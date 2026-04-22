//! Strip AppImage-injected environment variables at process start, so
//! they don't leak into child processes condash spawns (PTY sessions,
//! detached launchers, the `sh -c` fork in `server.rs`).
//!
//! Background. The AppImage bundled by `tauri-action` / `linuxdeploy`
//! wraps the stock AppImageKit `AppRun.wrapped` binary. That binary
//! unconditionally `putenv`s:
//!
//!   PYTHONHOME=$APPDIR/usr/
//!   PYTHONPATH=$APPDIR/usr/share/pyshared/:...
//!   PERLLIB=$APPDIR/usr/share/perl5/:...
//!   GSETTINGS_SCHEMA_DIR=$APPDIR/usr/share/glib-2.0/schemas/:...
//!   QT_PLUGIN_PATH=$APPDIR/usr/lib/.../qt{4,5}/plugins/:...
//!   GST_PLUGIN_SYSTEM_PATH[_1_0]=$APPDIR/usr/lib/gstreamer[-1.0]:...
//!   LD_LIBRARY_PATH=$APPDIR/usr/lib/:...:$LD_LIBRARY_PATH
//!   XDG_DATA_DIRS=$APPDIR/usr/share/:$XDG_DATA_DIRS
//!
//! regardless of whether any interpreter / Qt / GStreamer runtime is
//! actually present in the bundle. condash is pure Rust and bundles
//! none of them — the injected paths point at directories that don't
//! exist inside the mount. The consequence is that any Python / Perl /
//! Qt binary a user launches from a condash terminal picks up those
//! bogus hints, goes looking for its stdlib under `$APPDIR/usr/`, and
//! crashes before `main()` (classic "No module named 'encodings'").
//!
//! The fix: as the first thing condash does at startup, drop the
//! leaked entries so every spawned child inherits a clean environment.
//! Non-AppImage runs (`cargo tauri dev`, `.deb`, `.msi`, `.dmg`)
//! don't set `APPDIR`, so this function is a no-op there.
//!
//! See: conception/projects/2026-04/2026-04-22-condash-appimage-env-leak/.

/// Variables that AppImageKit's AppRun overwrites wholesale. Any value
/// pointing inside `$APPDIR` is assumed to be the AppRun's injection
/// and gets removed.
const WHOLESALE: &[&str] = &[
    "PYTHONHOME",
    "PYTHONPATH",
    "PERLLIB",
    "GSETTINGS_SCHEMA_DIR",
    "QT_PLUGIN_PATH",
    "GST_PLUGIN_SYSTEM_PATH",
    "GST_PLUGIN_SYSTEM_PATH_1_0",
];

/// Colon-delimited path-list variables the AppRun prepends its own
/// `$APPDIR`-rooted segments to. We filter those segments out rather
/// than nuking the whole var so the system-native portion survives.
const COLON_LISTS: &[&str] = &["LD_LIBRARY_PATH", "XDG_DATA_DIRS"];

/// AppImage-internal bookkeeping vars. Child processes have no use for
/// them; drop unconditionally.
const APPIMAGE_INTERNAL: &[&str] = &["APPDIR", "APPIMAGE", "APPIMAGE_UUID", "ARGV0", "OWD"];

/// Remove AppImageKit AppRun's env-var injections from the current
/// process environment. Idempotent; safe to call when not running
/// inside an AppImage (it simply does nothing).
///
/// Must be invoked **before** any thread is spawned and before any
/// child process is launched — callers that rely on the sanitized env
/// (tokio runtimes, Tauri setup, `portable_pty::CommandBuilder`,
/// `std::process::Command`) must run after this.
pub fn scrub_appimage_leaks() {
    let Ok(appdir) = std::env::var("APPDIR") else {
        // Not running from an AppImage — nothing to scrub.
        return;
    };
    if appdir.is_empty() {
        return;
    }

    for var in WHOLESALE {
        if let Ok(value) = std::env::var(var) {
            if value_points_into(&value, &appdir) {
                std::env::remove_var(var);
            }
        }
    }

    for var in COLON_LISTS {
        if let Ok(value) = std::env::var(var) {
            let kept: Vec<&str> = value
                .split(':')
                .filter(|seg| !seg.is_empty() && !seg.starts_with(&appdir))
                .collect();
            if kept.is_empty() {
                std::env::remove_var(var);
            } else if kept.len() != value.split(':').filter(|s| !s.is_empty()).count() {
                std::env::set_var(var, kept.join(":"));
            }
        }
    }

    for var in APPIMAGE_INTERNAL {
        std::env::remove_var(var);
    }
}

/// Colon-list-aware "does this var's value start/contain an $APPDIR
/// segment" check. Matches the first segment for wholesale vars
/// (PYTHONHOME is a single path, PYTHONPATH is a list that in practice
/// AppRun always leads with `$APPDIR/...`).
fn value_points_into(value: &str, appdir: &str) -> bool {
    value
        .split(':')
        .any(|seg| !seg.is_empty() && seg.starts_with(appdir))
}

