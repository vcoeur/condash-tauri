//! Configuration modal (`/configuration`) + legacy `/config` summary.
//!
//! - `GET /configuration` returns the raw `<conception>/configuration.yml`
//!   contents so the modal populates a single `<textarea>`.
//! - `POST /configuration` validates the body via serde (rejects
//!   invalid YAML with 400 + parse error), then atomically replaces
//!   the file. Changes take effect on the next launch — the
//!   `RenderCtx` is built once at startup and not hot-swapped here.
//! - `GET /config` is the small legacy summary the bundled frontend
//!   polls for setup-banner detection and terminal-shortcut loading.
//!   Returns only `conception_path` + the `terminal` block.
//!
//! `settings.yaml` is not written by any route — it is hand-edited on
//! disk and re-read on the next launch.
//!
//! Module name: `config_surface` rather than `config` so it doesn't
//! shadow the crate-root `config` module that owns `build_ctx`.

use axum::body::Body;
use axum::extract::State;
use axum::http::{header, HeaderValue, StatusCode};
use axum::response::{IntoResponse, Response};

use super::{error_json, json_response, AppState};

pub(super) async fn get_configuration(State(state): State<AppState>) -> Response {
    let path = crate::config::configuration_path(&state.ctx.base_dir);
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
    match crate::config::write_configuration(&state.ctx.base_dir, &body) {
        Ok(_path) => {
            // Invalidate caches so the next `/` hit re-walks the tree.
            // The RenderCtx itself still only rebuilds on restart or
            // /rescan — the modal's success message tells the user as
            // much.
            state.cache.invalidate_items();
            state.cache.invalidate_knowledge();
            (
                StatusCode::OK,
                [(header::CONTENT_TYPE, "text/plain; charset=utf-8")],
                "saved. Close and reopen condash for changes to take effect.\n",
            )
                .into_response()
        }
        Err(e) => error_json(StatusCode::INTERNAL_SERVER_ERROR, &format!("{e}")),
    }
}

pub(super) async fn get_config_summary(State(state): State<AppState>) -> Response {
    let conception_path = state.ctx.base_dir.to_string_lossy().into_owned();
    let term = &state.ctx.terminal;
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
