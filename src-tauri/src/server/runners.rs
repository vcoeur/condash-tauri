//! Runner routes — inline dev-server processes.
//!
//! - `POST /api/runner/start`      — spawn a dev server for a configured key
//! - `POST /api/runner/stop`       — SIGTERM + reap + clear
//! - `POST /api/runner/force-stop` — repo-level nuclear stop (free a port)
//! - `GET  /ws/runner/:key`        — attach a viewer to the live session

use axum::extract::State;
use axum::http::StatusCode;
use axum::response::IntoResponse;
use axum::Json;
use futures_util::SinkExt;
use serde::Deserialize;

use super::{error_json, json_response, json_with_status, validate_open_path, AppState};

#[derive(Debug, Deserialize)]
pub(super) struct RunnerStartPayload {
    #[serde(default)]
    key: String,
    #[serde(default)]
    checkout_key: String,
    #[serde(default)]
    path: String,
}

pub(super) async fn runner_start_route(
    State(state): State<AppState>,
    Json(p): Json<RunnerStartPayload>,
) -> impl IntoResponse {
    let key = p.key.trim();
    let checkout_key = p.checkout_key.trim();
    let path_raw = p.path.trim();
    if key.is_empty() || checkout_key.is_empty() || path_raw.is_empty() {
        return error_json(StatusCode::BAD_REQUEST, "key, checkout_key, path required");
    }
    let Some(template) = state.ctx().repo_run_templates.get(key).cloned() else {
        return error_json(
            StatusCode::NOT_FOUND,
            &format!("no run command configured for {key}"),
        );
    };
    let Some(validated) = validate_open_path(&state.ctx(), path_raw) else {
        return error_json(
            StatusCode::BAD_REQUEST,
            &format!("path out of sandbox: {path_raw}"),
        );
    };
    if let Some(existing) = state.runner_registry.get(key) {
        if existing.exit_code_now().is_none() {
            return json_with_status(
                &serde_json::json!({
                    "error": "runner already active",
                    "key": key,
                    "checkout_key": existing.checkout_key,
                }),
                StatusCode::CONFLICT,
            );
        }
    }
    let shell = crate::pty::resolve_terminal_shell(None);
    match crate::runner_registry::start(
        &state.runner_registry,
        &state.pty_registry,
        key,
        checkout_key,
        validated.to_str().unwrap_or(path_raw),
        &template,
        &shell,
    ) {
        Ok(session) => {
            let body = serde_json::json!({
                "ok": true,
                "key": session.key,
                "checkout_key": session.checkout_key,
                "pid": session.pty.session_id,
                "template": session.template,
            });
            json_response(&body)
        }
        Err(e) => error_json(StatusCode::INTERNAL_SERVER_ERROR, &format!("spawn: {e}")),
    }
}

#[derive(Debug, Deserialize)]
pub(super) struct RunnerStopPayload {
    #[serde(default)]
    key: String,
}

pub(super) async fn runner_stop_route(
    State(state): State<AppState>,
    Json(p): Json<RunnerStopPayload>,
) -> impl IntoResponse {
    let key = p.key.trim();
    if key.is_empty() {
        return error_json(StatusCode::BAD_REQUEST, "key required");
    }
    let Some(session) = state.runner_registry.get(key) else {
        return json_response(&serde_json::json!({"ok": true, "cleared": false}));
    };
    if session.exit_code_now().is_some() {
        crate::runner_registry::clear_exited(&state.runner_registry, key);
        return json_response(&serde_json::json!({"ok": true, "cleared": true, "exited": true}));
    }
    match crate::runner_registry::stop(
        &state.runner_registry,
        key,
        std::time::Duration::from_secs(5),
    )
    .await
    {
        Ok(_) => json_response(&serde_json::json!({"ok": true, "cleared": true})),
        Err(e) => error_json(StatusCode::INTERNAL_SERVER_ERROR, &format!("stop: {e}")),
    }
}

#[derive(Debug, Deserialize)]
pub(super) struct RunnerForceStopPayload {
    #[serde(default)]
    key: String,
}

