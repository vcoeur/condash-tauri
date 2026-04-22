//! axum HTTP server — the Phase 2 read-only route surface.
//!
//! The Tauri host owns the `RenderCtx` + `WorkspaceCache` and spawns
//! this server on a free localhost port at startup. The main webview
//! then navigates to `http://127.0.0.1:<port>/` so the dashboard's
//! existing JS — which speaks plain HTTP fetches — stays unchanged
//! between the Python and Rust builds.
//!
//! Routes mounted here:
//!
//! - `GET /` — full dashboard page (cards + knowledge + git strip)
//! - `GET /fragment?id=<node-id>` — per-card / per-family HTML
//! - `GET /check-updates` — fingerprint bundle for the long-poll
//! - `GET /search-history?q=<query>` — history-tab search
//! - `GET /favicon.svg`, `GET /favicon.ico` — window icon
//! - `GET /vendor/<lib>/<path>` — bundled PDF.js / xterm / etc.
//! - `GET /assets/dist/<path>` — esbuild-built dashboard bundle
//! - `GET /asset/<path>` — any file under the conception tree
//!   (notes, deliverables, file-tree previews)
//!
//! Phase 3 slice 2 added the step-mutation surface:
//!
//! - `POST /toggle`         — flip one checkbox's state
//! - `POST /add-step`       — insert a new `- [ ]` line
//! - `POST /remove-step`    — drop a checkbox line
//! - `POST /edit-step`      — rewrite a checkbox's body
//! - `POST /set-priority`   — update the `**Status**` metadata line
//! - `POST /reorder-all`    — shuffle checkboxes within their section
//!
//! Phase 3 slice 3 added the file-level mutation surface:
//!
//! - `POST /note`           — atomically overwrite a note file
//! - `POST /note/rename`    — rename a file under `<item>/notes/`
//! - `POST /note/create`    — create an empty note file
//! - `POST /note/mkdir`     — create a (nested) directory under an item
//! - `POST /note/upload`    — multipart file uploads (≤ 50 MB each)
//! - `POST /create-item`    — scaffold a new project/incident/document
//!
//! Phase 3 slice 4 added the SSE channel:
//!
//! - `GET /events`          — server-sent events (fan-out from the
//!   filesystem watcher in `events.rs`; `hello` frame on connect, then
//!   per-tab staleness payloads, with a 30 s keep-alive `ping`)
//!
//! Phase 4 slice 1 added the embedded terminal WebSocket:
//!
//! - `GET /ws/term`         — upgrade to a WebSocket streaming PTY
//!   bytes. `info` frame on connect, binary frames for output, text
//!   JSON for `exit`, `session-expired`, and `error`. Reattach via
//!   `?session_id=…`, override cwd via `?cwd=…`, launcher mode via
//!   `?launcher=1` (falls back to login shell until the config layer
//!   exposes `terminal.launcher_command`).
//!
//! Phase 4 slice 2 added the inline dev-server runner surface:
//!
//! - `POST /api/runner/start` — spawn a dev server for a configured
//!   repo key (template from `ctx.repo_run_templates`, sandbox-gated
//!   path)
//! - `POST /api/runner/stop`  — SIGTERM + reap the runner session and
//!   clear its registry slot
//! - `GET  /ws/runner/:key`   — attach a WebSocket viewer to an
//!   existing runner's PTY; no-spawn on miss
//!
//! Routes *not* ported here (Phase 5+ territory): `/note-raw`
//! (read-side convenience endpoint; the bulk-read `/note` write path
//! already covers the primary editor flow) and the config-editing
//! surface.

use std::collections::HashMap;
use std::net::{SocketAddr, TcpListener};
use std::sync::Arc;

