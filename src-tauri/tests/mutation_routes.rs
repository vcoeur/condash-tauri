//! Integration tests for the Phase 3 slice 2 mutation routes.
//!
//! Each test builds a temp conception tree with one seeded README, hands
//! the axum router a JSON POST, and asserts on the HTTP status + JSON
//! body + on-disk file bytes.

use std::path::{Path, PathBuf};
use std::sync::Arc;

use axum::body::{to_bytes, Body};
use axum::http::{Method, Request, StatusCode};
use condash_lib::server::{build_router, AppState};
use condash_state::{RenderCtx, WorkspaceCache};
use serde_json::{json, Value};
use tempfile::TempDir;
use tower::ServiceExt;

struct Harness {
    _tmp: TempDir,
    state: AppState,
    readme: PathBuf,
    rel_path: String,
}

fn harness_with(initial: &str) -> Harness {
    let tmp = TempDir::new().expect("tempdir");
    let rel = "projects/2026-04/2026-04-22-demo/README.md";
    let item_dir = tmp.path().join("projects/2026-04/2026-04-22-demo");
    std::fs::create_dir_all(&item_dir).expect("item dir");
    let readme = item_dir.join("README.md");
    std::fs::write(&readme, initial).expect("seed");

    let ctx = Arc::new(RenderCtx::with_base_dir(tmp.path()));
    let cache = Arc::new(WorkspaceCache::new());
    let state = AppState {
        ctx,
        cache,
        assets: condash_lib::assets::AssetSource::Embedded,
        version: Arc::new("test".into()),
        event_bus: condash_lib::events::EventBus::default(),
        pty_registry: condash_lib::pty::PtyRegistry::new(),
        runner_registry: condash_lib::runners::RunnerRegistry::new(),
    };

    Harness {
        _tmp: tmp,
        state,
        readme,
        rel_path: rel.into(),
    }
}

async fn post(state: &AppState, url: &str, body: Value) -> (StatusCode, Value) {
    let app = build_router(state.clone());
    let req = Request::builder()
        .method(Method::POST)
        .uri(url)
        .header("content-type", "application/json")
        .body(Body::from(serde_json::to_vec(&body).unwrap()))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    let status = resp.status();
    let bytes = to_bytes(resp.into_body(), 64 * 1024).await.unwrap();
    let parsed: Value = serde_json::from_slice(&bytes).unwrap_or(Value::Null);
    (status, parsed)
}

fn read(p: &Path) -> String {
    std::fs::read_to_string(p).expect("read back")
}

// ---------------------------------------------------------------------
// /toggle
// ---------------------------------------------------------------------

#[tokio::test]
async fn toggle_flips_checkbox_and_returns_new_status() {
    let h = harness_with("- [ ] first\n");
    let (status, body) = post(&h.state, "/toggle", json!({"file": h.rel_path, "line": 0})).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["ok"], json!(true));
    assert_eq!(body["status"], json!("done"));
    assert_eq!(read(&h.readme), "- [x] first\n");
}

#[tokio::test]
async fn toggle_rejects_non_checkbox_line() {
    let h = harness_with("plain text\n");
    let (status, body) = post(&h.state, "/toggle", json!({"file": h.rel_path, "line": 0})).await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert_eq!(body["error"], json!("not a checkbox line"));
}

