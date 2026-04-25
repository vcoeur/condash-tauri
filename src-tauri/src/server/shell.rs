//! Dashboard-shell surface: `/`, `/fragment/{history,knowledge,code,projects}`,
//! favicons, vendor + dist + asset static routes.
//!
//! This module owns the asset-serving helpers (`serve_embedded`,
//! `serve_under`, `serve_fixed`) because they are reached only from
//! the static routes here.

use axum::body::Body;
use axum::extract::{Query, State};
use axum::http::{header, HeaderValue, StatusCode};
use axum::response::{IntoResponse, Response};
use condash_render::{
    render_cards_pane, render_code_pane, render_history_pane, render_knowledge_pane, render_page,
};
use serde::Deserialize;

use super::{error_json, html_response, live_runners_snapshot, AppState};

pub(super) async fn index(State(state): State<AppState>) -> impl IntoResponse {
    let items = state.cache.get_items(&state.ctx());
    let knowledge = state.cache.get_knowledge(&state.ctx());
    let live_runners = live_runners_snapshot(&state);
    let html = render_page(
        &state.ctx(),
        &items,
        knowledge.as_ref().as_ref(),
        &state.version,
        &live_runners,
    );
    html_response(html)
}

#[derive(Debug, Deserialize)]
pub(super) struct HistoryFragmentQuery {
    #[serde(default)]
    q: String,
}

/// HTML fragment for the History pane content. Empty `q` returns the
/// month-grouped tree; non-empty `q` returns the search-results list.
/// Driven by the htmx attributes on `#history-content` in
/// `dashboard.html` — replaces the legacy JSON-returning
/// `/search-history` + client-side renderer.
pub(super) async fn fragment_history(
    State(state): State<AppState>,
    Query(s): Query<HistoryFragmentQuery>,
) -> impl IntoResponse {
    let items = state.cache.get_items(&state.ctx());
    html_response(render_history_pane(&state.ctx(), &items, &s.q))
}

/// HTML fragment for the Knowledge pane content. Driven by the htmx
/// attributes on `#knowledge` in `dashboard.html`; refreshed on
/// `sse:knowledge` whenever the file watcher reports a change under
/// `knowledge/`.
pub(super) async fn fragment_knowledge(State(state): State<AppState>) -> impl IntoResponse {
    let knowledge = state.cache.get_knowledge(&state.ctx());
    html_response(render_knowledge_pane(knowledge.as_ref().as_ref()))
}

/// HTML fragment for the Code pane content (the git strip). Refreshed
/// on `sse:code`. The runner-viewer mounts inside carry
/// `hx-preserve="true"` so xterm + WebSocket-attached terminals
/// survive a parent-pane morph swap.
pub(super) async fn fragment_code(State(state): State<AppState>) -> impl IntoResponse {
    let live_runners = live_runners_snapshot(&state);
    html_response(render_code_pane(&state.ctx(), &live_runners))
}

/// HTML fragment for the Projects pane content (the cards grid).
/// Refreshed on `sse:projects`. Card identity is preserved by morph
/// swap (each card has a stable `id`), and the `htmx:beforeSwap` hook
/// in `htmx-state-preserve.js` re-applies user-driven state (expanded
/// cards, open `<details>`) onto the swapped DOM.
pub(super) async fn fragment_projects(State(state): State<AppState>) -> impl IntoResponse {
    let items = state.cache.get_items(&state.ctx());
    html_response(render_cards_pane(&items))
}

pub(super) async fn favicon_svg(State(state): State<AppState>) -> impl IntoResponse {
    serve_embedded(&state.assets, "favicon.svg")
}

pub(super) async fn favicon_ico(State(state): State<AppState>) -> impl IntoResponse {
    // Serve the SVG for .ico too — the Tauri webview accepts it as a
    // window icon without complaint.
    serve_embedded(&state.assets, "favicon.svg")
}

pub(super) async fn vendor_asset(
    State(state): State<AppState>,
    axum::extract::Path(rel_path): axum::extract::Path<String>,
) -> impl IntoResponse {
    serve_embedded(&state.assets, &format!("vendor/{rel_path}"))
}

pub(super) async fn dist_asset(
    State(state): State<AppState>,
    axum::extract::Path(rel_path): axum::extract::Path<String>,
) -> impl IntoResponse {
    serve_embedded(&state.assets, &format!("dist/{rel_path}"))
}

/// Serve a file from the [`crate::assets::AssetSource`] — embedded or
/// on-disk. Used by the favicons, vendor, and dist routes.
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
        None => error_json(StatusCode::NOT_FOUND, "no such asset"),
    }
}

pub(super) async fn conception_asset(
    State(state): State<AppState>,
    axum::extract::Path(rel_path): axum::extract::Path<String>,
) -> impl IntoResponse {
    serve_under(&state.ctx().base_dir, &rel_path, None)
}

fn serve_under(base: &std::path::Path, rel: &str, mime_override: Option<&str>) -> Response {
    if rel.is_empty() || rel.contains('\0') {
        return error_json(StatusCode::FORBIDDEN, "bad path");
    }
    for part in rel.split('/') {
        if part.is_empty() || part == ".." {
            return error_json(StatusCode::FORBIDDEN, "path traversal");
        }
    }
    let full = base.join(rel);
    let canonical = match std::fs::canonicalize(&full) {
        Ok(c) => c,
        Err(_) => return error_json(StatusCode::NOT_FOUND, "no such file"),
    };
    let base_canonical = match std::fs::canonicalize(base) {
        Ok(c) => c,
        Err(_) => return error_json(StatusCode::NOT_FOUND, "base missing"),
    };
    if !canonical.starts_with(&base_canonical) {
        return error_json(StatusCode::FORBIDDEN, "outside base");
    }
    if !canonical.is_file() {
        return error_json(StatusCode::NOT_FOUND, "not a file");
    }
    let guessed;
    let mime = match mime_override {
        Some(m) => m,
        None => {
            guessed = mime_guess::from_path(&canonical)
                .first_or_octet_stream()
                .to_string();
            guessed.as_str()
        }
    };
    serve_fixed(&canonical, mime)
}

fn serve_fixed(path: &std::path::Path, mime: &str) -> Response {
    match std::fs::read(path) {
        Ok(bytes) => Response::builder()
            .status(StatusCode::OK)
            .header(header::CONTENT_TYPE, mime)
            .header(header::CACHE_CONTROL, "public, max-age=86400")
            .body(Body::from(bytes))
            .unwrap(),
        Err(_) => error_json(StatusCode::NOT_FOUND, "read failed"),
    }
}
