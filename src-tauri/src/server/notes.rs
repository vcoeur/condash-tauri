//! File-level mutation handlers — note read/write, rename, create,
//! mkdir, multipart upload. Each handler resolves its input through
//! `paths::validate_*_path` before touching disk.

use axum::extract::{Query, State};
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::Json;
use condash_mutations::{
    create_note, create_notes_subdir, rename_note, store_uploads, write_note, CreateNoteResult,
    CreateSubdirResult, RenameResult, WriteNoteResult,
};
use serde::Deserialize;

use super::{error_json, html_response, json_response, json_with_status, AppState};

#[derive(Debug, Deserialize)]
pub(super) struct NotePathQuery {
    #[serde(default)]
    path: String,
}

/// `GET /note?path=…` — rendered HTML for the modal view pane.
/// Dispatches on `note_kind` and returns preformatted text, `<img>`,
/// a PDF host placeholder the frontend mounts PDF.js into, or the
/// markdown render.
pub(super) async fn get_note(
    State(state): State<AppState>,
    Query(q): Query<NotePathQuery>,
) -> impl IntoResponse {
    if q.path.is_empty() {
        return error_json(StatusCode::BAD_REQUEST, "missing path");
    }
    let Some(full) = crate::paths::validate_note_path(&state.ctx().base_dir, &q.path) else {
        return error_json(StatusCode::FORBIDDEN, "invalid path");
    };
    let html = condash_render::render_note(&q.path, &full, &state.ctx().base_dir);
    html_response(html)
}

/// `GET /note-raw?path=…` — JSON `{content, kind, mtime}` for the edit
/// pane. Binary kinds (pdf/image) return 415 so the frontend silently
/// leaves the edit modes disabled (it catches the non-ok response).
pub(super) async fn get_note_raw(
    State(state): State<AppState>,
    Query(q): Query<NotePathQuery>,
) -> impl IntoResponse {
    if q.path.is_empty() {
        return error_json(StatusCode::BAD_REQUEST, "missing path");
    }
    let Some(full) = crate::paths::validate_note_path(&state.ctx().base_dir, &q.path) else {
        return error_json(StatusCode::FORBIDDEN, "invalid path");
    };
    match condash_render::note_raw_payload(&full) {
        Some(body) => json_response(&body),
        None => error_json(StatusCode::UNSUPPORTED_MEDIA_TYPE, "not editable"),
    }
}

#[derive(Debug, Deserialize)]
pub(super) struct NoteWritePayload {
    path: String,
    content: String,
    #[serde(default)]
    expected_mtime: Option<f64>,
}

pub(super) async fn post_note(
    State(state): State<AppState>,
    Json(p): Json<NoteWritePayload>,
) -> impl IntoResponse {
    let Some(full) = crate::paths::validate_note_path(&state.ctx().base_dir, &p.path) else {
        return error_json(StatusCode::FORBIDDEN, "invalid path");
    };
    let kind = condash_parser::note_kind(&full);
    if kind != "md" && kind != "text" {
        return error_json(StatusCode::BAD_REQUEST, "not editable");
    }
    match write_note(&full, &p.content, p.expected_mtime) {
        Ok(WriteNoteResult::Ok { mtime, .. }) => {
            state.cache.consume(condash_state::MutationOutput::for_path(
                full.as_path().to_path_buf(),
            ));
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
pub(super) struct NoteRenamePayload {
    path: String,
    new_stem: String,
}

pub(super) async fn post_note_rename(
    State(state): State<AppState>,
    Json(p): Json<NoteRenamePayload>,
) -> impl IntoResponse {
    let Some(full) = crate::paths::validate_note_path(&state.ctx().base_dir, &p.path) else {
        return error_json(StatusCode::BAD_REQUEST, "invalid path");
    };
    if !crate::paths::VALID_ITEM_NOTES_FILE_RE.is_match(&p.path) {
        return error_json(
            StatusCode::BAD_REQUEST,
            "only files under <item>/notes/ can be renamed",
        );
    }
    match rename_note(&full, &p.new_stem, &state.ctx().base_dir) {
        Ok(RenameResult::Ok { path, mtime, .. }) => {
            state.cache.consume(condash_state::MutationOutput::for_path(
                full.as_path().to_path_buf(),
            ));
            json_response(&serde_json::json!({"ok": true, "path": path, "mtime": mtime}))
        }
        Ok(RenameResult::Err { reason, .. }) => error_json(StatusCode::BAD_REQUEST, &reason),
        Err(e) => error_json(StatusCode::INTERNAL_SERVER_ERROR, &format!("rename: {e}")),
    }
}

#[derive(Debug, Deserialize)]
pub(super) struct NoteCreatePayload {
    item_readme: String,
    filename: String,
    #[serde(default)]
    subdir: String,
}

pub(super) async fn post_note_create(
    State(state): State<AppState>,
    Json(p): Json<NoteCreatePayload>,
) -> impl IntoResponse {
    let Some(readme) = crate::paths::validate_readme_path(&state.ctx().base_dir, &p.item_readme)
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
        &state.ctx().base_dir,
        subdir_was_supplied,
    ) {
        Ok(CreateNoteResult::Ok { path, mtime, .. }) => {
            state.cache.consume(condash_state::MutationOutput::for_path(
                readme.as_path().to_path_buf(),
            ));
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
pub(super) struct NoteMkdirPayload {
    item_readme: String,
    subpath: String,
}

pub(super) async fn post_note_mkdir(
    State(state): State<AppState>,
    Json(p): Json<NoteMkdirPayload>,
) -> impl IntoResponse {
    let Some(readme) = crate::paths::validate_readme_path(&state.ctx().base_dir, &p.item_readme)
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
            state.cache.consume(condash_state::MutationOutput::for_path(
                readme.as_path().to_path_buf(),
            ));
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

/// 50 MB per-file cap on multipart uploads.
const UPLOAD_MAX_BYTES: u64 = 50 * 1024 * 1024;

pub(super) async fn post_note_upload(
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
            other => {
                tracing::warn!(name = %other, "multipart upload: dropping unknown field");
                let _ = field.bytes().await;
            }
        }
    }

    if uploads.is_empty() {
        return error_json(StatusCode::BAD_REQUEST, "no files in upload");
    }

    let Some(readme) = crate::paths::validate_readme_path(&state.ctx().base_dir, &item_readme)
    else {
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
        &state.ctx().base_dir,
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
            state.cache.consume(condash_state::MutationOutput::for_path(
                readme.as_path().to_path_buf(),
            ));
            json_response(&serde_json::json!({
                "ok": true,
                "stored": res.stored,
                "rejected": res.rejected,
            }))
        }
        Err(e) => error_json(StatusCode::INTERNAL_SERVER_ERROR, &format!("upload: {e}")),
    }
}
