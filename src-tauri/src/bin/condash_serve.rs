//! Headless dashboard server — same HTTP surface the Tauri webview
//! uses, but without the window. Handy for hitting the Rust build
//! from curl / Playwright / a regular browser during development,
//! and the natural driver for Phase 2's e2e exit gate before the
//! GUI-dependent Tauri bootstrap runs.
//!
//! Flags: reads the same env vars the Tauri host reads
//! (`CONDASH_CONCEPTION_PATH`, `CONDASH_ASSET_DIR`). Also accepts
//! `CONDASH_PORT` to pin the listen port — handy for Playwright
//! fixtures that want a stable URL.

use std::path::PathBuf;
use std::sync::Arc;

use anyhow::{Context, Result};
use condash_lib::{build_ctx_for_bin, resolve_asset_dir_for_bin};
use condash_state::WorkspaceCache;

#[tokio::main]
async fn main() -> Result<()> {
    let conception_path = match std::env::var_os("CONDASH_CONCEPTION_PATH") {
        Some(v) => PathBuf::from(v),
        None => {
            let home = std::env::var_os("HOME").context("HOME unset")?;
            PathBuf::from(home).join("src/vcoeur/conception")
        }
    };
    let asset_dir = resolve_asset_dir_for_bin();
    let template_path = asset_dir.join("dashboard.html");

    let ctx = Arc::new(build_ctx_for_bin(&conception_path, &template_path)?);
    let cache = Arc::new(WorkspaceCache::new());
    // Synchronous warm-up: the first HTTP hit pays the cost anyway, and
    // warming here makes the first request fast.
    let _ = cache.get_items(&ctx);
    let _ = cache.get_knowledge(&ctx);

    let state = condash_lib::server::AppState {
        ctx,
        cache,
        asset_dir: Arc::new(asset_dir),
        version: Arc::new(env!("CARGO_PKG_VERSION").to_string()),
    };

    // Honor CONDASH_PORT if set, else pick a free one like the Tauri
    // host does.
    let port = if let Some(p) = std::env::var("CONDASH_PORT").ok() {
        let port: u16 = p.parse().context("CONDASH_PORT is not a u16")?;
        condash_lib::server::start_on(state, port).await?
    } else {
        condash_lib::server::start(state).await?
    };
    eprintln!("condash-serve: listening on http://127.0.0.1:{port}/");

    // Block forever — the server task owns the listener.
    std::future::pending::<()>().await;
    Ok(())
}
