//! `/ws/term` — embedded-terminal handler.
//!
//! - Query params: `session_id` (reattach), `cwd` (override working
//!   dir), `launcher` (=1 to spawn the configured launcher instead of
//!   a shell).
//! - Frames: `info` on attach, `session-expired` for stale reattach,
//!   `error` when PTY isn't supported, `exit` when the shell exits.
//! - The PTY survives a ws disconnect (only the viewer detaches).

use axum::extract::{Query, State};
use axum::response::IntoResponse;
use futures_util::SinkExt;
use serde::Deserialize;

use super::AppState;

#[derive(Debug, Deserialize)]
pub(super) struct TermQuery {
    #[serde(default)]
    session_id: Option<String>,
    #[serde(default)]
    cwd: Option<String>,
    #[serde(default)]
    launcher: Option<String>,
}

pub(super) async fn term_ws(
    ws: axum::extract::ws::WebSocketUpgrade,
    State(state): State<AppState>,
    Query(q): Query<TermQuery>,
) -> impl IntoResponse {
    ws.on_upgrade(move |socket| handle_term_ws(socket, state, q))
}

async fn handle_term_ws(mut socket: axum::extract::ws::WebSocket, state: AppState, q: TermQuery) {
    use axum::extract::ws::Message;

    if !crate::pty::supports_pty() {
        let _ = socket
            .send(Message::Text(
                serde_json::json!({
                    "type": "error",
                    "message": "Terminal only supported on Linux/macOS.",
                })
                .to_string()
                .into(),
            ))
            .await;
        let _ = socket.close().await;
        return;
    }

    let requested_id = q.session_id.as_deref().filter(|s| !s.is_empty());
    let existing = requested_id.and_then(|id| state.pty_registry.get(id));

    if let Some(id) = requested_id {
        if existing.is_none() {
            // Reattach to an unknown session — tell the client so it
            // can drop the stale id from its localStorage instead of
            // silently starting a new shell under the same tab.
            let _ = socket
                .send(Message::Text(
                    serde_json::json!({
                        "type": "session-expired",
                        "session_id": id,
                    })
                    .to_string()
                    .into(),
                ))
                .await;
            let _ = socket.close().await;
            return;
        }
    }

    let session = if let Some(s) = existing {
        // Displace any stale viewer — one attached ws per session.
        s.detach_viewer();
        s
    } else {
        let cwd = q
            .cwd
            .as_deref()
            .and_then(|c| {
                let candidate = std::path::PathBuf::from(c);
                if candidate.is_dir() {
                    Some(candidate)
                } else {
                    None
                }
            })
            .unwrap_or_else(|| state.ctx.base_dir.clone());
        let use_launcher = q.launcher.as_deref() == Some("1");
        let launcher_argv = if use_launcher {
            state
                .ctx
                .terminal
                .launcher_command
                .as_deref()
                .map(str::trim)
                .filter(|s| !s.is_empty())
                .and_then(shlex::split)
                .filter(|argv| !argv.is_empty())
        } else {
            None
        };
        let mode = match launcher_argv {
            Some(argv) => crate::pty::SpawnMode::Launcher { argv },
            None => crate::pty::SpawnMode::LoginShell {
                shell: crate::pty::resolve_terminal_shell(None),
            },
        };
        match crate::pty::spawn_session(&state.pty_registry, mode, cwd, 80, 24) {
            Ok(s) => s,
            Err(e) => {
                let _ = socket
                    .send(Message::Text(
                        serde_json::json!({
                            "type": "error",
                            "message": format!("spawn failed: {e}"),
                        })
                        .to_string()
                        .into(),
                    ))
                    .await;
                let _ = socket.close().await;
                return;
            }
        }
    };

    // Info frame — shell, cwd, session id.
    let info = serde_json::json!({
        "type": "info",
        "session_id": session.session_id,
        "shell": session.shell,
        "cwd": session.cwd.to_string_lossy(),
    });
    if socket
        .send(Message::Text(info.to_string().into()))
        .await
        .is_err()
    {
        return;
    }

    // Attach this socket as the viewer. The buffer replay is pushed
    // into the channel by attach_viewer itself.
    let mut rx = session.attach_viewer();

    // Fan out incoming PumpMessage frames to the socket, and route
    // incoming ws frames to the pty writer — both concurrently.
    loop {
        tokio::select! {
            msg = rx.recv() => match msg {
                Some(crate::pty::PumpMessage::Data(bytes)) => {
                    if socket.send(Message::Binary(bytes.into())).await.is_err() {
                        break;
                    }
                }
                Some(crate::pty::PumpMessage::Exit) => {
                    let _ = socket
                        .send(Message::Text(
                            serde_json::json!({"type": "exit"}).to_string().into(),
                        ))
                        .await;
                    let _ = socket.close().await;
                    return;
                }
                None => {
                    // Viewer channel dropped (e.g. displaced by another
                    // connection). Close the ws so the client reconnects.
                    let _ = socket.close().await;
                    return;
                }
            },
            ws_msg = socket.recv() => match ws_msg {
                Some(Ok(Message::Binary(bytes))) => {
                    if session.write_input(&bytes).is_err() {
                        break;
                    }
                }
                Some(Ok(Message::Text(text))) => {
                    if let Ok(val) = serde_json::from_str::<serde_json::Value>(&text) {
                        if val.get("type").and_then(|v| v.as_str()) == Some("resize") {
                            let cols = val
                                .get("cols")
                                .and_then(|v| v.as_u64())
                                .unwrap_or(80) as u16;
                            let rows = val
                                .get("rows")
                                .and_then(|v| v.as_u64())
                                .unwrap_or(24) as u16;
                            session.resize(cols, rows);
                        }
                    }
                }
                Some(Ok(Message::Close(_))) | None => break,
                Some(Ok(_)) => {}
                Some(Err(_)) => break,
            }
        }
    }

    session.detach_viewer();
}
