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

use std::sync::Arc;

use anyhow::{Context, Result};
use condash_lib::{assets, build_ctx_for_bin, load_template_for_bin, resolve_conception_path};
use condash_state::WorkspaceCache;

fn main() -> Result<()> {
    // Scrub AppImage-injected env vars before tokio spawns any worker
    // thread — worker threads inherit the process env, and once they
    // exist we can't mutate env safely. See env_hygiene.rs.
    #[cfg(target_os = "linux")]
    condash_lib::env_hygiene::scrub_appimage_leaks();

    // Hand off to the async body on a runtime we build ourselves so
    // the scrub above is guaranteed to happen before any tokio thread
    // starts.
    tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
        .context("build tokio runtime")?
        .block_on(async_main())
}

async fn async_main() -> Result<()> {
    condash_lib::init_tracing();
    // Headless binary: env var → ~/.config/condash/settings.yaml →
    // hard error. No folder picker, no hard-coded default.
    let conception_path = resolve_conception_path().map_err(|e| anyhow::anyhow!("{e}"))?;
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

    // Bridge watcher events to the cache so hand-edits invalidate the
    // items / knowledge slices without needing an explicit `/rescan`.
    condash_lib::events::spawn_cache_invalidator(event_bus.clone(), cache.clone());

    let state = condash_lib::server::AppState {
        ctx_swap: Arc::new(arc_swap::ArcSwap::from(ctx)),
        cache,
        assets: asset_source,
        version: Arc::new(env!("CARGO_PKG_VERSION").to_string()),
        event_bus,
        pty_registry: condash_lib::pty::PtyRegistry::new(),
        runner_registry: condash_lib::runner_registry::RunnerRegistry::new(),
    };

    // Honor CONDASH_PORT if set, else pick a free one like the Tauri
    // host does (port = 0).
    let requested_port = match std::env::var("CONDASH_PORT").ok() {
        Some(p) => p.parse::<u16>().context("CONDASH_PORT is not a u16")?,
        None => 0,
    };
    let port = condash_lib::server::start(state, requested_port).await?;
    eprintln!("condash-serve: listening on http://127.0.0.1:{port}/");

    // Block forever — the server task owns the listener.
    std::future::pending::<()>().await;
    Ok(())
}
