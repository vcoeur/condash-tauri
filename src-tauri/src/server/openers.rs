//! External-opener routes — `POST /open`, `/open-folder`,
//! `/open-external`, `/open-doc` — and `GET /recent-screenshot`.
//!
//! Each one validates the incoming path (URL for `/open-external`) and
//! dispatches to the [`crate::launcher`] module, which spawns a
//! detached `sh -c "<template with {path} filled in>"` and walks the
//! configured fallback chain. Returns 200 on first success, 502 when
//! the entire chain falls through, 400/403 on validation failures.

use axum::extract::State;
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::Json;
use serde::Deserialize;

use super::{error_json, json_response, validate_open_path, AppState};

#[derive(Debug, Deserialize)]
pub(super) struct OpenPayload {
    #[serde(default)]
    path: String,
    #[serde(default)]
    tool: String,
}

pub(super) async fn post_open(
    State(state): State<AppState>,
    Json(p): Json<OpenPayload>,
) -> impl IntoResponse {
    if p.path.trim().is_empty() || p.tool.trim().is_empty() {
        return error_json(StatusCode::BAD_REQUEST, "path and tool required");
    }
    let ctx = state.ctx();
    let Some(validated) = validate_open_path(&ctx, &p.path) else {
        return error_json(StatusCode::FORBIDDEN, "path out of sandbox");
    };
    let Some(slot) = ctx.open_with.get(&p.tool) else {
        return error_json(StatusCode::NOT_FOUND, &format!("unknown tool: {}", p.tool));
    };
    if slot.commands.is_empty() {
        return error_json(
            StatusCode::FAILED_DEPENDENCY,
            &format!("no commands configured for {}", p.tool),
        );
    }
    let value = validated.as_path().to_string_lossy().into_owned();
    let commands = slot.commands.clone();
    drop(ctx);
    match crate::launcher::try_chain(&commands, "path", &value) {
        Some(used) => json_response(&serde_json::json!({"ok": true, "command": used})),
        None => error_json(StatusCode::BAD_GATEWAY, "all commands failed"),
    }
}

#[derive(Debug, Deserialize)]
pub(super) struct PathOnlyPayload {
    #[serde(default)]
    path: String,
}

pub(super) async fn post_open_folder(
    State(state): State<AppState>,
    Json(p): Json<PathOnlyPayload>,
) -> impl IntoResponse {
    if p.path.trim().is_empty() {
        return error_json(StatusCode::BAD_REQUEST, "path required");
    }
    // Item folders live inside the conception tree (base_dir), not the
    // workspace/worktrees sandbox — the card-button passes a path like
    // `projects/2026-04/2026-04-23-slug/` relative to base_dir. The
    // Knowledge tab's per-folder affordance hands in `knowledge/...`
    // paths under the same root. Try both, then fall back to the
    // workspace sandbox for any other folder target a future caller
    // might feed in.
    let validated = crate::paths::validate_item_dir(&state.ctx().base_dir, &p.path)
        .or_else(|| crate::paths::validate_knowledge_dir(&state.ctx().base_dir, &p.path))
        .or_else(|| validate_open_path(&state.ctx(), &p.path));
    let Some(validated) = validated else {
        return error_json(StatusCode::FORBIDDEN, "path out of sandbox");
    };
    let value = validated.as_path().to_string_lossy().into_owned();
    match crate::launcher::try_chain_static(crate::launcher::FOLDER_FALLBACKS, "path", &value) {
        Some(used) => json_response(&serde_json::json!({"ok": true, "command": used})),
        None => error_json(StatusCode::BAD_GATEWAY, "no folder opener succeeded"),
    }
}

#[derive(Debug, Deserialize)]
pub(super) struct ExternalPayload {
    #[serde(default)]
    url: String,
}

pub(super) async fn post_open_external(Json(p): Json<ExternalPayload>) -> impl IntoResponse {
    let url = p.url.trim();
    if url.is_empty() {
        return error_json(StatusCode::BAD_REQUEST, "url required");
    }
    // Only hand verified URL schemes to `xdg-open` — never bare paths
    // or `javascript:` / `data:` tricks the webview might let through.
    let allowed = url.starts_with("http://")
        || url.starts_with("https://")
        || url.starts_with("mailto:")
        || url.starts_with("file://");
    if !allowed {
        return error_json(StatusCode::BAD_REQUEST, "unsupported url scheme");
    }
    match crate::launcher::try_chain_static(crate::launcher::URL_FALLBACKS, "url", url) {
        Some(used) => json_response(&serde_json::json!({"ok": true, "command": used})),
        None => error_json(StatusCode::BAD_GATEWAY, "no url opener succeeded"),
    }
}

