//! Configuration modal (`/configuration`) + legacy `/config` summary.
//!
//! - `GET /configuration` returns the raw `<conception>/configuration.yml`
//!   contents so the modal populates a single `<textarea>`.
//! - `POST /configuration` validates the body via serde (rejects
//!   invalid YAML with 400 + parse error), atomically replaces the
//!   file, then **hot-rebuilds** the [`RenderCtx`] in place: the new
//!   `Arc<RenderCtx>` is swapped into [`AppState::ctx_swap`], the
//!   workspace cache is fully flushed, and SSE refresh events are
//!   republished for every primary tab so the open dashboard repaints
//!   without a restart.
//! - `GET /config` is the small legacy summary the bundled frontend
//!   polls for setup-banner detection and terminal-shortcut loading.
//!   Returns only `conception_path` + the `terminal` block.
//!
//! `settings.yaml` is not written by any route — it is hand-edited on
//! disk and re-read on the next launch.
//!
//! Module name: `config_surface` rather than `config` so it doesn't
//! shadow the crate-root `config` module that owns `build_ctx`.

use std::sync::Arc;

use axum::body::Body;
use axum::extract::State;
use axum::http::{header, HeaderValue, StatusCode};
use axum::response::{IntoResponse, Response};

use super::{error_json, json_response, AppState};

pub(super) async fn get_configuration(State(state): State<AppState>) -> Response {
    let path = crate::config::configuration_path(&state.ctx().base_dir);
    let body = match std::fs::read_to_string(&path) {
        Ok(s) => s,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => String::new(),
        Err(e) => return error_json(StatusCode::INTERNAL_SERVER_ERROR, &format!("read: {e}")),
    };
    let mut r = Response::new(Body::from(body));
    r.headers_mut().insert(
        header::CONTENT_TYPE,
        HeaderValue::from_static("text/yaml; charset=utf-8"),
    );
    if let Ok(hv) = HeaderValue::from_str(&path.to_string_lossy()) {
        r.headers_mut().insert("X-Condash-Config-Path", hv);
    }
    r
}

pub(super) async fn post_configuration(State(state): State<AppState>, body: String) -> Response {
    if let Err(e) = crate::config::validate_configuration_yaml(&body) {
        return error_json(StatusCode::BAD_REQUEST, &format!("{e}"));
    }
    let base_dir = state.ctx().base_dir.clone();
    if let Err(e) = crate::config::write_configuration(&base_dir, &body) {
        return error_json(StatusCode::INTERNAL_SERVER_ERROR, &format!("{e}"));
    }

    // Hot-rebuild the RenderCtx so live opener menus, terminal launchers,
    // and runner force-stop commands pick up the new configuration without
    // a restart. If the rebuild fails (template missing or build_ctx bug)
    // we still report success on the write — the file is saved — but tell
    // the user they need to reopen.
    let template = match crate::load_template_for_bin(&state.assets) {
        Ok(t) => t,
        Err(e) => {
            tracing::error!("post_configuration: template load failed: {e}");
            state
                .cache
                .consume(condash_state::MutationOutput::full_flush());
            return saved_response(true);
        }
    };
    match crate::config::build_ctx(&base_dir, template) {
        Ok(new_ctx) => {
            state.ctx_swap.store(Arc::new(new_ctx));
            state
                .cache
                .consume(condash_state::MutationOutput::full_flush());
            // Push refresh events for every primary tab so the open
            // browser repaints from the new ctx.
            for tab in ["projects", "knowledge", "code"] {
                state
                    .event_bus
                    .publish(crate::events::EventPayload::for_tab(tab));
            }
            saved_response(false)
        }
        Err(e) => {
            tracing::error!("post_configuration: build_ctx failed: {e}");
            state
                .cache
                .consume(condash_state::MutationOutput::full_flush());
            saved_response(true)
        }
    }
}

fn saved_response(needs_restart: bool) -> Response {
    let body = if needs_restart {
        "saved. Close and reopen condash for changes to take effect.\n"
    } else {
        "saved. Changes are live — no restart needed.\n"
    };
    (
        StatusCode::OK,
        [(header::CONTENT_TYPE, "text/plain; charset=utf-8")],
        body,
    )
        .into_response()
}

pub(super) async fn get_config_summary(State(state): State<AppState>) -> Response {
    let conception_path = state.ctx().base_dir.to_string_lossy().into_owned();
    let term = &state.ctx().terminal;
    let body = serde_json::json!({
        "conception_path": conception_path,
        "terminal": {
            "shell": term.shell.clone().unwrap_or_default(),
            "shortcut": term.shortcut.clone().unwrap_or_default(),
            "screenshot_dir": term.screenshot_dir.clone().unwrap_or_default(),
            "screenshot_paste_shortcut": term.screenshot_paste_shortcut.clone().unwrap_or_default(),
            "launcher_command": term.launcher_command.clone().unwrap_or_default(),
            "move_tab_left_shortcut": term.move_tab_left_shortcut.clone().unwrap_or_default(),
            "move_tab_right_shortcut": term.move_tab_right_shortcut.clone().unwrap_or_default(),
        }
    });
    json_response(&body)
}
