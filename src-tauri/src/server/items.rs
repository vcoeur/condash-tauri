//! `POST /create-item` (and its `/api/items` alias) — scaffolds a new
//! project / incident / document under the conception tree.

use axum::extract::State;
use axum::http::StatusCode;
use axum::response::IntoResponse;
use axum::Json;
use chrono::Datelike;
use condash_mutations::{create_item, CreateItemResult, NewItemSpec};
use serde::Deserialize;

use super::{error_json, json_response, AppState};

#[derive(Debug, Deserialize)]
pub(super) struct CreateItemPayload {
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

pub(super) async fn post_create_item(
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
