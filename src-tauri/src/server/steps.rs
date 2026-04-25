//! Step-mutation handlers. Each handler validates the README path with
//! `paths::validate_readme_path`, delegates to the matching helper in
//! `condash-mutations`, and — on success — flushes the items cache so
//! the next `/check-updates` sees a fresh fingerprint.

use axum::extract::State;
use axum::http::StatusCode;
use axum::response::IntoResponse;
use axum::Json;
use condash_mutations::{
    add_step, edit_step, remove_step, reorder_all, set_priority, toggle_checkbox,
};
use serde::Deserialize;

use super::{error_json, json_response, AppState};

#[derive(Debug, Deserialize)]
pub(super) struct TogglePayload {
    file: String,
    line: i64,
}

pub(super) async fn toggle(
    State(state): State<AppState>,
    Json(p): Json<TogglePayload>,
) -> impl IntoResponse {
    let Some(full) = crate::paths::validate_readme_path(&state.ctx().base_dir, &p.file) else {
        return error_json(StatusCode::BAD_REQUEST, "invalid path");
    };
    if p.line < 0 {
        return error_json(StatusCode::BAD_REQUEST, "not a checkbox line");
    }
    match toggle_checkbox(&full, p.line as usize) {
        Ok(Some(status)) => {
            state.cache.consume(condash_state::MutationOutput::for_path(full.as_path().to_path_buf()));
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
pub(super) struct AddStepPayload {
    file: String,
    text: Option<String>,
    #[serde(default)]
    section: Option<String>,
}

pub(super) async fn add_step_route(
    State(state): State<AppState>,
    Json(p): Json<AddStepPayload>,
) -> impl IntoResponse {
    let text = p.text.unwrap_or_default();
    let text = text.trim();
    if text.is_empty() {
        return error_json(StatusCode::BAD_REQUEST, "empty text");
    }
    let Some(full) = crate::paths::validate_readme_path(&state.ctx().base_dir, &p.file) else {
        return error_json(StatusCode::BAD_REQUEST, "invalid path");
    };
    let section = p.section.as_deref();
    match add_step(&full, text, section) {
        Ok(line) => {
            state.cache.consume(condash_state::MutationOutput::for_path(full.as_path().to_path_buf()));
            json_response(&serde_json::json!({"ok": true, "line": line}))
        }
        Err(e) => error_json(StatusCode::INTERNAL_SERVER_ERROR, &format!("add-step: {e}")),
    }
}

#[derive(Debug, Deserialize)]
pub(super) struct RemoveStepPayload {
    file: String,
    line: i64,
}

pub(super) async fn remove_step_route(
    State(state): State<AppState>,
    Json(p): Json<RemoveStepPayload>,
) -> impl IntoResponse {
    let Some(full) = crate::paths::validate_readme_path(&state.ctx().base_dir, &p.file) else {
        return error_json(StatusCode::BAD_REQUEST, "invalid path");
    };
    if p.line < 0 {
        return error_json(StatusCode::BAD_REQUEST, "cannot remove");
    }
    match remove_step(&full, p.line as usize) {
        Ok(true) => {
            state.cache.consume(condash_state::MutationOutput::for_path(full.as_path().to_path_buf()));
            json_response(&serde_json::json!({"ok": true}))
        }
        Ok(false) => error_json(StatusCode::BAD_REQUEST, "cannot remove"),
        Err(e) => error_json(StatusCode::INTERNAL_SERVER_ERROR, &format!("remove: {e}")),
    }
}

#[derive(Debug, Deserialize)]
pub(super) struct EditStepPayload {
    file: String,
    line: i64,
    text: Option<String>,
}

pub(super) async fn edit_step_route(
    State(state): State<AppState>,
    Json(p): Json<EditStepPayload>,
) -> impl IntoResponse {
    let text = p.text.unwrap_or_default();
    let text = text.trim();
    if text.is_empty() {
        return error_json(StatusCode::BAD_REQUEST, "empty text");
    }
    let Some(full) = crate::paths::validate_readme_path(&state.ctx().base_dir, &p.file) else {
        return error_json(StatusCode::BAD_REQUEST, "invalid path");
    };
    if p.line < 0 {
        return error_json(StatusCode::BAD_REQUEST, "cannot edit");
    }
    match edit_step(&full, p.line as usize, text) {
        Ok(true) => {
            state.cache.consume(condash_state::MutationOutput::for_path(full.as_path().to_path_buf()));
            json_response(&serde_json::json!({"ok": true}))
        }
        Ok(false) => error_json(StatusCode::BAD_REQUEST, "cannot edit"),
        Err(e) => error_json(StatusCode::INTERNAL_SERVER_ERROR, &format!("edit: {e}")),
    }
}

#[derive(Debug, Deserialize)]
pub(super) struct SetPriorityPayload {
    file: String,
    priority: String,
}

pub(super) async fn set_priority_route(
    State(state): State<AppState>,
    Json(p): Json<SetPriorityPayload>,
) -> impl IntoResponse {
    let Some(full) = crate::paths::validate_readme_path(&state.ctx().base_dir, &p.file) else {
        return error_json(StatusCode::BAD_REQUEST, "invalid path");
    };
    match set_priority(&full, &p.priority) {
        Ok(true) => {
            state.cache.consume(condash_state::MutationOutput::for_path(full.as_path().to_path_buf()));
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
pub(super) struct ReorderAllPayload {
    file: String,
    order: Vec<i64>,
}

pub(super) async fn reorder_all_route(
    State(state): State<AppState>,
    Json(p): Json<ReorderAllPayload>,
) -> impl IntoResponse {
    let Some(full) = crate::paths::validate_readme_path(&state.ctx().base_dir, &p.file) else {
        return error_json(StatusCode::BAD_REQUEST, "invalid path");
    };
    if p.order.iter().any(|&n| n < 0) {
        return error_json(StatusCode::BAD_REQUEST, "cannot reorder");
    }
    let order: Vec<usize> = p.order.iter().map(|&n| n as usize).collect();
    match reorder_all(&full, &order) {
        Ok(true) => {
            state.cache.consume(condash_state::MutationOutput::for_path(full.as_path().to_path_buf()));
            json_response(&serde_json::json!({"ok": true}))
        }
        Ok(false) => error_json(StatusCode::BAD_REQUEST, "cannot reorder"),
        Err(e) => error_json(StatusCode::INTERNAL_SERVER_ERROR, &format!("reorder: {e}")),
    }
}
