//! `/rescan` — hard-refresh hook. Invalidates cached slices. The
//! `RenderCtx` itself still rebuilds only when the user actively edits
//! `configuration.yml` through the modal; this endpoint exists so the
//! top-bar refresh button forces a fresh filesystem walk through the
//! `WorkspaceCache` on the next request, picking up out-of-band edits
//! (git pull, external renames, direct YAML hand-edits after
//! close+reopen).

use axum::extract::State;
use axum::response::IntoResponse;

use super::{json_response, AppState};

pub(super) async fn post_rescan(State(state): State<AppState>) -> impl IntoResponse {
    state
        .cache
        .consume(condash_state::MutationOutput::full_flush());
    json_response(&serde_json::json!({"ok": true}))
}