use anyhow::{Context, Result};
use axum::body::Body;
use axum::extract::{Query, State};
use axum::http::{header, HeaderValue, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use axum::{Json, Router};
use chrono::Datelike;
use condash_mutations::write_note;
use condash_mutations::{
    add_step, create_item, create_note, create_notes_subdir, edit_step, remove_step, rename_note,
    reorder_all, set_priority, store_uploads, toggle_checkbox, CreateItemResult, CreateNoteResult,
    CreateSubdirResult, NewItemSpec, RenameResult, WriteNoteResult,
};
use condash_parser::{
    compute_fingerprint, compute_knowledge_node_fingerprints, compute_project_node_fingerprints,
};
use condash_parser::{find_card, find_node};
use condash_render::git_render::render_git_repo_fragment;
use condash_render::{
    render_card_fragment, render_knowledge_card_fragment, render_knowledge_group_fragment,
    render_page,
};
use condash_state::{
    collect_git_repos, compute_git_node_fingerprints, git_fingerprint, search_items, RenderCtx,
    WorkspaceCache,
};
use futures_util::SinkExt;
use serde::Deserialize;
use tokio::net::TcpListener as TokioTcpListener;

/// Application state shared across every handler. Cheap to clone
/// (all fields live behind `Arc`).
#[derive(Clone)]
pub struct AppState {
    pub ctx: Arc<RenderCtx>,
    pub cache: Arc<WorkspaceCache>,
    /// Source of the dashboard shell (`dashboard.html`),
    /// `favicon.{svg,ico}`, `dist/`, and `vendor/`. Production binaries
    /// use [`assets::AssetSource::Embedded`]; dev runs can flip to
    /// [`assets::AssetSource::Disk`] via the `CONDASH_ASSET_DIR` env
    /// var. Phase 5 step 1 landed the embedded variant so the binary
    /// is self-contained.
    pub assets: crate::assets::AssetSource,
    /// Version string stamped into the dashboard shell at `{{VERSION}}`.
    pub version: Arc<String>,
    /// Fan-out for filesystem-driven staleness events. Cloneable — each
    /// `/events` subscriber grabs its own `broadcast::Receiver`.
    pub event_bus: crate::events::EventBus,
    /// Per-process registry of live PTY sessions — the `/ws/term`
    /// WebSocket handler looks up sessions here.
    pub pty_registry: crate::pty::PtyRegistry,
    /// Per-process registry of inline dev-server runners — used by
    /// `/api/runner/{start,stop}` and `/ws/runner/:key`.
    pub runner_registry: crate::runners::RunnerRegistry,
}

/// Start the axum server on a free localhost port and return the port
/// so the caller can point the Tauri webview at it. The server runs
/// forever on the current tokio runtime.
pub async fn start(state: AppState) -> Result<u16> {
    start_on(state, 0).await
}

/// Start the axum server on an explicit port (`0` means any free port).
pub async fn start_on(state: AppState, port: u16) -> Result<u16> {
    let std_listener = TcpListener::bind(SocketAddr::from(([127, 0, 0, 1], port)))
        .context("binding 127.0.0.1 for the dashboard HTTP server")?;
    std_listener.set_nonblocking(true)?;
    let port = std_listener.local_addr()?.port();

    let listener = TokioTcpListener::from_std(std_listener)?;
    let app = build_router(state);
    tokio::spawn(async move {
        if let Err(e) = axum::serve(listener, app).await {
            eprintln!("condash: HTTP server exited: {e}");
        }
    });
    Ok(port)
}

pub fn build_router(state: AppState) -> Router {
    Router::new()
        .route("/", get(index))
        .route("/fragment", get(fragment))
        .route("/check-updates", get(check_updates))
        .route("/search-history", get(search_history))
        .route("/favicon.svg", get(favicon_svg))
        .route("/favicon.ico", get(favicon_ico))
        .route("/vendor/{*path}", get(vendor_asset))
        .route("/assets/dist/{*path}", get(dist_asset))
        .route("/asset/{*path}", get(conception_asset))
        // Phase 3 slice 2 — step mutations.
        .route("/toggle", post(toggle))
        .route("/add-step", post(add_step_route))
        .route("/remove-step", post(remove_step_route))
        .route("/edit-step", post(edit_step_route))
        .route("/set-priority", post(set_priority_route))
        .route("/reorder-all", post(reorder_all_route))
        // Phase 3 slice 4 — SSE events channel.
        .route("/events", get(events_stream))
        // Phase 4 slice 1 — embedded terminal WebSocket.
        .route("/ws/term", get(term_ws))
        // Phase 4 slice 2 — inline dev-server runners.
        .route("/api/runner/start", post(runner_start_route))
        .route("/api/runner/stop", post(runner_stop_route))
        .route("/ws/runner/{key}", get(runner_ws))
        // Phase 3 slice 3 — file-level mutations.
        .route("/note", post(post_note))
        .route("/note/rename", post(post_note_rename))
        .route("/note/create", post(post_note_create))
        .route("/note/mkdir", post(post_note_mkdir))
        .route("/note/upload", post(post_note_upload))
        .route("/create-item", post(post_create_item))
        .with_state(state)
}

// ---------------------------------------------------------------------
// Phase 3 slice 2: step-mutation handlers.
// Shape matches `src/condash/routes/steps.py` — each handler validates
// the README path with `paths::validate_readme_path`, delegates to the
// matching helper in `condash-mutations`, and — on success — flushes
// the items cache so the next `/check-updates` sees a fresh fingerprint.
// ---------------------------------------------------------------------

#[derive(Debug, Deserialize)]
struct TogglePayload {
    file: String,
    line: i64,
}

async fn toggle(State(state): State<AppState>, Json(p): Json<TogglePayload>) -> impl IntoResponse {
    let Some(full) = crate::paths::validate_readme_path(&state.ctx.base_dir, &p.file) else {
        return error_json(StatusCode::BAD_REQUEST, "invalid path");
    };
    if p.line < 0 {
        return error_json(StatusCode::BAD_REQUEST, "not a checkbox line");
    }
    match toggle_checkbox(&full, p.line as usize) {
        Ok(Some(status)) => {
            state.cache.invalidate_items();
            json_response(&serde_json::json!({
                "ok": true,
                "status": status,
            }))
        }
        Ok(None) => error_json(StatusCode::BAD_REQUEST, "not a checkbox line"),
        Err(e) => error_json(StatusCode::INTERNAL_SERVER_ERROR, &format!("toggle: {e}")),
    }
}

#[derive(Debug, Deserialize)]
struct AddStepPayload {
    file: String,
    text: Option<String>,
    #[serde(default)]
    section: Option<String>,
}

async fn add_step_route(
    State(state): State<AppState>,
    Json(p): Json<AddStepPayload>,
) -> impl IntoResponse {
    let text = p.text.unwrap_or_default();
    let text = text.trim();
    if text.is_empty() {
        return error_json(StatusCode::BAD_REQUEST, "empty text");
    }
    let Some(full) = crate::paths::validate_readme_path(&state.ctx.base_dir, &p.file) else {
        return error_json(StatusCode::BAD_REQUEST, "invalid path");
    };
    let section = p.section.as_deref();
    match add_step(&full, text, section) {
        Ok(line) => {
            state.cache.invalidate_items();
            json_response(&serde_json::json!({"ok": true, "line": line}))
        }
        Err(e) => error_json(StatusCode::INTERNAL_SERVER_ERROR, &format!("add-step: {e}")),
    }
}

#[derive(Debug, Deserialize)]
struct RemoveStepPayload {
    file: String,
    line: i64,
}

async fn remove_step_route(
    State(state): State<AppState>,
    Json(p): Json<RemoveStepPayload>,
) -> impl IntoResponse {
    let Some(full) = crate::paths::validate_readme_path(&state.ctx.base_dir, &p.file) else {
        return error_json(StatusCode::BAD_REQUEST, "invalid path");
    };
    if p.line < 0 {
        return error_json(StatusCode::BAD_REQUEST, "cannot remove");
    }
    match remove_step(&full, p.line as usize) {
        Ok(true) => {
            state.cache.invalidate_items();
            json_response(&serde_json::json!({"ok": true}))
        }
        Ok(false) => error_json(StatusCode::BAD_REQUEST, "cannot remove"),
        Err(e) => error_json(StatusCode::INTERNAL_SERVER_ERROR, &format!("remove: {e}")),
    }
}

#[derive(Debug, Deserialize)]
struct EditStepPayload {
    file: String,
    line: i64,
    text: Option<String>,
}

async fn edit_step_route(
    State(state): State<AppState>,
    Json(p): Json<EditStepPayload>,
) -> impl IntoResponse {
    let text = p.text.unwrap_or_default();
    let text = text.trim();
    if text.is_empty() {
        return error_json(StatusCode::BAD_REQUEST, "empty text");
    }
    let Some(full) = crate::paths::validate_readme_path(&state.ctx.base_dir, &p.file) else {
        return error_json(StatusCode::BAD_REQUEST, "invalid path");
    };
    if p.line < 0 {
        return error_json(StatusCode::BAD_REQUEST, "cannot edit");
    }
    match edit_step(&full, p.line as usize, text) {
        Ok(true) => {
            state.cache.invalidate_items();
            json_response(&serde_json::json!({"ok": true}))
        }
        Ok(false) => error_json(StatusCode::BAD_REQUEST, "cannot edit"),
        Err(e) => error_json(StatusCode::INTERNAL_SERVER_ERROR, &format!("edit: {e}")),
    }
}

#[derive(Debug, Deserialize)]
struct SetPriorityPayload {
    file: String,
    priority: String,
}

async fn set_priority_route(
    State(state): State<AppState>,
    Json(p): Json<SetPriorityPayload>,
) -> impl IntoResponse {
    let Some(full) = crate::paths::validate_readme_path(&state.ctx.base_dir, &p.file) else {
        return error_json(StatusCode::BAD_REQUEST, "invalid path");
    };
    match set_priority(&full, &p.priority) {
        Ok(true) => {
            state.cache.invalidate_items();
            json_response(&serde_json::json!({
                "ok": true,
                "priority": p.priority,
            }))
        }
        Ok(false) => error_json(StatusCode::BAD_REQUEST, "invalid priority"),
        Err(e) => error_json(
            StatusCode::INTERNAL_SERVER_ERROR,
            &format!("set-priority: {e}"),
        ),
    }
}

#[derive(Debug, Deserialize)]
struct ReorderAllPayload {
    file: String,
    order: Vec<i64>,
}

async fn reorder_all_route(
    State(state): State<AppState>,
    Json(p): Json<ReorderAllPayload>,
) -> impl IntoResponse {
    let Some(full) = crate::paths::validate_readme_path(&state.ctx.base_dir, &p.file) else {
        return error_json(StatusCode::BAD_REQUEST, "invalid path");
    };
    if p.order.iter().any(|&n| n < 0) {
        return error_json(StatusCode::BAD_REQUEST, "cannot reorder");
    }
    let order: Vec<usize> = p.order.iter().map(|&n| n as usize).collect();
    match reorder_all(&full, &order) {
        Ok(true) => {
            state.cache.invalidate_items();
            json_response(&serde_json::json!({"ok": true}))
        }
        Ok(false) => error_json(StatusCode::BAD_REQUEST, "cannot reorder"),
        Err(e) => error_json(StatusCode::INTERNAL_SERVER_ERROR, &format!("reorder: {e}")),
    }
}

// ---------------------------------------------------------------------
// Phase 3 slice 3: file-level mutation handlers.
// Shape matches `src/condash/routes/notes.py` and
// `src/condash/routes/items.py`.
// ---------------------------------------------------------------------

#[derive(Debug, Deserialize)]
struct NoteWritePayload {
    path: String,
    content: String,
    #[serde(default)]
    expected_mtime: Option<f64>,
}

async fn post_note(
    State(state): State<AppState>,
    Json(p): Json<NoteWritePayload>,
) -> impl IntoResponse {
    let Some(full) = crate::paths::validate_note_path(&state.ctx.base_dir, &p.path) else {
        return error_json(StatusCode::FORBIDDEN, "invalid path");
    };
    let kind = condash_parser::note_kind(&full);
    if kind != "md" && kind != "text" {
        return error_json(StatusCode::BAD_REQUEST, "not editable");
    }
    match write_note(&full, &p.content, p.expected_mtime) {
        Ok(WriteNoteResult::Ok { mtime, .. }) => {
            state.cache.invalidate_items();
            json_response(&serde_json::json!({"ok": true, "mtime": mtime}))
        }
        Ok(WriteNoteResult::Err { reason, mtime, .. }) => {
            let body = match mtime {
                Some(m) => serde_json::json!({"ok": false, "reason": reason, "mtime": m}),
                None => serde_json::json!({"ok": false, "reason": reason}),
            };
            json_with_status(&body, StatusCode::CONFLICT)
        }
        Err(e) => error_json(StatusCode::INTERNAL_SERVER_ERROR, &format!("note: {e}")),
    }
}

#[derive(Debug, Deserialize)]
struct NoteRenamePayload {
    path: String,
    new_stem: String,
}

async fn post_note_rename(
    State(state): State<AppState>,
    Json(p): Json<NoteRenamePayload>,
) -> impl IntoResponse {
    let Some(full) = crate::paths::validate_note_path(&state.ctx.base_dir, &p.path) else {
        return error_json(StatusCode::BAD_REQUEST, "invalid path");
    };
    if !crate::paths::is_item_notes_file(&p.path) {
        return error_json(
            StatusCode::BAD_REQUEST,
            "only files under <item>/notes/ can be renamed",
        );
    }
    match rename_note(&full, &p.new_stem, &state.ctx.base_dir) {
        Ok(RenameResult::Ok { path, mtime, .. }) => {
            state.cache.invalidate_items();
            json_response(&serde_json::json!({"ok": true, "path": path, "mtime": mtime}))
        }
        Ok(RenameResult::Err { reason, .. }) => error_json(StatusCode::BAD_REQUEST, &reason),
        Err(e) => error_json(StatusCode::INTERNAL_SERVER_ERROR, &format!("rename: {e}")),
    }
}

#[derive(Debug, Deserialize)]
struct NoteCreatePayload {
    item_readme: String,
    filename: String,
    #[serde(default)]
    subdir: String,
}

async fn post_note_create(
    State(state): State<AppState>,
    Json(p): Json<NoteCreatePayload>,
) -> impl IntoResponse {
    let Some(readme) = crate::paths::validate_readme_path(&state.ctx.base_dir, &p.item_readme)
    else {
        return error_json(StatusCode::BAD_REQUEST, "invalid item");
    };
    let Some(item_dir) = readme.parent() else {
        return error_json(StatusCode::BAD_REQUEST, "invalid item");
    };
    let Some(target_dir) = crate::paths::resolve_under_item(item_dir, &p.subdir) else {
        return error_json(StatusCode::BAD_REQUEST, "invalid subdirectory");
    };
    let subdir_was_supplied = !p.subdir.trim().trim_matches('/').is_empty();
    match create_note(
        &target_dir,
        &p.filename,
        &state.ctx.base_dir,
        subdir_was_supplied,
    ) {
        Ok(CreateNoteResult::Ok { path, mtime, .. }) => {
            state.cache.invalidate_items();
            json_response(&serde_json::json!({"ok": true, "path": path, "mtime": mtime}))
        }
        Ok(CreateNoteResult::Err { reason, .. }) => error_json(StatusCode::BAD_REQUEST, &reason),
        Err(e) => error_json(
            StatusCode::INTERNAL_SERVER_ERROR,
            &format!("create-note: {e}"),
        ),
    }
}

#[derive(Debug, Deserialize)]
struct NoteMkdirPayload {
    item_readme: String,
    subpath: String,
}

async fn post_note_mkdir(
    State(state): State<AppState>,
    Json(p): Json<NoteMkdirPayload>,
) -> impl IntoResponse {
    let Some(readme) = crate::paths::validate_readme_path(&state.ctx.base_dir, &p.item_readme)
    else {
        return error_json(StatusCode::BAD_REQUEST, "invalid item");
    };
    let Some(item_dir) = readme.parent() else {
        return error_json(StatusCode::BAD_REQUEST, "invalid item");
    };
    let trimmed = p.subpath.trim().trim_matches('/').to_string();
    if trimmed.is_empty() {
        return error_json(StatusCode::BAD_REQUEST, "invalid subdirectory name");
    }
    let Some(target_dir) = crate::paths::resolve_under_item(item_dir, &trimmed) else {
        return error_json(StatusCode::BAD_REQUEST, "invalid subdirectory name");
    };
    let item_name = item_dir
        .file_name()
        .map(|n| n.to_string_lossy().into_owned())
        .unwrap_or_default();
    match create_notes_subdir(&target_dir, &trimmed, &item_name) {
        Ok(CreateSubdirResult::Ok {
            rel_dir,
            subdir_key,
            ..
        }) => {
            state.cache.invalidate_items();
            json_response(&serde_json::json!({
                "ok": true,
                "rel_dir": rel_dir,
                "subdir_key": subdir_key,
            }))
        }
        Ok(CreateSubdirResult::Err { reason, .. }) => {
            let code = if reason == "exists" {
                StatusCode::CONFLICT
            } else {
                StatusCode::BAD_REQUEST
            };
            json_with_status(&serde_json::json!({"ok": false, "reason": reason}), code)
        }
        Err(e) => error_json(StatusCode::INTERNAL_SERVER_ERROR, &format!("mkdir: {e}")),
    }
}

/// 50 MB per-file cap — mirrors Python's `max_bytes_per_file` default.
const UPLOAD_MAX_BYTES: u64 = 50 * 1024 * 1024;

async fn post_note_upload(
    State(state): State<AppState>,
    mut mp: axum::extract::Multipart,
) -> Response {
    let mut item_readme: String = String::new();
    let mut subdir: String = String::new();
    let mut uploads: Vec<(String, Vec<u8>)> = Vec::new();

    loop {
        let field = match mp.next_field().await {
            Ok(Some(f)) => f,
            Ok(None) => break,
            Err(e) => {
                return error_json(StatusCode::BAD_REQUEST, &format!("multipart: {e}"));
            }
        };
        let name = field.name().unwrap_or("").to_string();
        match name.as_str() {
            "item_readme" => {
                item_readme = field.text().await.unwrap_or_default();
            }
            "subdir" => {
                subdir = field.text().await.unwrap_or_default();
            }
            "file" => {
                let filename = field.file_name().unwrap_or("").to_string();
                match field.bytes().await {
                    Ok(b) => uploads.push((filename, b.to_vec())),
                    Err(e) => {
                        return error_json(StatusCode::BAD_REQUEST, &format!("upload read: {e}"));
                    }
                }
            }
            _ => {
                // Silently drop unknown fields — matches Python which
                // only picks `item_readme`, `subdir`, `file` keys.
                let _ = field.bytes().await;
            }
        }
    }

    if uploads.is_empty() {
        return error_json(StatusCode::BAD_REQUEST, "no files in upload");
    }

    let Some(readme) = crate::paths::validate_readme_path(&state.ctx.base_dir, &item_readme) else {
        return error_json(StatusCode::BAD_REQUEST, "invalid item");
    };
    let Some(item_dir) = readme.parent() else {
        return error_json(StatusCode::BAD_REQUEST, "invalid item");
    };
    let Some(target_dir) = crate::paths::resolve_under_item(item_dir, &subdir) else {
        return error_json(StatusCode::BAD_REQUEST, "invalid subdirectory");
    };
    let subdir_was_supplied = !subdir.trim().trim_matches('/').is_empty();

    // Re-shape each upload as (String, Cursor<Vec<u8>>) so it implements Read.
    let read_uploads: Vec<(String, std::io::Cursor<Vec<u8>>)> = uploads
        .into_iter()
        .map(|(n, b)| (n, std::io::Cursor::new(b)))
        .collect();

    match store_uploads(
        &target_dir,
        &state.ctx.base_dir,
        read_uploads,
        subdir_was_supplied,
        UPLOAD_MAX_BYTES,
    ) {
        Ok(res) => {
            if !res.ok {
                // Short-circuit case — e.g. subdirectory does not exist.
                let reason = res
                    .rejected
                    .first()
                    .map(|r| r.reason.clone())
                    .unwrap_or_else(|| "upload failed".into());
                return error_json(StatusCode::BAD_REQUEST, &reason);
            }
            state.cache.invalidate_items();
            json_response(&serde_json::json!({
                "ok": true,
                "stored": res.stored,
                "rejected": res.rejected,
            }))
        }
        Err(e) => error_json(StatusCode::INTERNAL_SERVER_ERROR, &format!("upload: {e}")),
    }
}

#[derive(Debug, Deserialize)]
struct CreateItemPayload {
    #[serde(default)]
    title: String,
    #[serde(default)]
    slug: String,
    #[serde(default)]
    kind: String,
    #[serde(default)]
    status: String,
    #[serde(default)]
    apps: String,
    #[serde(default)]
    environment: String,
    #[serde(default)]
    severity: String,
    #[serde(default)]
    languages: String,
}

async fn post_create_item(
    State(state): State<AppState>,
    Json(p): Json<CreateItemPayload>,
) -> impl IntoResponse {
    let today = chrono::Local::now().date_naive();
    let ymd = (today.year() as u16, today.month() as u8, today.day() as u8);
    let spec = NewItemSpec {
        title: p.title,
        slug: p.slug,
        kind: p.kind,
        status: p.status,
        apps: p.apps,
        environment: p.environment,
        severity: p.severity,
        languages: p.languages,
    };
    match create_item(&state.ctx.base_dir, spec, ymd) {
        Ok(CreateItemResult::Ok {
            rel_path,
            slug,
            folder_name,
            priority,
            month,
            ..
        }) => {
            state.cache.invalidate_items();
            json_response(&serde_json::json!({
                "ok": true,
                "rel_path": rel_path,
                "slug": slug,
                "folder_name": folder_name,
                "priority": priority,
                "month": month,
            }))
        }
        Ok(CreateItemResult::Err { reason, .. }) => error_json(StatusCode::BAD_REQUEST, &reason),
        Err(e) => error_json(
            StatusCode::INTERNAL_SERVER_ERROR,
            &format!("create-item: {e}"),
        ),
    }
}

fn json_with_status<T: serde::Serialize>(body: &T, code: StatusCode) -> Response {
    let bytes = match serde_json::to_vec(body) {
        Ok(b) => b,
        Err(e) => return error(StatusCode::INTERNAL_SERVER_ERROR, &format!("json: {e}")),
    };
    Response::builder()
        .status(code)
        .header(header::CONTENT_TYPE, "application/json")
        .body(Body::from(bytes))
        .unwrap()
}

/// JSON error response matching `routes/_common.error()` — a
/// `{"error": <msg>}` body plus the given status code.
fn error_json(code: StatusCode, msg: &str) -> Response {
    let body = serde_json::json!({"error": msg});
    let bytes = serde_json::to_vec(&body).unwrap_or_default();
    Response::builder()
        .status(code)
        .header(header::CONTENT_TYPE, "application/json")
        .body(Body::from(bytes))
        .unwrap()
}

async fn index(State(state): State<AppState>) -> impl IntoResponse {
    let items = state.cache.get_items(&state.ctx);
    let knowledge = state.cache.get_knowledge(&state.ctx);
    let html = render_page(
        &state.ctx,
        &items,
        knowledge.as_ref().as_ref(),
        &state.version,
    );
    html_response(html)
}

#[derive(Debug, Deserialize)]
struct FragmentQuery {
    #[serde(default)]
    id: String,
}

async fn fragment(
    State(state): State<AppState>,
    Query(q): Query<FragmentQuery>,
) -> impl IntoResponse {
    let id = q.id;
    if id.is_empty() {
        return error(StatusCode::BAD_REQUEST, "missing id");
    }

    if let Some(rest) = id.strip_prefix("projects/") {
        // projects/<priority>/<slug> — look up the card by slug.
        let parts: Vec<&str> = rest.splitn(2, '/').collect();
        if parts.len() != 2 {
            return error(StatusCode::NOT_FOUND, "not a card id");
        }
        let slug = parts[1];
        let items = state.cache.get_items(&state.ctx);
        for item in items.iter() {
            if item.readme.slug == slug {
                return html_response(render_card_fragment(item));
            }
        }
        return error(StatusCode::NOT_FOUND, "card not found");
    }

    if id == "knowledge" {
        // Root tab — fall back to global reload like Python.
        return error(StatusCode::NOT_FOUND, "use global reload");
    }

    if let Some(rest) = id.strip_prefix("code/") {
        if !rest.contains('/') {
            // A bare code group — only whole-repo nodes are fragmentable.
            return error(StatusCode::NOT_FOUND, "use global reload");
        }
        let groups = collect_git_repos(&state.ctx);
        if let Some(html) = render_git_repo_fragment(&state.ctx, &groups, &id) {
            return html_response(html);
        }
        return error(StatusCode::NOT_FOUND, "repo not found");
    }

    if id.starts_with("knowledge/") {
        let tree = state.cache.get_knowledge(&state.ctx);
        let root = tree.as_ref().as_ref();
        if id.ends_with(".md") {
            if let Some(card) = find_card(root, &id) {
                return html_response(render_knowledge_card_fragment(card));
            }
            return error(StatusCode::NOT_FOUND, "card not found");
        }
        if let Some(node) = find_node(root, &id) {
            return html_response(render_knowledge_group_fragment(node));
        }
        return error(StatusCode::NOT_FOUND, "dir not found");
    }

    error(StatusCode::NOT_FOUND, "unsupported id")
}

// ---------------------------------------------------------------------
// Phase 4 slice 1: /ws/term embedded-terminal handler.
// Mirrors `routes/terminals.py` + `pty.py::attach_ws`:
// - Query params: `session_id` (reattach), `cwd` (override working dir),
//   `launcher` (=1 to spawn the configured launcher instead of a shell).
// - Frames: `info` on attach, `session-expired` for stale reattach,
//   `error` when PTY isn't supported, `exit` when the shell exits.
// - The PTY survives a ws disconnect (only the viewer detaches).
// ---------------------------------------------------------------------

#[derive(Debug, Deserialize)]
struct TermQuery {
    #[serde(default)]
    session_id: Option<String>,
    #[serde(default)]
    cwd: Option<String>,
    #[serde(default)]
    launcher: Option<String>,
}

async fn term_ws(
    ws: axum::extract::ws::WebSocketUpgrade,
    State(state): State<AppState>,
    Query(q): Query<TermQuery>,
) -> impl IntoResponse {
    ws.on_upgrade(move |socket| handle_term_ws(socket, state, q))
}

async fn handle_term_ws(mut socket: axum::extract::ws::WebSocket, state: AppState, q: TermQuery) {
    use axum::extract::ws::Message;

    if !crate::pty::supports_pty() {
        let _ = socket
            .send(Message::Text(
                serde_json::json!({
                    "type": "error",
                    "message": "Terminal only supported on Linux/macOS.",
                })
                .to_string()
                .into(),
            ))
            .await;
        let _ = socket.close().await;
        return;
    }

    let requested_id = q.session_id.as_deref().filter(|s| !s.is_empty());
    let existing = requested_id.and_then(|id| state.pty_registry.get(id));

    if let Some(id) = requested_id {
        if existing.is_none() {
            // Reattach to an unknown session — tell the client so it can
            // drop the stale id from its localStorage instead of silently
            // starting a new shell under the same tab.
            let _ = socket
                .send(Message::Text(
                    serde_json::json!({
                        "type": "session-expired",
                        "session_id": id,
                    })
                    .to_string()
                    .into(),
                ))
                .await;
            let _ = socket.close().await;
            return;
        }
    }

    let session = if let Some(s) = existing {
        // Displace any stale viewer — one attached ws per session.
        s.detach_viewer();
        s
    } else {
        let cwd = q
            .cwd
            .as_deref()
            .and_then(|c| {
                let candidate = std::path::PathBuf::from(c);
                if candidate.is_dir() {
                    Some(candidate)
                } else {
                    None
                }
            })
            .unwrap_or_else(|| state.ctx.base_dir.clone());
        let use_launcher = q.launcher.as_deref() == Some("1");
        let mode = if use_launcher {
            // Phase 4 slice 2 will pipe the launcher command through
            // config; for this slice we fall back to the shell so the
            // handler still produces a usable terminal.
            crate::pty::SpawnMode::LoginShell {
                shell: crate::pty::resolve_terminal_shell(None),
            }
        } else {
            crate::pty::SpawnMode::LoginShell {
                shell: crate::pty::resolve_terminal_shell(None),
            }
        };
        match crate::pty::spawn_session(&state.pty_registry, mode, cwd, 80, 24) {
            Ok(s) => s,
            Err(e) => {
                let _ = socket
                    .send(Message::Text(
                        serde_json::json!({
                            "type": "error",
                            "message": format!("spawn failed: {e}"),
                        })
                        .to_string()
                        .into(),
                    ))
                    .await;
                let _ = socket.close().await;
                return;
            }
        }
    };

    // Info frame — shell, cwd, session id.
    let info = serde_json::json!({
        "type": "info",
        "session_id": session.session_id,
        "shell": session.shell,
        "cwd": session.cwd.to_string_lossy(),
    });
    if socket
        .send(Message::Text(info.to_string().into()))
        .await
        .is_err()
    {
        return;
    }

    // Attach this socket as the viewer. The buffer replay is pushed
    // into the channel by attach_viewer itself.
    let mut rx = session.attach_viewer();

    // Fan out incoming PumpMessage frames to the socket, and route
    // incoming ws frames to the pty writer — both concurrently.
    loop {
        tokio::select! {
            msg = rx.recv() => match msg {
                Some(crate::pty::PumpMessage::Data(bytes)) => {
                    if socket.send(Message::Binary(bytes.into())).await.is_err() {
                        break;
                    }
                }
                Some(crate::pty::PumpMessage::Exit) => {
                    let _ = socket
                        .send(Message::Text(
                            serde_json::json!({"type": "exit"}).to_string().into(),
                        ))
                        .await;
                    let _ = socket.close().await;
                    return;
                }
                None => {
                    // Viewer channel dropped (e.g. displaced by another
                    // connection). Close the ws so the client reconnects.
                    let _ = socket.close().await;
                    return;
                }
            },
            ws_msg = socket.recv() => match ws_msg {
                Some(Ok(Message::Binary(bytes))) => {
                    if session.write_input(&bytes).is_err() {
                        break;
                    }
                }
                Some(Ok(Message::Text(text))) => {
                    if let Ok(val) = serde_json::from_str::<serde_json::Value>(&text) {
                        if val.get("type").and_then(|v| v.as_str()) == Some("resize") {
                            let cols = val
                                .get("cols")
                                .and_then(|v| v.as_u64())
                                .unwrap_or(80) as u16;
                            let rows = val
                                .get("rows")
                                .and_then(|v| v.as_u64())
                                .unwrap_or(24) as u16;
                            session.resize(cols, rows);
                        }
                    }
                }
                Some(Ok(Message::Close(_))) | None => break,
                Some(Ok(_)) => {}
                Some(Err(_)) => break,
            }
        }
    }

    session.detach_viewer();
}

// ---------------------------------------------------------------------
// Phase 4 slice 2: runner routes.
// - `POST /api/runner/start` — spawn a dev server for a configured key
// - `POST /api/runner/stop`  — SIGTERM + reap + clear
// - `GET  /ws/runner/:key`   — attach a viewer to the live session
// ---------------------------------------------------------------------

#[derive(Debug, Deserialize)]
struct RunnerStartPayload {
    #[serde(default)]
    key: String,
    #[serde(default)]
    checkout_key: String,
    #[serde(default)]
    path: String,
}

async fn runner_start_route(
    State(state): State<AppState>,
    Json(p): Json<RunnerStartPayload>,
) -> impl IntoResponse {
    let key = p.key.trim();
    let checkout_key = p.checkout_key.trim();
    let path_raw = p.path.trim();
    if key.is_empty() || checkout_key.is_empty() || path_raw.is_empty() {
        return error_json(StatusCode::BAD_REQUEST, "key, checkout_key, path required");
    }
    let Some(template) = state.ctx.repo_run_templates.get(key).cloned() else {
        return error_json(
            StatusCode::NOT_FOUND,
            &format!("no run command configured for {key}"),
        );
    };
    let Some(validated) = validate_open_path(&state.ctx, path_raw) else {
        return error_json(
            StatusCode::BAD_REQUEST,
            &format!("path out of sandbox: {path_raw}"),
        );
    };
    if let Some(existing) = state.runner_registry.get(key) {
        if existing.exit_code_now().is_none() {
            return json_with_status(
                &serde_json::json!({
                    "error": "runner already active",
                    "key": key,
                    "checkout_key": existing.checkout_key,
                }),
                StatusCode::CONFLICT,
            );
        }
    }
    let shell = crate::pty::resolve_terminal_shell(None);
    match crate::runners::start(
        &state.runner_registry,
        &state.pty_registry,
        key,
        checkout_key,
        validated.to_str().unwrap_or(path_raw),
        &template,
        &shell,
    ) {
        Ok(session) => {
            let body = serde_json::json!({
                "ok": true,
                "key": session.key,
                "checkout_key": session.checkout_key,
                "pid": session.pty.session_id,
                "template": session.template,
            });
            json_response(&body)
        }
        Err(e) => error_json(StatusCode::INTERNAL_SERVER_ERROR, &format!("spawn: {e}")),
    }
}

#[derive(Debug, Deserialize)]
struct RunnerStopPayload {
    #[serde(default)]
    key: String,
}

async fn runner_stop_route(
    State(state): State<AppState>,
    Json(p): Json<RunnerStopPayload>,
) -> impl IntoResponse {
    let key = p.key.trim();
    if key.is_empty() {
        return error_json(StatusCode::BAD_REQUEST, "key required");
    }
    let Some(session) = state.runner_registry.get(key) else {
        return json_response(&serde_json::json!({"ok": true, "cleared": false}));
    };
    if session.exit_code_now().is_some() {
        crate::runners::clear_exited(&state.runner_registry, key);
        return json_response(&serde_json::json!({"ok": true, "cleared": true, "exited": true}));
    }
    match crate::runners::stop(
        &state.runner_registry,
        key,
        std::time::Duration::from_secs(5),
    )
    .await
    {
        Ok(_) => json_response(&serde_json::json!({"ok": true, "cleared": true})),
        Err(e) => error_json(StatusCode::INTERNAL_SERVER_ERROR, &format!("stop: {e}")),
    }
}

/// `/ws/runner/:key` — attach a viewer to an existing runner. Fails
/// closed with `session-missing` when the key has no live (or exited-
/// but-still-in-registry) entry; the Code tab posts `/api/runner/start`
/// first, so a miss here is unexpected.
async fn runner_ws(
    ws: axum::extract::ws::WebSocketUpgrade,
    State(state): State<AppState>,
    axum::extract::Path(key): axum::extract::Path<String>,
) -> impl IntoResponse {
    ws.on_upgrade(move |socket| handle_runner_ws(socket, state, key))
}

async fn handle_runner_ws(mut socket: axum::extract::ws::WebSocket, state: AppState, key: String) {
    use axum::extract::ws::Message;

    if !crate::pty::supports_pty() {
        let _ = socket
            .send(Message::Text(
                serde_json::json!({
                    "type": "error",
                    "message": "Runner only supported on Linux/macOS.",
                })
                .to_string()
                .into(),
            ))
            .await;
        let _ = socket.close().await;
        return;
    }

    let Some(session) = state.runner_registry.get(&key) else {
        let _ = socket
            .send(Message::Text(
                serde_json::json!({"type": "session-missing", "key": key})
                    .to_string()
                    .into(),
            ))
            .await;
        let _ = socket.close().await;
        return;
    };

    // Displace any stale viewer.
    session.pty.detach_viewer();

    let info = serde_json::json!({
        "type": "info",
        "key": session.key,
        "checkout_key": session.checkout_key,
        "path": session.path,
        "template": session.template,
        "exit_code": session.exit_code_now(),
    });
    if socket
        .send(Message::Text(info.to_string().into()))
        .await
        .is_err()
    {
        return;
    }

    let mut rx = session.pty.attach_viewer();

    // If the runner already exited, emit the exit frame once the buffer
    // has been drained so the client paints the greyed status line.
    if let Some(code) = session.exit_code_now() {
        let _ = socket
            .send(Message::Text(
                serde_json::json!({"type": "exit", "exit_code": code})
                    .to_string()
                    .into(),
            ))
            .await;
    }

    loop {
        tokio::select! {
            msg = rx.recv() => match msg {
                Some(crate::pty::PumpMessage::Data(bytes)) => {
                    if socket.send(Message::Binary(bytes.into())).await.is_err() {
                        break;
                    }
                }
                Some(crate::pty::PumpMessage::Exit) => {
                    let exit_code = session.exit_code_now().unwrap_or(0);
                    let _ = socket
                        .send(Message::Text(
                            serde_json::json!({"type": "exit", "exit_code": exit_code})
                                .to_string()
                                .into(),
                        ))
                        .await;
                    break;
                }
                None => break,
            },
            ws_msg = socket.recv() => match ws_msg {
                Some(Ok(Message::Binary(bytes))) => {
                    if session.exit_code_now().is_some() {
                        continue; // Swallow typing after exit.
                    }
                    if session.pty.write_input(&bytes).is_err() {
                        break;
                    }
                }
                Some(Ok(Message::Text(text))) => {
                    if let Ok(val) = serde_json::from_str::<serde_json::Value>(&text) {
                        if val.get("type").and_then(|v| v.as_str()) == Some("resize") {
                            let cols = val
                                .get("cols")
                                .and_then(|v| v.as_u64())
                                .unwrap_or(80) as u16;
                            let rows = val
                                .get("rows")
                                .and_then(|v| v.as_u64())
                                .unwrap_or(24) as u16;
                            if session.exit_code_now().is_none() {
                                session.pty.resize(cols, rows);
                            }
                        }
                    }
                }
                Some(Ok(Message::Close(_))) | None => break,
                Some(Ok(_)) => {}
                Some(Err(_)) => break,
            }
        }
    }
    session.pty.detach_viewer();
}

/// Validate a filesystem path as an in-sandbox directory under
/// `ctx.workspace` or `ctx.worktrees`. Rust port of
/// `paths._validate_open_path` from `paths.py`.
fn validate_open_path(ctx: &condash_state::RenderCtx, path: &str) -> Option<std::path::PathBuf> {
    if path.is_empty() || path.contains('\0') {
        return None;
    }
    let canonical = std::fs::canonicalize(path).ok()?;
    if !canonical.is_dir() {
        return None;
    }
    let roots: Vec<std::path::PathBuf> = [ctx.workspace.as_ref(), ctx.worktrees.as_ref()]
        .into_iter()
        .flatten()
        .filter_map(|p| std::fs::canonicalize(p).ok())
        .collect();
    for root in roots {
        if canonical.starts_with(&root) {
            return Some(canonical);
        }
    }
    None
}

/// `GET /events` — server-sent events stream. Mirrors
/// `routes/updates.py`'s `/events`: opens with a `hello` frame so the
/// browser's `EventSource.onopen` fires immediately, fans out the
/// event-bus payloads as `data:` frames, and punctuates the stream
/// with a 30-second keep-alive so reverse proxies don't kill an idle
/// connection.
async fn events_stream(
    State(state): State<AppState>,
) -> axum::response::Sse<
    impl futures_util::Stream<Item = Result<axum::response::sse::Event, std::convert::Infallible>>,
> {
    use axum::response::sse::{Event as SseEvent, KeepAlive};
    use futures_util::StreamExt;
    use tokio_stream::wrappers::BroadcastStream;

    let rx = state.event_bus.subscribe();
    let hello = futures_util::stream::once(async {
        Ok::<_, std::convert::Infallible>(SseEvent::default().event("hello").data("{}"))
    });
    let payloads = BroadcastStream::new(rx).filter_map(|res| async move {
        match res {
            Ok(payload) => {
                let data = serde_json::to_string(&payload).unwrap_or_else(|_| "{}".into());
                Some(Ok::<_, std::convert::Infallible>(
                    SseEvent::default().data(data),
                ))
            }
            // Subscriber lagged — the reconciler picks it up, just skip.
            Err(_) => None,
        }
    });
    let combined = hello.chain(payloads);
    axum::response::Sse::new(combined).keep_alive(
        KeepAlive::new()
            .interval(std::time::Duration::from_secs(30))
            .text("ping"),
    )
}

async fn check_updates(State(state): State<AppState>) -> impl IntoResponse {
    let items = state.cache.get_items(&state.ctx);
    let knowledge = state.cache.get_knowledge(&state.ctx);
    let mut nodes: HashMap<String, String> = HashMap::new();
    nodes.extend(compute_project_node_fingerprints(&items));
    nodes.extend(compute_knowledge_node_fingerprints(
        knowledge.as_ref().as_ref(),
    ));
    nodes.extend(compute_git_node_fingerprints(&state.ctx));
    let body = serde_json::json!({
        "fingerprint": compute_fingerprint(&items),
        "git_fingerprint": git_fingerprint(&state.ctx),
        "nodes": nodes,
    });
    json_response(&body)
}

#[derive(Debug, Deserialize)]
struct SearchQuery {
    #[serde(default)]
    q: String,
}

async fn search_history(
    State(state): State<AppState>,
    Query(s): Query<SearchQuery>,
) -> impl IntoResponse {
    let items = state.cache.get_items(&state.ctx);
    let results = search_items(&state.ctx, &items, &s.q);
    json_response(&results)
}

async fn favicon_svg(State(state): State<AppState>) -> impl IntoResponse {
    serve_embedded(&state.assets, "favicon.svg")
}

async fn favicon_ico(State(state): State<AppState>) -> impl IntoResponse {
    // Python serves the SVG for .ico too — the Tauri webview accepts
    // it as a window icon without complaint.
    serve_embedded(&state.assets, "favicon.svg")
}

async fn vendor_asset(
    State(state): State<AppState>,
    axum::extract::Path(rel_path): axum::extract::Path<String>,
) -> impl IntoResponse {
    serve_embedded(&state.assets, &format!("vendor/{rel_path}"))
}

async fn dist_asset(
    State(state): State<AppState>,
    axum::extract::Path(rel_path): axum::extract::Path<String>,
) -> impl IntoResponse {
    serve_embedded(&state.assets, &format!("dist/{rel_path}"))
}

/// Serve a file from the [`assets::AssetSource`] — embedded or on-disk.
/// Same traversal guards + caching headers the old `serve_fixed`
/// applied; differs only in the byte source.
fn serve_embedded(source: &crate::assets::AssetSource, rel_path: &str) -> Response {
    match source.load(rel_path) {
        Some((bytes, mime)) => {
            let mime = mime
                .parse::<HeaderValue>()
                .ok()
                .unwrap_or_else(|| HeaderValue::from_static("application/octet-stream"));
            Response::builder()
                .status(StatusCode::OK)
                .header(header::CONTENT_TYPE, mime)
                .header(header::CACHE_CONTROL, "public, max-age=86400")
                .body(Body::from(bytes.into_owned()))
                .unwrap()
        }
        None => error(StatusCode::NOT_FOUND, "no such asset"),
    }
}

async fn conception_asset(
    State(state): State<AppState>,
    axum::extract::Path(rel_path): axum::extract::Path<String>,
) -> impl IntoResponse {
    serve_under(&state.ctx.base_dir, &rel_path, None)
}

fn serve_under(base: &std::path::Path, rel: &str, mime_override: Option<&str>) -> Response {
    if rel.is_empty() || rel.contains('\0') {
        return error(StatusCode::FORBIDDEN, "bad path");
    }
    for part in rel.split('/') {
        if part.is_empty() || part == ".." {
            return error(StatusCode::FORBIDDEN, "path traversal");
        }
    }
    let full = base.join(rel);
    let canonical = match std::fs::canonicalize(&full) {
        Ok(c) => c,
        Err(_) => return error(StatusCode::NOT_FOUND, "no such file"),
    };
    let base_canonical = match std::fs::canonicalize(base) {
        Ok(c) => c,
        Err(_) => return error(StatusCode::NOT_FOUND, "base missing"),
    };
    if !canonical.starts_with(&base_canonical) {
        return error(StatusCode::FORBIDDEN, "outside base");
    }
    if !canonical.is_file() {
        return error(StatusCode::NOT_FOUND, "not a file");
    }
    serve_fixed(
        &canonical,
        mime_override.unwrap_or_else(|| guess_mime(&canonical)),
    )
}

fn serve_fixed(path: &std::path::Path, mime: &str) -> Response {
    match std::fs::read(path) {
        Ok(bytes) => Response::builder()
            .status(StatusCode::OK)
            .header(header::CONTENT_TYPE, mime)
            .header(header::CACHE_CONTROL, "public, max-age=86400")
            .body(Body::from(bytes))
            .unwrap(),
        Err(_) => error(StatusCode::NOT_FOUND, "read failed"),
    }
}

fn guess_mime(path: &std::path::Path) -> &'static str {
    match path.extension().and_then(|e| e.to_str()) {
        Some("mjs") | Some("js") => "text/javascript",
        Some("css") => "text/css",
        Some("json") => "application/json",
        Some("wasm") => "application/wasm",
        Some("svg") => "image/svg+xml",
        Some("png") => "image/png",
        Some("jpg") | Some("jpeg") => "image/jpeg",
        Some("gif") => "image/gif",
        Some("webp") => "image/webp",
        Some("pdf") => "application/pdf",
        Some("html") => "text/html; charset=utf-8",
        Some("md") | Some("txt") => "text/plain; charset=utf-8",
        _ => "application/octet-stream",
    }
}

fn html_response(body: String) -> Response {
    let mut r = Response::new(Body::from(body));
    r.headers_mut().insert(
        header::CONTENT_TYPE,
        HeaderValue::from_static("text/html; charset=utf-8"),
    );
    r
}

fn json_response<T: serde::Serialize>(body: &T) -> Response {
    let bytes = match serde_json::to_vec(body) {
        Ok(b) => b,
        Err(e) => return error(StatusCode::INTERNAL_SERVER_ERROR, &format!("json: {e}")),
    };
    let mut r = Response::new(Body::from(bytes));
    r.headers_mut().insert(
        header::CONTENT_TYPE,
        HeaderValue::from_static("application/json"),
    );
    r
}

fn error(code: StatusCode, msg: &str) -> Response {
    Response::builder()
        .status(code)
        .header(header::CONTENT_TYPE, "text/plain; charset=utf-8")
        .body(Body::from(format!("{code} — {msg}\n")))
        .unwrap()
}
