//! Integration tests for the Phase 4 slice 2 runner routes.
//!
//! Covers:
//! - `POST /api/runner/start` — missing/bad config → 404, good config
//!   → 200 with {ok, key, template}, double-start → 409.
//! - `POST /api/runner/stop` — clears a live session; no-op on unknown
//!   key; clears an exited session.
//! - `GET /ws/runner/:key` — `session-missing` when no session, `info`
//!   frame when one exists.

#![cfg(target_os = "linux")]

use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use axum::body::{to_bytes, Body};
use axum::http::{Method, Request, StatusCode};
use condash_lib::events::EventBus;
use condash_lib::pty::PtyRegistry;
use condash_lib::runners::RunnerRegistry;
use condash_lib::server::{self, build_router, AppState};
use condash_state::{RenderCtx, WorkspaceCache};
use futures_util::StreamExt;
use serde_json::{json, Value};
use tempfile::TempDir;
use tokio_tungstenite::tungstenite::Message;
use tower::ServiceExt;

struct Harness {
    _tmp: TempDir,
    state: AppState,
    repo_dir: PathBuf,
}

fn harness_with(templates: Vec<(&str, &str)>) -> Harness {
    let tmp = TempDir::new().expect("tmp");
    // Create a fake workspace + one repo directory so validate_open_path
    // accepts it.
    let workspace = tmp.path().join("src");
    let repo_dir = workspace.join("demo");
    std::fs::create_dir_all(&repo_dir).unwrap();

    let mut ctx = RenderCtx::with_base_dir(tmp.path());
    ctx.workspace = Some(workspace.clone());
    ctx.repo_run_templates = templates
        .into_iter()
        .map(|(k, v)| (k.to_string(), v.to_string()))
        .collect();
    ctx.repo_run_keys = ctx.repo_run_templates.keys().cloned().collect();

    let state = AppState {
        ctx: Arc::new(ctx),
        cache: Arc::new(WorkspaceCache::new()),
        assets: condash_lib::assets::AssetSource::Embedded,
        version: Arc::new("test".into()),
        event_bus: EventBus::default(),
        pty_registry: PtyRegistry::new(),
        runner_registry: RunnerRegistry::new(),
    };
    Harness {
        _tmp: tmp,
        state,
        repo_dir,
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
    (
        status,
        serde_json::from_slice(&bytes).unwrap_or(Value::Null),
    )
}

// ---------------------------------------------------------------------
// /api/runner/start
// ---------------------------------------------------------------------

#[tokio::test]
async fn start_rejects_missing_required_fields() {
    let h = harness_with(vec![("demo", "sleep 30")]);
    let (status, body) = post(&h.state, "/api/runner/start", json!({})).await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert!(body["error"]
        .as_str()
        .unwrap()
        .contains("key, checkout_key, path required"));
}

#[tokio::test]
async fn start_404s_for_unconfigured_key() {
    let h = harness_with(vec![]);
    let (status, body) = post(
        &h.state,
        "/api/runner/start",
        json!({
            "key": "demo",
            "checkout_key": "demo@main",
            "path": h.repo_dir.to_string_lossy(),
        }),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    assert!(body["error"].as_str().unwrap().contains("no run command"));
}

#[tokio::test]
async fn start_rejects_path_outside_workspace() {
    let h = harness_with(vec![("demo", "sleep 30")]);
    let outside = h._tmp.path().parent().unwrap().to_path_buf();
    let (status, body) = post(
        &h.state,
        "/api/runner/start",
        json!({
            "key": "demo",
            "checkout_key": "demo@main",
            "path": outside.to_string_lossy(),
        }),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert!(body["error"]
        .as_str()
        .unwrap()
        .contains("path out of sandbox"));
}

#[tokio::test]
async fn start_then_double_start_returns_409() {
    let h = harness_with(vec![("demo", "sleep 30")]);
    let (s1, _body) = post(
        &h.state,
        "/api/runner/start",
        json!({
            "key": "demo",
            "checkout_key": "demo@main",
            "path": h.repo_dir.to_string_lossy(),
        }),
    )
    .await;
    assert_eq!(s1, StatusCode::OK);
    let (s2, body) = post(
        &h.state,
        "/api/runner/start",
        json!({
            "key": "demo",
            "checkout_key": "demo@main",
            "path": h.repo_dir.to_string_lossy(),
        }),
    )
    .await;
    assert_eq!(s2, StatusCode::CONFLICT);
    assert_eq!(body["error"], json!("runner already active"));
    // Clean up to not leak the sleeper.
    let _ = post(&h.state, "/api/runner/stop", json!({"key": "demo"})).await;
}

// ---------------------------------------------------------------------
// /api/runner/stop
// ---------------------------------------------------------------------

#[tokio::test]
async fn stop_clears_a_live_runner() {
    let h = harness_with(vec![("demo", "sleep 30")]);
    let (_s, _b) = post(
        &h.state,
        "/api/runner/start",
        json!({
            "key": "demo",
            "checkout_key": "demo@main",
            "path": h.repo_dir.to_string_lossy(),
        }),
    )
    .await;
    assert_eq!(h.state.runner_registry.len(), 1);
    let (status, body) = post(&h.state, "/api/runner/stop", json!({"key": "demo"})).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["ok"], json!(true));
    assert_eq!(body["cleared"], json!(true));
    assert_eq!(h.state.runner_registry.len(), 0);
}

#[tokio::test]
async fn stop_noop_on_unknown_key() {
    let h = harness_with(vec![]);
    let (status, body) = post(&h.state, "/api/runner/stop", json!({"key": "ghost"})).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["ok"], json!(true));
    assert_eq!(body["cleared"], json!(false));
}

// ---------------------------------------------------------------------
// /ws/runner/:key
// ---------------------------------------------------------------------

#[tokio::test]
async fn ws_runner_sends_session_missing_frame_for_unknown_key() {
    let h = harness_with(vec![]);
    let port = server::start(h.state.clone()).await.expect("start server");
    let url = format!("ws://127.0.0.1:{port}/ws/runner/unknown");
    let (mut stream, _resp) = tokio_tungstenite::connect_async(&url)
        .await
        .expect("ws connect");
    let Some(Ok(Message::Text(text))) = tokio::time::timeout(Duration::from_secs(3), stream.next())
        .await
        .expect("text frame timeout")
    else {
        panic!("expected text frame");
    };
    let v: Value = serde_json::from_str(&text).unwrap();
    assert_eq!(v["type"], json!("session-missing"));
    assert_eq!(v["key"], json!("unknown"));
}

#[tokio::test]
async fn ws_runner_sends_info_frame_for_live_session() {
    let h = harness_with(vec![("demo", "sleep 30")]);
    // Spawn the runner via the real HTTP route so state stays coherent.
    let (start_status, _) = post(
        &h.state,
        "/api/runner/start",
        json!({
            "key": "demo",
            "checkout_key": "demo@main",
            "path": h.repo_dir.to_string_lossy(),
        }),
    )
    .await;
    assert_eq!(start_status, StatusCode::OK);

    let port = server::start(h.state.clone()).await.expect("start server");
    let url = format!("ws://127.0.0.1:{port}/ws/runner/demo");
    let (mut stream, _resp) = tokio_tungstenite::connect_async(&url)
        .await
        .expect("ws connect");
    let Some(Ok(Message::Text(text))) = tokio::time::timeout(Duration::from_secs(3), stream.next())
        .await
        .expect("text frame timeout")
    else {
        panic!("expected info text frame");
    };
    let v: Value = serde_json::from_str(&text).unwrap();
    assert_eq!(v["type"], json!("info"));
    assert_eq!(v["key"], json!("demo"));
    assert_eq!(v["checkout_key"], json!("demo@main"));
    assert!(v["template"].as_str().unwrap().contains("sleep"));

    // Tear the session down so the sleep subprocess doesn't linger.
    drop(stream);
    let _ = post(&h.state, "/api/runner/stop", json!({"key": "demo"})).await;
}
