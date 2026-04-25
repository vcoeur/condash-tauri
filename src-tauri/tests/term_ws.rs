//! End-to-end integration test for `/ws/term`.
//!
//! Starts a real axum server on a free localhost port, connects via
//! `tokio-tungstenite`, and asserts on the handshake frames the handler
//! emits:
//! - `info` frame (session id + shell + cwd) immediately on attach
//! - binary frames carrying PTY output (we drive `echo marker; exit 0`
//!   by typing into the PTY, read the echo back)
//! - `exit` frame when the shell terminates

#![cfg(target_os = "linux")]

use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use condash_lib::events::EventBus;
use condash_lib::pty::PtyRegistry;
use condash_lib::server::{self, AppState};
use condash_state::{RenderCtx, WorkspaceCache};
use futures_util::{SinkExt, StreamExt};
use tempfile::TempDir;
use tokio_tungstenite::tungstenite::Message;

async fn start_server() -> (u16, TempDir) {
    let tmp = TempDir::new().expect("tmp");
    let ctx = Arc::new(RenderCtx::with_base_dir(tmp.path()));
    let cache = Arc::new(WorkspaceCache::new());
    let state = AppState {
        ctx_swap: Arc::new(arc_swap::ArcSwap::from(ctx)),
        cache,
        assets: condash_lib::assets::AssetSource::Embedded,
        version: Arc::new("test".into()),
        event_bus: EventBus::default(),
        pty_registry: PtyRegistry::new(),
        runner_registry: condash_lib::runner_registry::RunnerRegistry::new(),
    };
    let port = server::start(state, 0).await.expect("start server");
    (port, tmp)
}

#[tokio::test]
async fn term_ws_emits_info_frame_and_pty_output() {
    let (port, _tmp) = start_server().await;

    let url = format!("ws://127.0.0.1:{port}/ws/term");
    let (mut stream, _resp) = tokio_tungstenite::connect_async(&url)
        .await
        .expect("ws connect");

    // First frame: `info` — session id, shell, cwd.
    let Some(Ok(Message::Text(info))) = tokio::time::timeout(Duration::from_secs(5), stream.next())
        .await
        .expect("info frame timeout")
    else {
        panic!("expected text info frame");
    };
    let info_json: serde_json::Value = serde_json::from_str(&info).expect("info is json");
    assert_eq!(info_json["type"], serde_json::json!("info"));
    assert!(info_json["session_id"].is_string());
    assert!(info_json["shell"].is_string());

    // Type a command into the PTY: `echo marker-42\n` then `exit\n`.
    stream
        .send(Message::Binary(
            "echo marker-42\n".as_bytes().to_vec().into(),
        ))
        .await
        .expect("send echo");
    stream
        .send(Message::Binary("exit\n".as_bytes().to_vec().into()))
        .await
        .expect("send exit");

    // Collect frames until we see "marker-42" (could be split across
    // several binary messages — PTY output is line-buffered) and an
    // `exit` text frame.
    let mut got_marker = false;
    let mut got_exit = false;
    let deadline = tokio::time::Instant::now() + Duration::from_secs(10);
    while tokio::time::Instant::now() < deadline {
        let Ok(Some(msg)) = tokio::time::timeout(Duration::from_millis(500), stream.next()).await
        else {
            continue;
        };
        let Ok(msg) = msg else { break };
        match msg {
            Message::Binary(bytes) => {
                let s = String::from_utf8_lossy(&bytes);
                if s.contains("marker-42") {
                    got_marker = true;
                }
            }
            Message::Text(text) => {
                if text.contains("\"type\":\"exit\"") {
                    got_exit = true;
                    break;
                }
            }
            Message::Close(_) => break,
            _ => {}
        }
    }
    assert!(got_marker, "never saw marker-42 in PTY output");
    assert!(got_exit, "never saw exit frame");
}

#[tokio::test]
async fn term_ws_session_expired_when_reattach_unknown() {
    let (port, _tmp) = start_server().await;

    let url = format!("ws://127.0.0.1:{port}/ws/term?session_id=ghost-id-that-does-not-exist",);
    let (mut stream, _resp) = tokio_tungstenite::connect_async(&url)
        .await
        .expect("ws connect");

    let Some(Ok(Message::Text(text))) = tokio::time::timeout(Duration::from_secs(5), stream.next())
        .await
        .expect("expired frame timeout")
    else {
        panic!("expected session-expired text frame");
    };
    let v: serde_json::Value = serde_json::from_str(&text).expect("json");
    assert_eq!(v["type"], serde_json::json!("session-expired"));
    assert_eq!(
        v["session_id"],
        serde_json::json!("ghost-id-that-does-not-exist")
    );
}