pub(super) async fn post_open_doc(
    State(state): State<AppState>,
    Json(p): Json<PathOnlyPayload>,
) -> impl IntoResponse {
    if p.path.trim().is_empty() {
        return error_json(StatusCode::BAD_REQUEST, "path required");
    }
    // /open-doc may land on an absolute path (from a note link) or a
    // conception-tree-relative path (from a card button). Try to
    // resolve it either way inside the sandbox. The note-link path is
    // already sandbox-safe (the note path itself was validated to open
    // the modal), so we first try the raw value and fall back to
    // base_dir-rooted resolution.
    let full = match validate_open_path(&state.ctx(), &p.path) {
        Some(v) => v,
        None => {
            let rel = state.ctx().base_dir.join(&p.path);
            match std::fs::canonicalize(&rel).ok().and_then(|c| {
                let base = std::fs::canonicalize(&state.ctx().base_dir).ok()?;
                if c.starts_with(&base) {
                    Some(crate::paths::ValidatedPath::from_canonical_in_sandbox(c))
                } else {
                    None
                }
            }) {
                Some(v) => v,
                None => return error_json(StatusCode::FORBIDDEN, "path out of sandbox"),
            }
        }
    };
    let value = full.as_path().to_string_lossy().into_owned();
    // Prefer the user's configured pdf_viewer chain; fall back to the
    // xdg-open / gio open chain.
    let chain: Vec<String> = if state.ctx().pdf_viewer.is_empty() {
        crate::launcher::DOC_FALLBACKS
            .iter()
            .map(|s| s.to_string())
            .collect()
    } else {
        state.ctx().pdf_viewer.clone()
    };
    match crate::launcher::try_chain(&chain, "path", &value) {
        Some(used) => json_response(&serde_json::json!({"ok": true, "command": used})),
        None => error_json(StatusCode::BAD_GATEWAY, "no doc opener succeeded"),
    }
}

// ---------------------------------------------------------------------
// `/recent-screenshot` — data source for the Ctrl+Shift+V
// screenshot-paste shortcut. Returns the absolute path of the newest
// image in the configured `terminal.screenshot_dir` (falls back to an
// XDG-aware default). Response shape:
//   `{path: <abs>, dir: <abs>}` on success, or
//   `{path: null, dir: <abs>, reason: <message>}` when the directory
//   is missing, unreadable, or empty.
// ---------------------------------------------------------------------

const SCREENSHOT_IMAGE_EXTENSIONS: &[&str] = &["png", "jpg", "jpeg", "webp"];

/// Best-guess default location for OS screenshots. Honours
/// `$XDG_PICTURES_DIR` (standard XDG user-dirs key); otherwise falls
/// back to `~/Pictures/Screenshots` on Linux and `~/Desktop` on macOS.
fn default_screenshot_dir() -> std::path::PathBuf {
    if let Ok(xdg) = std::env::var("XDG_PICTURES_DIR") {
        if !xdg.is_empty() {
            return std::path::PathBuf::from(xdg).join("Screenshots");
        }
    }
    let home = std::env::var("HOME").unwrap_or_default();
    let base = std::path::PathBuf::from(&home);
    if cfg!(target_os = "macos") {
        base.join("Desktop")
    } else {
        base.join("Pictures").join("Screenshots")
    }
}

fn resolved_screenshot_dir(ctx: &condash_state::RenderCtx) -> std::path::PathBuf {
    match ctx.terminal.screenshot_dir.as_deref() {
        Some(s) if !s.is_empty() => {
            // Expand a leading `~/` against $HOME; anything else is passed through.
            if let Some(rest) = s.strip_prefix("~/") {
                let home = std::env::var("HOME").unwrap_or_default();
                std::path::PathBuf::from(home).join(rest)
            } else {
                std::path::PathBuf::from(s)
            }
        }
        _ => default_screenshot_dir(),
    }
}

pub(super) async fn get_recent_screenshot(State(state): State<AppState>) -> Response {
    let dir = resolved_screenshot_dir(&state.ctx());
    let dir_str = dir.to_string_lossy().into_owned();
    let payload_err = |reason: &str| {
        json_response(&serde_json::json!({
            "path": serde_json::Value::Null,
            "dir": dir_str,
            "reason": reason,
        }))
    };
    if !dir.exists() {
        return payload_err("directory does not exist");
    }
    if !dir.is_dir() {
        return payload_err("configured path is not a directory");
    }
    let entries = match std::fs::read_dir(&dir) {
        Ok(iter) => iter,
        Err(e) if e.kind() == std::io::ErrorKind::PermissionDenied => {
            return payload_err("permission denied");
        }
        Err(e) => return payload_err(&format!("read error: {e}")),
    };
    let mut newest: Option<(std::time::SystemTime, std::path::PathBuf)> = None;
    for entry in entries.flatten() {
        let path = entry.path();
        let ext_ok = path
            .extension()
            .and_then(|e| e.to_str())
            .map(|e| SCREENSHOT_IMAGE_EXTENSIONS.contains(&e.to_ascii_lowercase().as_str()))
            .unwrap_or(false);
        if !ext_ok {
            continue;
        }
        let Ok(meta) = entry.metadata() else { continue };
        if !meta.is_file() {
            continue;
        }
        let Ok(mtime) = meta.modified() else { continue };
        if newest.as_ref().is_none_or(|(prev, _)| mtime > *prev) {
            newest = Some((mtime, path));
        }
    }
    match newest {
        Some((_, path)) => json_response(&serde_json::json!({
            "path": path.to_string_lossy(),
            "dir": dir_str,
            "reason": "",
        })),
        None => payload_err("no image files found"),
    }
}
