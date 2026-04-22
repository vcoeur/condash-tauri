//! Tauri host entry point. Phase 2 slice 5 wires axum in under the
//! webview: we start an HTTP server on a free localhost port, warm the
//! workspace cache, and navigate the main window to `http://127.0.0.1:<port>/`.
//!
//! The dashboard JS and templates are unchanged from the Python build —
//! they all speak plain HTTP fetches, so pointing the webview at our
//! axum server is the only integration delta.

use std::path::{Path, PathBuf};
use std::sync::Arc;

use condash_state::WorkspaceCache;
use tauri::Manager;

pub mod assets;
pub mod config;
pub mod events;
pub mod openers;
pub mod paths;
pub mod pty;
pub mod runners;
pub mod server;
pub mod user_config;

/// Re-exports for the standalone `condash-serve` binary (same config
/// and asset resolution the Tauri host uses).
pub use config::build_ctx as build_ctx_for_bin;

/// Environment variable that overrides every other source when
/// resolving the conception tree. Primarily useful for tests and
/// Playwright fixtures that want a stable path.
pub const CONCEPTION_ENV: &str = "CONDASH_CONCEPTION_PATH";

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
            let conception_path = match resolve_conception_path() {
                Ok(p) => p,
                Err(unset) => prompt_for_conception_path(unset).ok_or_else(|| {
                    "condash cancelled at the conception folder picker".to_string()
                })?,
            };
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

/// Error returned when no source provides a conception path. The
/// Tauri host upgrades this into a folder-picker prompt; `condash-serve`
/// surfaces it as a fatal error.
#[derive(Debug, Clone)]
pub struct ConceptionPathUnset {
    pub settings_path: Option<PathBuf>,
}

impl std::fmt::Display for ConceptionPathUnset {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let hint = self
            .settings_path
            .as_ref()
            .map(|p| p.display().to_string())
            .unwrap_or_else(|| "~/.config/condash/settings.yaml".into());
        write!(
            f,
            "no conception path configured. Set {CONCEPTION_ENV}, \
             or create {hint} with `conception_path: /path/to/conception`."
        )
    }
}

impl std::error::Error for ConceptionPathUnset {}

/// Resolve the conception tree from (in order): `CONDASH_CONCEPTION_PATH`
/// env var → user config at `~/.config/condash/settings.yaml` → absent.
///
/// The GUI binary wraps `Err(ConceptionPathUnset)` into a folder picker
/// (Phase 3); `condash-serve` and other headless callers surface the
/// error verbatim.
pub fn resolve_conception_path() -> Result<PathBuf, ConceptionPathUnset> {
    resolve_from(
        std::env::var_os(CONCEPTION_ENV).map(PathBuf::from),
        user_config::load().ok().flatten(),
        user_config::settings_file_path(),
    )
}

/// Pure form of [`resolve_conception_path`] — every input is explicit
/// so callers can unit-test the precedence rules without mutating
/// process env or the real settings file.
pub fn resolve_from(
    env_var: Option<PathBuf>,
    user_cfg: Option<user_config::UserConfig>,
    settings_path: Option<PathBuf>,
) -> Result<PathBuf, ConceptionPathUnset> {
    if let Some(p) = env_var.filter(|p| !p.as_os_str().is_empty()) {
        return Ok(p);
    }
    if let Some(cfg) = user_cfg {
        if let Some(p) = cfg.conception_path.filter(|p| !p.as_os_str().is_empty()) {
            return Ok(p);
        }
    }
    Err(ConceptionPathUnset { settings_path })
}

