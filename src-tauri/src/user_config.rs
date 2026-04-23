//! Per-user persistent settings — the per-machine companion to the
//! tree-level `configuration.yml`.
//!
//! Stored at `${XDG_CONFIG_HOME:-~/.config}/condash/settings.yaml`.
//! Schema:
//!
//! ```yaml
//! conception_path: /home/alice/src/vcoeur/conception
//! terminal:
//!   shortcut: Ctrl+T
//!   launcher_command: claude
//! pdf_viewer:
//!   - xdg-open {path}
//!   - evince {path}
//! open_with:
//!   main_ide:
//!     label: Open in main IDE
//!     commands: [idea {path}]
//! ```
//!
//! Every field is optional. `conception_path` tells condash *which*
//! tree to render; the other three carry per-machine overrides for
//! keys that also live in the tree's `configuration.yml`. See the
//! design note in
//! `projects/2026-04/2026-04-23-condash-rust-audit/notes/09-settings-split-schema.md`
//! for rationale and the precedence rule (settings.yaml wins on
//! overlap, field by field).
//!
//! Read order of precedence when resolving the conception tree lives in
//! [`crate::resolve_conception_path`]: env var → this file → first-run
//! prompt (Tauri only) → hard error.

use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct UserConfig {
    /// Absolute path to the conception tree. Optional so callers can
    /// decide whether absence is fatal (first-run picker vs hard error).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub conception_path: Option<PathBuf>,

    /// Per-machine overrides for `terminal.*` fields in the tree's
    /// `configuration.yml`. Missing keys fall through to the tree.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub terminal: Option<TerminalYaml>,

    /// Per-machine PDF-viewer fallback chain. When present and
    /// non-empty, replaces the tree's `pdf_viewer`.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub pdf_viewer: Option<Vec<String>>,

    /// Per-machine "Open with …" slot overrides. Merged per-slot with
    /// the tree's `open_with`.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub open_with: Option<HashMap<String, OpenWithSlotYaml>>,
}

/// One `terminal:` block — fields mirror the tree's `configuration.yml`
/// shape. Missing / empty strings mean "fall through to the tree / to
/// the built-in default".
#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct TerminalYaml {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub shell: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub shortcut: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub screenshot_dir: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub screenshot_paste_shortcut: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub launcher_command: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub move_tab_left_shortcut: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub move_tab_right_shortcut: Option<String>,
}

/// One `open_with.<slot>:` entry. Either field may be absent; a
/// missing `label` falls through to the tree's value.
#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct OpenWithSlotYaml {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub label: Option<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub commands: Vec<String>,
}

/// Resolve the on-disk settings file path. Returns `None` when neither
/// `XDG_CONFIG_HOME` nor `HOME` is set (no sensible location to read
/// or write to).
pub fn settings_file_path() -> Option<PathBuf> {
    let base = match std::env::var_os("XDG_CONFIG_HOME") {
        Some(v) if !v.is_empty() => PathBuf::from(v),
        _ => {
            let home = std::env::var_os("HOME")?;
            PathBuf::from(home).join(".config")
        }
    };
    Some(base.join("condash").join("settings.yaml"))
}

/// Load the on-disk user config from the default settings path.
/// Returns `Ok(None)` when the file doesn't exist; `Err` only on IO /
/// parse failures.
pub fn load() -> Result<Option<UserConfig>> {
    let Some(path) = settings_file_path() else {
        return Ok(None);
    };
    load_from(&path)
}

/// Testable variant of [`load`].
pub fn load_from(path: &Path) -> Result<Option<UserConfig>> {
    if !path.is_file() {
        return Ok(None);
    }
    let raw = fs::read_to_string(path).with_context(|| format!("reading {}", path.display()))?;
    let cfg: UserConfig =
        serde_yaml_ng::from_str(&raw).with_context(|| format!("parsing {}", path.display()))?;
    Ok(Some(cfg))
}

/// Persist `cfg` to the default settings path. Creates the parent
/// directory if needed. Writes atomically (temp file + rename) and sets
/// `0600` permissions on unix.
pub fn save(cfg: &UserConfig) -> Result<PathBuf> {
    let path = settings_file_path()
        .context("neither XDG_CONFIG_HOME nor HOME is set; cannot locate settings.yaml")?;
    save_to(&path, cfg)?;
    Ok(path)
}

/// Testable variant of [`save`]. Writes to `path` with the same atomic
/// semantics.
pub fn save_to(path: &Path, cfg: &UserConfig) -> Result<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).with_context(|| format!("creating {}", parent.display()))?;
    }
    let yaml = serde_yaml_ng::to_string(cfg).context("serialising UserConfig")?;
    let tmp = {
        let mut p = path.to_path_buf();
        let file_name = path
            .file_name()
            .map(|n| n.to_string_lossy().into_owned())
            .unwrap_or_else(|| "settings.yaml".into());
        p.set_file_name(format!(".{file_name}.tmp"));
        p
    };
    fs::write(&tmp, yaml.as_bytes()).with_context(|| format!("writing {}", tmp.display()))?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let _ = fs::set_permissions(&tmp, fs::Permissions::from_mode(0o600));
    }
    fs::rename(&tmp, path)
        .with_context(|| format!("renaming {} -> {}", tmp.display(), path.display()))?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn load_missing_file_returns_none() {
        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("settings.yaml");
        assert!(matches!(load_from(&path), Ok(None)));
    }

    #[test]
    fn roundtrip_preserves_conception_path() {
        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("nested").join("settings.yaml");
        let cfg = UserConfig {
            conception_path: Some(PathBuf::from("/tmp/conception")),
            ..Default::default()
        };
        save_to(&path, &cfg).unwrap();
        let loaded = load_from(&path).unwrap().unwrap();
        assert_eq!(loaded, cfg);
    }

    #[test]
    fn save_sets_0600_on_unix() {
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let tmp = tempfile::tempdir().unwrap();
            let path = tmp.path().join("settings.yaml");
            save_to(&path, &UserConfig::default()).unwrap();
            let mode = fs::metadata(&path).unwrap().permissions().mode() & 0o777;
            assert_eq!(mode, 0o600, "expected 0600, got {mode:o}");
        }
    }

    #[test]
    fn load_rejects_invalid_yaml() {
        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("settings.yaml");
        fs::write(&path, "conception_path: [not, a, path]").unwrap();
        assert!(load_from(&path).is_err());
    }

    #[test]
    fn load_accepts_empty_document() {
        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("settings.yaml");
        fs::write(&path, "{}\n").unwrap();
        let cfg = load_from(&path).unwrap().unwrap();
        assert_eq!(cfg.conception_path, None);
    }
}
