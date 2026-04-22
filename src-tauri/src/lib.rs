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

pub mod config;
pub mod server;

/// Re-exports for the standalone `condash-serve` binary (same config
/// and asset resolution the Tauri host uses).
pub use config::build_ctx as build_ctx_for_bin;

pub fn resolve_asset_dir_for_bin() -> PathBuf {
    resolve_asset_dir()
}

/// Environment variable the dev build reads to locate the conception
/// tree. Production builds will ship a richer config layer (Phase 5).
const CONCEPTION_ENV: &str = "CONDASH_CONCEPTION_PATH";

/// Environment variable that overrides the on-disk `assets/` directory.
/// Defaults to the path baked in at build time so `cargo tauri dev` out
/// of the worktree Just Works.
const ASSET_DIR_ENV: &str = "CONDASH_ASSET_DIR";

/// Compile-time default asset dir — resolved from the src-tauri crate
/// manifest, so a binary built from `cargo tauri dev` can locate
/// `dashboard.html` + `favicon.svg` + `dist/` + `vendor/` without
/// needing rust-embed (that's Phase 5 packaging work).
const DEFAULT_ASSET_DIR: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/../src/condash/assets");

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            let conception_path = resolve_conception_path()?;
            let asset_dir = resolve_asset_dir();
            let template_path = asset_dir.join("dashboard.html");
            let ctx = config::build_ctx(&conception_path, &template_path)
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

            let state = server::AppState {
                ctx,
                cache,
                asset_dir: Arc::new(asset_dir),
                version: Arc::new(env!("CARGO_PKG_VERSION").to_string()),
            };

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

fn resolve_asset_dir() -> PathBuf {
    if let Some(dir) = std::env::var_os(ASSET_DIR_ENV) {
        return PathBuf::from(dir);
    }
    PathBuf::from(DEFAULT_ASSET_DIR)
}