#[tokio::test]
async fn toggle_rejects_invalid_path() {
    let h = harness_with("- [ ] x\n");
    let (status, body) = post(
        &h.state,
        "/toggle",
        json!({"file": "../etc/passwd", "line": 0}),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert_eq!(body["error"], json!("invalid path"));
}

// ---------------------------------------------------------------------
// /add-step
// ---------------------------------------------------------------------

#[tokio::test]
async fn add_step_inserts_and_returns_line() {
    let h = harness_with("# T\n\n## Steps\n\n- [ ] old\n");
    let (status, body) = post(
        &h.state,
        "/add-step",
        json!({"file": h.rel_path, "text": "new"}),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["ok"], json!(true));
    assert!(body["line"].is_u64());
    assert!(read(&h.readme).contains("- [ ] old\n- [ ] new\n"));
}

#[tokio::test]
async fn add_step_rejects_empty_text() {
    let h = harness_with("# T\n\n## Steps\n\n- [ ] old\n");
    let (status, body) = post(
        &h.state,
        "/add-step",
        json!({"file": h.rel_path, "text": "   "}),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert_eq!(body["error"], json!("empty text"));
}

// ---------------------------------------------------------------------
// /remove-step
// ---------------------------------------------------------------------

#[tokio::test]
async fn remove_step_drops_line() {
    let h = harness_with("- [ ] a\n- [ ] b\n- [ ] c\n");
    let (status, body) = post(
        &h.state,
        "/remove-step",
        json!({"file": h.rel_path, "line": 1}),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["ok"], json!(true));
    assert_eq!(read(&h.readme), "- [ ] a\n- [ ] c\n");
}

#[tokio::test]
async fn remove_step_rejects_non_checkbox() {
    let h = harness_with("heading\n- [ ] a\n");
    let (status, body) = post(
        &h.state,
        "/remove-step",
        json!({"file": h.rel_path, "line": 0}),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert_eq!(body["error"], json!("cannot remove"));
}

// ---------------------------------------------------------------------
// /edit-step
// ---------------------------------------------------------------------

#[tokio::test]
async fn edit_step_rewrites_body() {
    let h = harness_with("- [x] old\n");
    let (status, body) = post(
        &h.state,
        "/edit-step",
        json!({"file": h.rel_path, "line": 0, "text": "new"}),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["ok"], json!(true));
    assert_eq!(read(&h.readme), "- [x] new\n");
}

#[tokio::test]
async fn edit_step_rejects_empty_text() {
    let h = harness_with("- [x] old\n");
    let (status, body) = post(
        &h.state,
        "/edit-step",
        json!({"file": h.rel_path, "line": 0, "text": "  "}),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert_eq!(body["error"], json!("empty text"));
}

// ---------------------------------------------------------------------
// /set-priority
// ---------------------------------------------------------------------

#[tokio::test]
async fn set_priority_rewrites_status() {
    let h = harness_with("# T\n\n**Date**: 2026-04-22\n**Status**: now\n");
    let (status, body) = post(
        &h.state,
        "/set-priority",
        json!({"file": h.rel_path, "priority": "soon"}),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["ok"], json!(true));
    assert_eq!(body["priority"], json!("soon"));
    assert!(read(&h.readme).contains("**Status**: soon"));
}

#[tokio::test]
async fn set_priority_rejects_unknown() {
    let h = harness_with("# T\n\n**Status**: now\n");
    let (status, body) = post(
        &h.state,
        "/set-priority",
        json!({"file": h.rel_path, "priority": "urgent"}),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert_eq!(body["error"], json!("invalid priority"));
}

// ---------------------------------------------------------------------
// /reorder-all
// ---------------------------------------------------------------------

#[tokio::test]
async fn reorder_all_shuffles_checkboxes() {
    let h = harness_with("## Steps\n\n- [ ] a\n- [x] b\n- [~] c\n");
    // lines: 0="## Steps", 1="", 2,3,4=checkboxes. Reorder [c,a,b].
    let (status, body) = post(
        &h.state,
        "/reorder-all",
        json!({"file": h.rel_path, "order": [4, 2, 3]}),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["ok"], json!(true));
    assert_eq!(read(&h.readme), "## Steps\n\n- [~] c\n- [ ] a\n- [x] b\n");
}

#[tokio::test]
async fn reorder_all_rejects_non_checkbox_index() {
    let h = harness_with("heading\n- [ ] a\n- [ ] b\n");
    let (status, body) = post(
        &h.state,
        "/reorder-all",
        json!({"file": h.rel_path, "order": [0, 1, 2]}),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert_eq!(body["error"], json!("cannot reorder"));
}