#[cfg(test)]
mod tests {
    //! Env-var tests mutate global process state. cargo runs tests in
    //! parallel by default, so we serialize every test in this module
    //! behind a single mutex — otherwise overlapping mutations of the
    //! shared variables (PYTHONPATH, LD_LIBRARY_PATH, APPDIR) race and
    //! assertions flake.

    use super::*;
    use std::sync::Mutex;

    static ENV_LOCK: Mutex<()> = Mutex::new(());

    fn isolated_appdir(marker: &str) -> String {
        format!("/tmp/.mount_condash-test-{marker}")
    }

    fn scrub_with(appdir: &str) {
        std::env::set_var("APPDIR", appdir);
        scrub_appimage_leaks();
    }

    // Reset every var the tests touch so a previous test's state
    // doesn't bleed into the next, even under the lock.
    fn clean_slate() {
        for var in [
            "APPDIR",
            "APPIMAGE",
            "ARGV0",
            "OWD",
            "PYTHONHOME",
            "PYTHONPATH",
            "PERLLIB",
            "GSETTINGS_SCHEMA_DIR",
            "QT_PLUGIN_PATH",
            "GST_PLUGIN_SYSTEM_PATH",
            "GST_PLUGIN_SYSTEM_PATH_1_0",
            "LD_LIBRARY_PATH",
            "XDG_DATA_DIRS",
        ] {
            std::env::remove_var(var);
        }
    }

    #[test]
    fn no_op_without_appdir() {
        let _g = ENV_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        clean_slate();
        std::env::set_var("PYTHONHOME", "/opt/user-python");
        // APPDIR is unset, so the scrub is a no-op.
        scrub_appimage_leaks();
        assert_eq!(std::env::var("PYTHONHOME").unwrap(), "/opt/user-python");
        clean_slate();
    }

    #[test]
    fn strips_pythonhome_pointing_into_appdir() {
        let _g = ENV_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        clean_slate();
        let appdir = isolated_appdir("pyhome");
        std::env::set_var("PYTHONHOME", format!("{appdir}/usr/"));
        scrub_with(&appdir);
        assert!(std::env::var("PYTHONHOME").is_err());
        clean_slate();
    }

    #[test]
    fn keeps_pythonhome_outside_appdir() {
        let _g = ENV_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        clean_slate();
        let appdir = isolated_appdir("pyhome-keep");
        std::env::set_var("PYTHONHOME", "/opt/python");
        scrub_with(&appdir);
        assert_eq!(std::env::var("PYTHONHOME").unwrap(), "/opt/python");
        clean_slate();
    }

    #[test]
    fn filters_injected_segments_from_xdg_data_dirs() {
        let _g = ENV_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        clean_slate();
        let appdir = isolated_appdir("xdg");
        std::env::set_var(
            "XDG_DATA_DIRS",
            format!("{appdir}/usr/share/:/usr/local/share/:/usr/share/"),
        );
        scrub_with(&appdir);
        assert_eq!(
            std::env::var("XDG_DATA_DIRS").unwrap(),
            "/usr/local/share/:/usr/share/"
        );
        clean_slate();
    }

    #[test]
    fn removes_ld_library_path_when_all_segments_are_appdir() {
        let _g = ENV_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        clean_slate();
        let appdir = isolated_appdir("ld");
        std::env::set_var(
            "LD_LIBRARY_PATH",
            format!("{appdir}/usr/lib/:{appdir}/usr/lib64/"),
        );
        scrub_with(&appdir);
        assert!(std::env::var("LD_LIBRARY_PATH").is_err());
        clean_slate();
    }

    #[test]
    fn drops_appimage_internals() {
        let _g = ENV_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        clean_slate();
        let appdir = isolated_appdir("internals");
        std::env::set_var("APPIMAGE", "/home/alice/Desktop/condash_1.0.8.AppImage");
        std::env::set_var("ARGV0", "condash");
        std::env::set_var("OWD", "/home/alice");
        scrub_with(&appdir);
        assert!(std::env::var("APPDIR").is_err());
        assert!(std::env::var("APPIMAGE").is_err());
        assert!(std::env::var("ARGV0").is_err());
        assert!(std::env::var("OWD").is_err());
        clean_slate();
    }

    #[test]
    fn idempotent_on_second_run() {
        let _g = ENV_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        clean_slate();
        let appdir = isolated_appdir("idem");
        std::env::set_var("PYTHONPATH", format!("{appdir}/usr/share/pyshared/:"));
        scrub_with(&appdir);
        // Second call: APPDIR has been removed, so it's a no-op.
        scrub_appimage_leaks();
        assert!(std::env::var("PYTHONPATH").is_err());
        assert!(std::env::var("APPDIR").is_err());
        clean_slate();
    }
}
