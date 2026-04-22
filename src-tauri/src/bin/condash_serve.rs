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
use condash_lib::{assets, build_ctx_for_bin, load_template_for_bin};
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
    let asset_source = assets::pick_from_env();
    let template = load_template_for_bin(&asset_source)?;

    let ctx = Arc::new(build_ctx_for_bin(&conception_path, template)?);
    let cache = Arc::new(WorkspaceCache::new());
    // Synchronous warm-up: the first HTTP hit pays the cost anyway, and
    // warming here makes the first request fast.
    let _ = cache.get_items(&ctx);
    let _ = cache.get_knowledge(&ctx);

    let event_bus = condash_lib::events::EventBus::default();
    // Start the filesystem watcher so /events pushes real staleness
    // signals. Hang onto the handle for the life of the process.
    let watch_cfg = condash_lib::events::WatchConfig::from_ctx(
        &ctx.base_dir,
        ctx.workspace.as_deref(),
        ctx.worktrees.as_deref(),
    );
    let _watcher = condash_lib::events::start_watcher(event_bus.clone(), watch_cfg);

    let state = condash_lib::server::AppState {
        ctx,
        cache,
        assets: asset_source,
        version: Arc::new(env!("CARGO_PKG_VERSION").to_string()),
        event_bus,
        pty_registry: condash_lib::pty::PtyRegistry::new(),
        runner_registry: condash_lib::runners::RunnerRegistry::new(),
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
