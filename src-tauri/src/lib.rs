//! Tauri host entry point. Phase 2 slice 5 wires axum in under the
//! webview: we start an HTTP server on a free localhost port, warm the
//! workspace cache, and navigate the main window to `http://127.0.0.1:<port>/`.
//!
//! The dashboard JS and templates are unchanged from the Python build —
//! they all speak plain HTTP fetches, so pointing the webview at our
//! axum server is the only integration delta.

use std::path::PathBuf;
use std::sync::Arc;

use condash_state::WorkspaceCache;
use tauri::Manager;

pub mod assets;
pub mod config;
pub mod events;
pub mod paths;
pub mod pty;
pub mod runners;
pub mod server;

/// Re-exports for the standalone `condash-serve` binary (same config
/// and asset resolution the Tauri host uses).
pub use config::build_ctx as build_ctx_for_bin;

/// Environment variable the dev build reads to locate the conception
/// tree. Production builds will ship a richer config layer (Phase 5).
const CONCEPTION_ENV: &str = "CONDASH_CONCEPTION_PATH";

/// Load the dashboard HTML template from the configured asset source.
/// Fails loudly when it's missing — the dashboard is unusable without
/// it, and the embedded variant ships it unconditionally, so a failure
/// here signals a bad `CONDASH_ASSET_DIR` override.
pub fn load_template_for_bin(source: &assets::AssetSource) -> anyhow::Result<String> {
    let (bytes, _mime) = source.load("dashboard.html").ok_or_else(|| {
        anyhow::anyhow!(
            "asset 'dashboard.html' missing from {:?}",
            source
                .disk_root()
                .map(|p| p.display().to_string())
                .unwrap_or_else(|| "embedded".into()),
        )
    })?;
    Ok(String::from_utf8(bytes.into_owned())
        .map_err(|e| anyhow::anyhow!("dashboard.html is not valid UTF-8: {e}"))?)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            let conception_path = resolve_conception_path()?;
            let asset_source = assets::pick_from_env();
            let template =
                load_template_for_bin(&asset_source).map_err(|e| format!("load template: {e}"))?;
            let ctx = config::build_ctx(&conception_path, template)
                .map_err(|e| format!("build_ctx: {e}"))?;
            let ctx = Arc::new(ctx);

            let cache = Arc::new(WorkspaceCache::new());
            // Warm the cache off the main thread so window creation
            // doesn't block on parser + git scans.
            let warm_ctx = ctx.clone();
            let warm_cache = cache.clone();
            tauri::async_runtime::spawn_blocking(move || {
                let _ = warm_cache.get_items(&warm_ctx);
                let _ = warm_cache.get_knowledge(&warm_ctx);
            });

            let event_bus = events::EventBus::default();
            let pty_registry = pty::PtyRegistry::new();
            let runner_registry = runners::RunnerRegistry::new();
            let state = server::AppState {
                ctx: ctx.clone(),
                cache,
                assets: asset_source,
                version: Arc::new(env!("CARGO_PKG_VERSION").to_string()),
                event_bus: event_bus.clone(),
                pty_registry: pty_registry.clone(),
                runner_registry: runner_registry.clone(),
            };

            // Start the filesystem watcher (best-effort — the UI
            // degrades to pure long-polling when the OS refuses to
            // attach the watcher, e.g. inotify limits).
            let watch_cfg = events::WatchConfig::from_ctx(
                &ctx.base_dir,
                ctx.workspace.as_deref(),
                ctx.worktrees.as_deref(),
            );
            let _watcher = events::start_watcher(event_bus.clone(), watch_cfg);
            if let Some(w) = _watcher {
                app.manage(w);
            }

            // Start axum + grab the port it picked.
            let port = tauri::async_runtime::block_on(server::start(state.clone()))
                .map_err(|e| format!("start server: {e}"))?;
            eprintln!("condash: HTTP server listening on 127.0.0.1:{port}");

            // Point the main window at the running server. If a window
            // already exists (from `windows` in tauri.conf.json), just
            // navigate it; otherwise build one programmatically.
            let url = format!("http://127.0.0.1:{port}/");
            let parsed: tauri::Url = url.parse().map_err(|e| format!("bad url: {e}"))?;
            if let Some(win) = app.get_webview_window("main") {
                win.navigate(parsed).map_err(|e| format!("navigate: {e}"))?;
            } else {
                tauri::WebviewWindowBuilder::new(app, "main", tauri::WebviewUrl::External(parsed))
                    .title("Conception Dashboard")
                    .inner_size(1400.0, 900.0)
                    .min_inner_size(800.0, 600.0)
                    .build()
                    .map_err(|e| format!("window build: {e}"))?;
            }

            // Keep the app state so it isn't dropped.
            app.manage(state);
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running condash Tauri application");
}

fn resolve_conception_path() -> Result<PathBuf, String> {
    if let Some(path) = std::env::var_os(CONCEPTION_ENV) {
        return Ok(PathBuf::from(path));
    }
    // Dev default — the user's conception tree.
    let fallback = std::env::var_os("HOME").map(|h| PathBuf::from(h).join("src/vcoeur/conception"));
    match fallback {
        Some(p) if p.is_dir() => Ok(p),
        _ => Err(format!(
            "no conception path configured. Set {CONCEPTION_ENV} or ensure ~/src/vcoeur/conception exists."
        )),
    }
}
