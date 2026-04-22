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
//! Routes *not* ported here (Phase 3+ territory): `/events` (SSE),
//! `/note`, `/note-raw`, file-level mutations (`/update`, `/rename`,
//! `/create-note`, `/create-item`, uploads), runners (`/ws/runner/…`),
//! terminal WebSockets.

use std::collections::HashMap;
use std::net::{SocketAddr, TcpListener};
use std::path::PathBuf;
use std::sync::Arc;

use anyhow::{Context, Result};
use axum::body::Body;
use axum::extract::{Query, State};
use axum::http::{header, HeaderValue, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use axum::{Json, Router};
use condash_mutations::{
    add_step, edit_step, remove_step, reorder_all, set_priority, toggle_checkbox,
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
use serde::Deserialize;
use tokio::net::TcpListener as TokioTcpListener;

/// Application state shared across every handler. Cheap to clone
/// (all fields live behind `Arc`).
#[derive(Clone)]
pub struct AppState {
    pub ctx: Arc<RenderCtx>,
    pub cache: Arc<WorkspaceCache>,
    /// On-disk directory containing `dashboard.html`, `favicon.svg`,
    /// `dist/`, and `vendor/`. Dev builds point at the Python package
    /// tree; production builds would bundle this via `rust-embed`
    /// (Phase 5 work).
    pub asset_dir: Arc<PathBuf>,
    /// Version string stamped into the dashboard shell at `{{VERSION}}`.
    pub version: Arc<String>,
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
    serve_fixed(&state.asset_dir.join("favicon.svg"), "image/svg+xml")
}

async fn favicon_ico(State(state): State<AppState>) -> impl IntoResponse {
    // Python serves the SVG for .ico too — the Tauri webview accepts
    // it as a window icon without complaint.
    serve_fixed(&state.asset_dir.join("favicon.svg"), "image/svg+xml")
}

async fn vendor_asset(
    State(state): State<AppState>,
    axum::extract::Path(rel_path): axum::extract::Path<String>,
) -> impl IntoResponse {
    serve_under(&state.asset_dir.join("vendor"), &rel_path, None)
}

async fn dist_asset(
    State(state): State<AppState>,
    axum::extract::Path(rel_path): axum::extract::Path<String>,
) -> impl IntoResponse {
    let mime = match std::path::Path::new(&rel_path)
        .extension()
        .and_then(|e| e.to_str())
    {
        Some("js") => Some("text/javascript"),
        Some("css") => Some("text/css"),
        Some("map") => Some("application/json"),
        _ => None,
    };
    serve_under(&state.asset_dir.join("dist"), &rel_path, mime)
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