/// Native folder picker shown at first run when no env var and no
/// user config supply a conception path. Loops until the user picks a
/// directory that looks like a conception tree or cancels.
///
/// On success, persists the choice to the on-disk settings file so the
/// next launch skips the picker. Returns `None` when the user cancels
/// (the caller should exit cleanly).
fn prompt_for_conception_path(initial: ConceptionPathUnset) -> Option<PathBuf> {
    // Title picks a friendlier form than the raw error.
    let title = "Select your conception tree";
    let message = format!(
        "{}\n\nPick the root of your conception tree (the directory that \
         contains configuration.yml and/or projects/).",
        initial,
    );
    eprintln!("condash: {message}");

    loop {
        let Some(picked) = rfd::FileDialog::new().set_title(title).pick_folder() else {
            // User hit Cancel — bail to the caller.
            return None;
        };

        match validate_conception_candidate(&picked) {
            Ok(()) => {
                let cfg = user_config::UserConfig {
                    conception_path: Some(picked.clone()),
                };
                if let Err(e) = user_config::save(&cfg) {
                    // Don't fail the launch on a save failure — the
                    // user still gets a working session with this path,
                    // and they'll see the same picker on the next run.
                    eprintln!("condash: warning — could not persist settings.yaml: {e}");
                } else if let Some(path) = user_config::settings_file_path() {
                    eprintln!("condash: saved conception path to {}", path.display());
                }
                return Some(picked);
            }
            Err(reason) => {
                // Show a non-blocking error and loop back to the picker.
                rfd::MessageDialog::new()
                    .set_title("Not a conception tree")
                    .set_description(&format!("{}\n\n{}", picked.display(), reason))
                    .set_level(rfd::MessageLevel::Warning)
                    .show();
            }
        }
    }
}

/// Loose validation: the candidate must be a directory and contain
/// either `configuration.yml` (a migrated tree) or `projects/` (a
/// pre-migration or freshly-scaffolded tree). Stricter checks are
/// deliberately avoided — we re-prompt rather than punish plausible
/// picks.
pub fn validate_conception_candidate(path: &Path) -> Result<(), String> {
    if !path.is_dir() {
        return Err(format!("{} is not a directory.", path.display()));
    }
    let has_config = path.join("configuration.yml").is_file();
    let has_projects = path.join("projects").is_dir();
    if has_config || has_projects {
        return Ok(());
    }
    Err(
        "This directory does not look like a conception tree — expected configuration.yml \
         or projects/ inside it."
            .into(),
    )
}

#[cfg(test)]
mod validate_tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn rejects_missing_directory() {
        assert!(validate_conception_candidate(Path::new("/does/not/exist")).is_err());
    }

    #[test]
    fn rejects_empty_directory() {
        let tmp = tempdir().unwrap();
        assert!(validate_conception_candidate(tmp.path()).is_err());
    }

    #[test]
    fn accepts_directory_with_configuration_yml() {
        let tmp = tempdir().unwrap();
        std::fs::write(tmp.path().join("configuration.yml"), "").unwrap();
        assert!(validate_conception_candidate(tmp.path()).is_ok());
    }

    #[test]
    fn accepts_directory_with_projects_subdir() {
        let tmp = tempdir().unwrap();
        std::fs::create_dir(tmp.path().join("projects")).unwrap();
        assert!(validate_conception_candidate(tmp.path()).is_ok());
    }
}

#[cfg(test)]
mod resolve_tests {
    use super::*;
    use user_config::UserConfig;

    #[test]
    fn env_var_wins_over_user_config() {
        let got = resolve_from(
            Some(PathBuf::from("/from-env")),
            Some(UserConfig {
                conception_path: Some(PathBuf::from("/from-file")),
            }),
            None,
        )
        .unwrap();
        assert_eq!(got, PathBuf::from("/from-env"));
    }

    #[test]
    fn empty_env_var_falls_through_to_user_config() {
        let got = resolve_from(
            Some(PathBuf::from("")),
            Some(UserConfig {
                conception_path: Some(PathBuf::from("/from-file")),
            }),
            None,
        )
        .unwrap();
        assert_eq!(got, PathBuf::from("/from-file"));
    }

    #[test]
    fn user_config_used_when_env_absent() {
        let got = resolve_from(
            None,
            Some(UserConfig {
                conception_path: Some(PathBuf::from("/from-file")),
            }),
            None,
        )
        .unwrap();
        assert_eq!(got, PathBuf::from("/from-file"));
    }

    #[test]
    fn no_sources_errors_with_unset() {
        let err = resolve_from(None, None, Some(PathBuf::from("/x/settings.yaml"))).unwrap_err();
        assert_eq!(err.settings_path, Some(PathBuf::from("/x/settings.yaml")));
        let msg = err.to_string();
        assert!(msg.contains(CONCEPTION_ENV));
        assert!(msg.contains("/x/settings.yaml"));
    }

    #[test]
    fn user_config_without_conception_path_is_unset() {
        let err = resolve_from(
            None,
            Some(UserConfig {
                conception_path: None,
            }),
            None,
        )
        .unwrap_err();
        // Error path — we don't assert on the message beyond the type.
        let _ = err;
    }
}
