//! axum HTTP server — the dashboard's entire HTTP + WebSocket surface.
//!
//! The Tauri host owns the `RenderCtx` + `WorkspaceCache` and spawns
//! this server on a free localhost port at startup. The main webview
//! then navigates to `http://127.0.0.1:<port>/` so the dashboard's JS —
//! which speaks plain HTTP fetches — has a fixed origin regardless of
//! host.
//!
//! Structure: this `mod.rs` owns the shared application state, the
//! route wiring in [`build_router`], startup helpers, and a handful of
//! response-building utilities + cross-module helpers
//! ([`live_runners_snapshot`], [`validate_open_path`]). Every handler
//! lives in one of the sibling sub-modules, grouped by surface:
//!
//! - [`shell`]         — `/`, `/fragment`, `/fragment/history`,
//!                       `/check-updates`, favicons, static assets
//! - [`steps`]         — `/toggle`, `/add-step`, `/remove-step`,
//!                       `/edit-step`, `/set-priority`, `/reorder-all`
//! - [`notes`]         — `/note`, `/note-raw`, `/note/rename`,
//!                       `/note/create`, `/note/mkdir`, `/note/upload`
//! - [`items`]         — `/create-item`, `/api/items`
//! - [`events`]        — `GET /events` SSE stream
//! - [`terminal`]      — `GET /ws/term` embedded-terminal WebSocket
//! - [`runners`]       — `/api/runner/{start,stop,force-stop}`,
//!                       `GET /ws/runner/{key}`
//! - [`config_surface`] — `/configuration` r/w + legacy `/config`
//! - [`openers`]       — `/open`, `/open-folder`, `/open-external`,
//!                       `/open-doc`, `/recent-screenshot`
//! - [`rescan`]        — `/rescan`

use std::net::{SocketAddr, TcpListener};
use std::sync::Arc;

use anyhow::{Context, Result};
use axum::body::Body;
use axum::http::{header, HeaderValue, StatusCode};
use axum::response::Response;
use axum::routing::{get, post};
use axum::Router;
use condash_state::{RenderCtx, WorkspaceCache};
use tokio::net::TcpListener as TokioTcpListener;

mod config_surface;
mod events;
mod items;
mod notes;
mod openers;
mod rescan;
mod runners;
mod shell;
mod steps;
mod terminal;

/// Application state shared across every handler. Cheap to clone
/// (all fields live behind `Arc`).
#[derive(Clone)]
pub struct AppState {
    pub ctx: Arc<RenderCtx>,
    pub cache: Arc<WorkspaceCache>,
    /// Source of the dashboard shell (`dashboard.html`),
    /// `favicon.{svg,ico}`, `dist/`, and `vendor/`. Production
    /// binaries use [`crate::assets::AssetSource::Embedded`] so the
    /// binary is self-contained; dev runs can flip to
    /// [`crate::assets::AssetSource::Disk`] via the
    /// `CONDASH_ASSET_DIR` env var to reload bundles without a
    /// rebuild.
    pub assets: crate::assets::AssetSource,
    /// Version string stamped into the dashboard shell at
    /// `{{VERSION}}`.
    pub version: Arc<String>,
    /// Fan-out for filesystem-driven staleness events. Cloneable —
    /// each `/events` subscriber grabs its own `broadcast::Receiver`.
    pub event_bus: crate::events::EventBus,
    /// Per-process registry of live PTY sessions — the `/ws/term`
    /// WebSocket handler looks up sessions here.
    pub pty_registry: crate::pty::PtyRegistry,
    /// Per-process registry of inline dev-server runners — used by
    /// `/api/runner/{start,stop}` and `/ws/runner/:key`.
    pub runner_registry: crate::runner_registry::RunnerRegistry,
}

