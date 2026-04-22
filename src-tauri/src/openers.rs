//! External-launcher helpers — one place to spawn IDE / file-manager /
//! PDF-viewer / browser processes, detached from the condash lifetime.
//!
//! Port of `src/condash/openers.py` (Python build). Shape: take a
//! shell-template fallback chain, substitute `{path}` (or `{url}`),
//! spawn each in order until one exits 0 within a short window.
//! Spawning is detached via `/bin/sh -c` with all standard streams
//! redirected to `/dev/null`, so condash doesn't hold the child's
//! output buffers and the process outlives the window.

use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

/// Default fallbacks for `POST /open-folder` when no `open_with.folder`
/// slot is configured. Tried in order; first that exits 0 wins.
pub const FOLDER_FALLBACKS: &[&str] = &[
    "xdg-open {path}",
    "gio open {path}",
    "nautilus {path}",
    "dolphin {path}",
    "thunar {path}",
];

/// Default fallbacks for `POST /open-doc` when no `pdf_viewer` chain is
/// configured. Tried in order.
pub const DOC_FALLBACKS: &[&str] = &[
    "xdg-open {path}",
    "gio open {path}",
    "evince {path}",
    "okular {path}",
    "zathura {path}",
];

/// Default fallbacks for `POST /open-external` URLs.
pub const URL_FALLBACKS: &[&str] = &["xdg-open {url}", "gio open {url}"];

/// How long to wait on each candidate before moving on to the next.
/// Long enough for a cold Electron launcher to fork its child, short
/// enough that a no-op wrong-chain iteration doesn't hang the UI.
const ATTEMPT_GRACE: Duration = Duration::from_millis(600);

/// Substitute `{path}` in `template` with `value`. Also supports the
/// `{url}` alias so the URL fallbacks and the path fallbacks share the
/// same substitutor.
pub fn substitute(template: &str, key: &str, value: &str) -> String {
    template
        .replace(&format!("{{{key}}}"), value)
        .replace("{path}", value)
}

/// Try each template in order with `{path}` / `{url}` replaced by
/// `value`. Returns the template that won, or `None` if the whole chain
/// fell through. Spawns detached — the child owns its own session so
/// closing condash doesn't take the IDE down.
pub fn try_chain(templates: &[String], key: &str, value: &str) -> Option<String> {
    for tpl in templates {
        let filled = substitute(tpl, key, value);
        if filled.trim().is_empty() {
            continue;
        }
        match Command::new("sh")
            .arg("-c")
            .arg(&filled)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
        {
            Ok(mut child) => {
                let deadline = Instant::now() + ATTEMPT_GRACE;
                loop {
                    match child.try_wait() {
                        Ok(Some(status)) => {
                            if status.success() {
                                return Some(tpl.clone());
                            }
                            break;
                        }
                        Ok(None) => {
                            if Instant::now() >= deadline {
                                // Still running past the grace window —
                                // assume the GUI launcher forked and
                                // treat as success. `xdg-open` exits
                                // quickly; `idea` forks and lingers.
                                return Some(tpl.clone());
                            }
                            std::thread::sleep(Duration::from_millis(20));
                        }
                        Err(_) => break,
                    }
                }
            }
            Err(_) => continue,
        }
    }
    None
}

/// Convenience wrapper — same as [`try_chain`] but accepts `&[&str]`.
pub fn try_chain_static(templates: &[&str], key: &str, value: &str) -> Option<String> {
    let owned: Vec<String> = templates.iter().map(|s| s.to_string()).collect();
    try_chain(&owned, key, value)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn substitute_replaces_both_path_and_url_aliases() {
        assert_eq!(substitute("xdg-open {path}", "url", "x"), "xdg-open x");
        assert_eq!(substitute("xdg-open {url}", "url", "x"), "xdg-open x");
    }

    #[test]
    fn try_chain_returns_first_successful() {
        let chain = vec!["false".into(), "true".into(), "true".into()];
        let won = try_chain(&chain, "path", "/tmp").expect("one succeeds");
        assert_eq!(won, "true");
    }

    #[test]
    fn try_chain_returns_none_when_all_fail() {
        let chain = vec!["/nonexistent-binary-xyz --arg".into(), "false".into()];
        assert!(try_chain(&chain, "path", "/tmp").is_none());
    }
}