/// `POST /api/runner/force-stop` — run the configured `force_stop`
/// command for `key`. Unlike `/api/runner/stop`, which only touches
/// sessions condash launched, this invokes a user-supplied shell
/// fragment meant to kill whatever is currently holding the port
/// (a stale gunicorn, a server started from another terminal).
///
/// The command runs detached via `sh -c`; we wait up to 5s for it to
/// exit so the frontend can report success/failure, but any child
/// processes the command starts are not tracked. Also clears any
/// condash-managed session for `key` so the tri-state button resets
/// to Start without a further refresh.
pub(super) async fn runner_force_stop_route(
    State(state): State<AppState>,
    Json(p): Json<RunnerForceStopPayload>,
) -> impl IntoResponse {
    let key = p.key.trim();
    if key.is_empty() {
        return error_json(StatusCode::BAD_REQUEST, "key required");
    }
    let Some(command) = state.ctx().repo_force_stop_templates.get(key).cloned() else {
        return error_json(
            StatusCode::NOT_FOUND,
            &format!("no force_stop command configured for {key}"),
        );
    };

    // Best-effort: stop any condash-managed session for the same key
    // first so the registry reflects reality once the external
    // process is gone. Ignore failures — the user's force_stop is
    // what the request is really about.
    if let Some(session) = state.runner_registry.get(key) {
        if session.exit_code_now().is_some() {
            crate::runner_registry::clear_exited(&state.runner_registry, key);
        } else {
            let _ = crate::runner_registry::stop(
                &state.runner_registry,
                key,
                std::time::Duration::from_secs(2),
            )
            .await;
        }
    }

    let cmd = command.clone();
    let spawn = tokio::task::spawn_blocking(move || {
        std::process::Command::new("sh")
            .arg("-c")
            .arg(&cmd)
            .stdin(std::process::Stdio::null())
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::piped())
            .spawn()
    })
    .await;
    let child = match spawn {
        Ok(Ok(c)) => c,
        Ok(Err(e)) => {
            return error_json(
                StatusCode::INTERNAL_SERVER_ERROR,
                &format!("spawn force_stop: {e}"),
            );
        }
        Err(e) => {
            return error_json(
                StatusCode::INTERNAL_SERVER_ERROR,
                &format!("spawn force_stop task: {e}"),
            );
        }
    };

    // Wait up to 5s so the UI can flag scripts that hang. After that
    // we leave the process running and return ok — the script is
    // user-supplied, so a long-running "kill -9 && sleep 10" is a
    // legitimate shape we don't want to block the request on.
    let wait = tokio::task::spawn_blocking(move || child.wait_with_output());
    let outcome = tokio::time::timeout(std::time::Duration::from_secs(5), wait).await;
    match outcome {
        Ok(Ok(Ok(output))) => {
            let body = serde_json::json!({
                "ok": output.status.success(),
                "exit_code": output.status.code(),
                "stdout": String::from_utf8_lossy(&output.stdout),
                "stderr": String::from_utf8_lossy(&output.stderr),
                "command": command,
            });
            json_response(&body)
        }
        Ok(Ok(Err(e))) => error_json(
            StatusCode::INTERNAL_SERVER_ERROR,
            &format!("force_stop wait: {e}"),
        ),
        Ok(Err(e)) => error_json(
            StatusCode::INTERNAL_SERVER_ERROR,
            &format!("force_stop join: {e}"),
        ),
        Err(_) => {
            // Timed out waiting for exit. The process is still alive
            // and detached — report ok so the UI shows success; the
            // next /check-updates cycle will pick up whatever state it
            // ends in.
            json_response(&serde_json::json!({
                "ok": true,
                "detached": true,
                "command": command,
            }))
        }
    }
}

/// `/ws/runner/:key` — attach a viewer to an existing runner. Fails
/// closed with `session-missing` when the key has no live (or
/// exited-but-still-in-registry) entry; the Code tab posts
/// `/api/runner/start` first, so a miss here is unexpected.
pub(super) async fn runner_ws(
    ws: axum::extract::ws::WebSocketUpgrade,
    State(state): State<AppState>,
    axum::extract::Path(key): axum::extract::Path<String>,
) -> impl IntoResponse {
    ws.on_upgrade(move |socket| handle_runner_ws(socket, state, key))
}

async fn handle_runner_ws(mut socket: axum::extract::ws::WebSocket, state: AppState, key: String) {
    use axum::extract::ws::Message;

    if !crate::pty::supports_pty() {
        let _ = socket
            .send(Message::Text(
                serde_json::json!({
                    "type": "error",
                    "message": "Runner only supported on Linux/macOS.",
                })
                .to_string()
                .into(),
            ))
            .await;
        let _ = socket.close().await;
        return;
    }

    let Some(session) = state.runner_registry.get(&key) else {
        let _ = socket
            .send(Message::Text(
                serde_json::json!({"type": "session-missing", "key": key})
                    .to_string()
                    .into(),
            ))
            .await;
        let _ = socket.close().await;
        return;
    };

    // Displace any stale viewer.
    session.pty.detach_viewer();

    let info = serde_json::json!({
        "type": "info",
        "key": session.key,
        "checkout_key": session.checkout_key,
        "path": session.path,
        "template": session.template,
        "exit_code": session.exit_code_now(),
    });
    if socket
        .send(Message::Text(info.to_string().into()))
        .await
        .is_err()
    {
        return;
    }

    let mut rx = session.pty.attach_viewer();

    // If the runner already exited, emit the exit frame once the
    // buffer has been drained so the client paints the greyed status
    // line.
    if let Some(code) = session.exit_code_now() {
        let _ = socket
            .send(Message::Text(
                serde_json::json!({"type": "exit", "exit_code": code})
                    .to_string()
                    .into(),
            ))
            .await;
    }

    loop {
        tokio::select! {
            msg = rx.recv() => match msg {
                Some(crate::pty::PumpMessage::Data(bytes)) => {
                    if socket.send(Message::Binary(bytes.into())).await.is_err() {
                        break;
                    }
                }
                Some(crate::pty::PumpMessage::Exit) => {
                    let exit_code = session.exit_code_now().unwrap_or(0);
                    let _ = socket
                        .send(Message::Text(
                            serde_json::json!({"type": "exit", "exit_code": exit_code})
                                .to_string()
                                .into(),
                        ))
                        .await;
                    break;
                }
                None => break,
            },
            ws_msg = socket.recv() => match ws_msg {
                Some(Ok(Message::Binary(bytes))) => {
                    if session.exit_code_now().is_some() {
                        continue; // Swallow typing after exit.
                    }
                    if session.pty.write_input(&bytes).is_err() {
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
                            if session.exit_code_now().is_none() {
                                session.pty.resize(cols, rows);
                            }
                        }
                    }
                }
                Some(Ok(Message::Close(_))) | None => break,
                Some(Ok(_)) => {}
                Some(Err(_)) => break,
            }
        }
    }
    session.pty.detach_viewer();
}