/// Start the axum server on the given localhost port (`0` means any
/// free port) and return the bound port so the caller can point the
/// Tauri webview at it. The server runs forever on the current tokio
/// runtime.
pub async fn start(state: AppState, port: u16) -> Result<u16> {
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

/// Middleware — log any non-2xx response at warn-level with method +
/// path + status. Written to stderr so it lands in the Tauri host's
/// stdout capture and in `condash-serve`'s console. Keeps silent 404s
/// from hiding unported routes; a future regression shows up as a
/// one-liner after the first click.
async fn log_non_2xx(
    req: axum::extract::Request,
    next: axum::middleware::Next,
) -> axum::response::Response {
    let method = req.method().clone();
    let path = req.uri().path().to_string();
    let response = next.run(req).await;
    let status = response.status();
    if status.is_client_error() || status.is_server_error() {
        eprintln!("[condash] {method} {path} -> {}", status.as_u16());
    }
    response
}

pub fn build_router(state: AppState) -> Router {
    Router::new()
        // Dashboard shell + asset surface.
        .route("/", get(shell::index))
        .route("/fragment", get(shell::fragment))
        .route("/check-updates", get(shell::check_updates))
        .route("/fragment/history", get(shell::fragment_history))
        .route("/fragment/knowledge", get(shell::fragment_knowledge))
        .route("/fragment/code", get(shell::fragment_code))
        .route("/fragment/projects", get(shell::fragment_projects))
        .route("/favicon.svg", get(shell::favicon_svg))
        .route("/favicon.ico", get(shell::favicon_ico))
        .route("/vendor/{*path}", get(shell::vendor_asset))
        .route("/assets/dist/{*path}", get(shell::dist_asset))
        .route("/asset/{*path}", get(shell::conception_asset))
        // Step mutations (operate on a single README checkbox line).
        .route("/toggle", post(steps::toggle))
        .route("/add-step", post(steps::add_step_route))
        .route("/remove-step", post(steps::remove_step_route))
        .route("/edit-step", post(steps::edit_step_route))
        .route("/set-priority", post(steps::set_priority_route))
        .route("/reorder-all", post(steps::reorder_all_route))
        // SSE staleness channel.
        .route("/events", get(events::events_stream))
        // Embedded terminal WebSocket.
        .route("/ws/term", get(terminal::term_ws))
        // Inline dev-server runners.
        .route("/api/runner/start", post(runners::runner_start_route))
        .route("/api/runner/stop", post(runners::runner_stop_route))
        .route(
            "/api/runner/force-stop",
            post(runners::runner_force_stop_route),
        )
        .route("/ws/runner/{key}", get(runners::runner_ws))
        // File-level mutations.
        .route("/note", get(notes::get_note).post(notes::post_note))
        .route("/note-raw", get(notes::get_note_raw))
        .route("/note/rename", post(notes::post_note_rename))
        .route("/note/create", post(notes::post_note_create))
        .route("/note/mkdir", post(notes::post_note_mkdir))
        .route("/note/upload", post(notes::post_note_upload))
        .route("/create-item", post(items::post_create_item))
        // `/api/items` is the legacy path the bundled frontend still
        // calls for the New Item modal. Kept as an alias so the modal
        // works without a frontend rebuild; semantically identical.
        .route("/api/items", post(items::post_create_item))
        // Configuration modal — plain-text YAML editor of
        // <conception>/configuration.yml.
        .route(
            "/configuration",
            get(config_surface::get_configuration).post(config_surface::post_configuration),
        )
        // Legacy config summary — used by the frontend for setup-banner
        // detection and terminal shortcut loading. Returns a small
        // JSON dict with `conception_path` + `terminal` fields only.
        .route("/config", get(config_surface::get_config_summary))
        // Open-path surface — these four dispatch the user-visible
        // "Open with", "Open folder", "Open external", "Open doc"
        // actions into detached external processes.
        .route("/open", post(openers::post_open))
        .route("/open-folder", post(openers::post_open_folder))
        .route("/open-external", post(openers::post_open_external))
        .route("/open-doc", post(openers::post_open_doc))
        .route("/recent-screenshot", get(openers::get_recent_screenshot))
        // Hard-refresh hook — rebuild RenderCtx from disk + invalidate
        // cached slices. `refreshAll` in the frontend hits this before
        // `location.reload()`.
        .route("/rescan", post(rescan::post_rescan))
        .layer(axum::middleware::from_fn(log_non_2xx))
        .with_state(state)
}

// ---------------------------------------------------------------------
// Cross-module helpers. Kept here rather than a separate `util.rs` so
// the sub-modules only ever reach up to `super`.
// ---------------------------------------------------------------------

/// JSON body with the 200 status code.
pub(super) fn json_response<T: serde::Serialize>(body: &T) -> Response {
    json_with_status(body, StatusCode::OK)
}

/// JSON body with an explicit status code.
pub(super) fn json_with_status<T: serde::Serialize>(body: &T, code: StatusCode) -> Response {
    let bytes = match serde_json::to_vec(body) {
        Ok(b) => b,
        Err(e) => return error_json(StatusCode::INTERNAL_SERVER_ERROR, &format!("json: {e}")),
    };
    Response::builder()
        .status(code)
        .header(header::CONTENT_TYPE, "application/json")
        .body(Body::from(bytes))
        .unwrap()
}

/// JSON error response — a `{"error": <msg>}` body plus the given
/// status code. Every failure path in this module funnels through here
/// so the frontend parses one shape.
pub(super) fn error_json(code: StatusCode, msg: &str) -> Response {
    let body = serde_json::json!({"error": msg});
    let bytes = serde_json::to_vec(&body).unwrap_or_default();
    Response::builder()
        .status(code)
        .header(header::CONTENT_TYPE, "application/json")
        .body(Body::from(bytes))
        .unwrap()
}

/// Response whose body is an HTML fragment — used by the dashboard
/// shell and the `/fragment` endpoint.
pub(super) fn html_response(body: String) -> Response {
    let mut r = Response::new(Body::from(body));
    r.headers_mut().insert(
        header::CONTENT_TYPE,
        HeaderValue::from_static("text/html; charset=utf-8"),
    );
    r
}

/// Build the renderer's `LiveRunners` map from the current runner
/// registry. One entry per session (live or exited); the renderer
/// decides whether to paint the mount as running or "exited: N".
///
/// Shared between [`shell::index`] (top-level render) and
/// [`shell::fragment`] (per-card refresh).
pub(super) fn live_runners_snapshot(state: &AppState) -> condash_render::git_render::LiveRunners {
    state
        .runner_registry
        .snapshot()
        .into_iter()
        .map(|session| {
            (
                session.key.clone(),
                condash_render::git_render::RunnerLive {
                    checkout_key: session.checkout_key.clone(),
                    exit_code: session.exit_code_now(),
                },
            )
        })
        .collect()
}

/// Validate a filesystem path as an in-sandbox directory under
/// `ctx.workspace` or `ctx.worktrees`. Used by the opener + runner
/// routes so the shell-command-dispatching helpers only see paths the
/// user legitimately asked condash to manage.
pub(super) fn validate_open_path(
    ctx: &condash_state::RenderCtx,
    path: &str,
) -> Option<std::path::PathBuf> {
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
