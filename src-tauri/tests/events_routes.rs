//! Integration tests for the `/events` SSE stream + the event bus
//! plumbing under it.
//!
//! Two axes of coverage:
//!
//! 1. The handler emits the opening `event: hello` frame as soon as the
//!    client connects, before any filesystem activity.
//! 2. A `bus.publish(...)` call reaches a live SSE subscriber as a
//!    `data: { … }` frame.

use std::path::PathBuf;
use std::sync::Arc;

use axum::body::Body;
use axum::http::{Request, StatusCode};
use condash_lib::events::{EventBus, EventPayload};
use condash_lib::server::{build_router, AppState};
use condash_state::{RenderCtx, WorkspaceCache};
use futures_util::StreamExt;
use tempfile::TempDir;
use tower::ServiceExt;

fn state_with_bus() -> (TempDir, AppState, EventBus) {
    let tmp = TempDir::new().expect("tmp");
    let ctx = Arc::new(RenderCtx::with_base_dir(tmp.path()));
    let cache = Arc::new(WorkspaceCache::new());
    let bus = EventBus::default();
    let state = AppState {
        ctx_swap: Arc::new(arc_swap::ArcSwap::from(ctx)),
        cache,
        assets: condash_lib::assets::AssetSource::Embedded,
        version: Arc::new("test".into()),
        event_bus: bus.clone(),
        pty_registry: condash_lib::pty::PtyRegistry::new(),
        runner_registry: condash_lib::runner_registry::RunnerRegistry::new(),
    };
    (tmp, state, bus)
}

#[tokio::test]
async fn events_stream_emits_hello_frame_on_connect() {
    let (_tmp, state, _bus) = state_with_bus();
    let app = build_router(state);
    let req = Request::builder()
        .method("GET")
        .uri("/events")
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
    assert_eq!(
        resp.headers()
            .get("content-type")
            .unwrap()
            .to_str()
            .unwrap(),
        "text/event-stream"
    );

    let mut stream = resp.into_body().into_data_stream();
    let Some(chunk) = stream.next().await else {
        panic!("stream closed before hello frame");
    };
    let bytes = chunk.expect("chunk read");
    let s = std::str::from_utf8(&bytes).expect("utf-8 frame");
    assert!(
        s.contains("event: hello"),
        "expected hello frame, got {s:?}"
    );
    assert!(s.contains("data: {}"), "expected empty data, got {s:?}");
}

#[tokio::test]
async fn events_stream_forwards_bus_publish_to_subscriber() {
    let (_tmp, state, bus) = state_with_bus();
    let app = build_router(state);
    let req = Request::builder()
        .method("GET")
        .uri("/events")
        .body(Body::empty())
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    let mut stream = resp.into_body().into_data_stream();

    // Drain the hello frame first.
    let _hello = stream.next().await.unwrap().unwrap();

    // Publish an event. Spawn the publish from another task so the
    // stream future and the send don't deadlock on a single-threaded
    // runtime.
    let bus2 = bus.clone();
    tokio::spawn(async move {
        // Wait a hair so the subscriber is definitely attached.
        tokio::time::sleep(std::time::Duration::from_millis(20)).await;
        bus2.publish(EventPayload {
            tab: "projects".into(),
            ts: 1234,
        });
    });

    let chunk = tokio::time::timeout(std::time::Duration::from_secs(2), stream.next())
        .await
        .expect("timed out waiting for forwarded event")
        .expect("stream still open")
        .expect("chunk read");
    let s = std::str::from_utf8(&chunk).expect("utf-8 frame");
    assert!(
        s.contains("data: ") && s.contains("\"tab\":\"projects\""),
        "expected projects event frame, got {s:?}"
    );
    assert!(s.contains("\"ts\":1234"), "ts missing from {s:?}");
}
