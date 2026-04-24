//! Dashboard-shell surface: `/`, `/fragment`, `/check-updates`,
//! `/search-history`, favicons, vendor + dist + asset static routes.
//!
//! This module owns the asset-serving helpers (`serve_embedded`,
//! `serve_under`, `serve_fixed`) because they are reached only from
//! the static routes here.

use std::collections::HashMap;

use axum::body::Body;
use axum::extract::{Query, State};
use axum::http::{header, HeaderMap, HeaderValue, StatusCode};
use axum::response::{IntoResponse, Response};
use condash_parser::{
    compute_fingerprint, compute_knowledge_node_fingerprints, compute_project_node_fingerprints,
    find_card, find_node,
};
use condash_render::git_render::render_git_repo_fragment;
use condash_render::{
    render_card_fragment, render_knowledge_card_fragment, render_knowledge_group_fragment,
    render_page,
};
use condash_state::{
    collect_git_repos, compute_git_node_fingerprints, git_fingerprint, search_items,
};
use serde::Deserialize;

use super::{error_json, html_response, json_response, live_runners_snapshot, AppState};

/// Build an ETag from the id + the workspace fingerprint + the git
/// fingerprint. Identical workspace state produces identical ETags, so a
/// client `If-None-Match` lets us short-circuit the render pass.
fn fragment_etag(id: &str, items_fp: &str, git_fp: &str) -> HeaderValue {
    use md5::{Digest, Md5};
    let mut h = Md5::new();
    h.update(id.as_bytes());
    h.update(b"\0");
    h.update(items_fp.as_bytes());
    h.update(b"\0");
    h.update(git_fp.as_bytes());
    let digest = h.finalize();
    let mut hex = String::with_capacity(34);
    hex.push('"');
    for b in digest {
        hex.push_str(&format!("{:02x}", b));
    }
    hex.push('"');
    HeaderValue::from_str(&hex).unwrap()
}

fn if_none_match_matches(headers: &HeaderMap, tag: &HeaderValue) -> bool {
    headers
        .get_all(header::IF_NONE_MATCH)
        .iter()
        .any(|v| v == tag)
}

fn not_modified(tag: HeaderValue) -> Response {
    let mut resp = Response::builder()
        .status(StatusCode::NOT_MODIFIED)
        .body(Body::empty())
        .unwrap();
    resp.headers_mut().insert(header::ETAG, tag);
    resp
}

fn with_etag(mut resp: Response, tag: HeaderValue) -> Response {
    resp.headers_mut().insert(header::ETAG, tag);
    resp
}

pub(super) async fn index(State(state): State<AppState>) -> impl IntoResponse {
    let items = state.cache.get_items(&state.ctx);
    let knowledge = state.cache.get_knowledge(&state.ctx);
    let live_runners = live_runners_snapshot(&state);
    let html = render_page(
        &state.ctx,
        &items,
        knowledge.as_ref().as_ref(),
        &state.version,
        &live_runners,
    );
    html_response(html)
}

#[derive(Debug, Deserialize)]
pub(super) struct FragmentQuery {
    #[serde(default)]
    id: String,
}

pub(super) async fn fragment(
    State(state): State<AppState>,
    headers: HeaderMap,
    Query(q): Query<FragmentQuery>,
) -> impl IntoResponse {
    let id = q.id;
    if id.is_empty() {
        return error_json(StatusCode::BAD_REQUEST, "missing id");
    }

    // Compute the ETag once up front. It hashes the id together with the
    // workspace + git fingerprints, so unchanged state produces an
    // unchanged tag and the browser's `If-None-Match` short-circuits the
    // render pass.
    let items = state.cache.get_items(&state.ctx);
    let items_fp = compute_fingerprint(&items);
    let git_fp = git_fingerprint(&state.ctx);
    let etag = fragment_etag(&id, &items_fp, &git_fp);
    if if_none_match_matches(&headers, &etag) {
        return not_modified(etag);
    }

    if let Some(rest) = id.strip_prefix("projects/") {
        let parts: Vec<&str> = rest.splitn(2, '/').collect();
        if parts.len() != 2 {
            return error_json(StatusCode::NOT_FOUND, "not a card id");
        }
        let slug = parts[1];
        for item in items.iter() {
            if item.readme.slug == slug {
                return with_etag(html_response(render_card_fragment(item)), etag);
            }
        }
        return error_json(StatusCode::NOT_FOUND, "card not found");
    }

    if id == "knowledge" {
        return error_json(StatusCode::NOT_FOUND, "use global reload");
    }

    if let Some(rest) = id.strip_prefix("code/") {
        if !rest.contains('/') {
            return error_json(StatusCode::NOT_FOUND, "use global reload");
        }
        let groups = collect_git_repos(&state.ctx);
        let live_runners = live_runners_snapshot(&state);
        if let Some(html) = render_git_repo_fragment(&state.ctx, &groups, &id, &live_runners) {
            return with_etag(html_response(html), etag);
        }
        return error_json(StatusCode::NOT_FOUND, "repo not found");
    }

    if id.starts_with("knowledge/") {
        let tree = state.cache.get_knowledge(&state.ctx);
        let root = tree.as_ref().as_ref();
        if id.ends_with(".md") {
            if let Some(card) = find_card(root, &id) {
                return with_etag(html_response(render_knowledge_card_fragment(card)), etag);
            }
            return error_json(StatusCode::NOT_FOUND, "card not found");
        }
        if let Some(node) = find_node(root, &id) {
            return with_etag(html_response(render_knowledge_group_fragment(node)), etag);
        }
        return error_json(StatusCode::NOT_FOUND, "dir not found");
    }

    error_json(StatusCode::NOT_FOUND, "unsupported id")
}

pub(super) async fn check_updates(State(state): State<AppState>) -> impl IntoResponse {
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
pub(super) struct SearchQuery {
    #[serde(default)]
    q: String,
}

pub(super) async fn search_history(
    State(state): State<AppState>,
    Query(s): Query<SearchQuery>,
) -> impl IntoResponse {
    let items = state.cache.get_items(&state.ctx);
    let results = search_items(&state.ctx, &items, &s.q);
    json_response(&results)
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
    serve_under(&state.ctx.base_dir, &rel_path, None)
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
