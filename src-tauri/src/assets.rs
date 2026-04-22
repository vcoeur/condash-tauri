//! Asset resolution — embedded via `rust-embed` for production builds,
//! with an opt-in on-disk override (`CONDASH_ASSET_DIR`) for development
//! so CSS / HTML / vendor libs can be live-edited without recompiling.
//!
//! The dashboard shell (`dashboard.html`), the bundled dashboard JS
//! (`dist/`), the vendored frontend libraries (`vendor/`), and the
//! favicon all ship baked into the binary by default — Phase 5 step 1 of
//! the packaging scope change (see `notes/packaging.md`). A self-
//! contained binary is the prerequisite for every other packaging step.

use std::borrow::Cow;
use std::path::{Path, PathBuf};

/// Embedded copy of the Python package's `assets/` tree. The path is
/// relative to `src-tauri/Cargo.toml` (rust-embed resolves
/// `CARGO_MANIFEST_DIR` + `folder`). `include = "*"` keeps every file in
/// the tree; we need `dashboard.html`, `favicon.{svg,ico}`, `dist/*`,
/// `vendor/<lib>/*`, and occasionally `src/*` for debug previews.
#[derive(rust_embed::Embed)]
#[folder = "../src/condash/assets/"]
pub struct EmbeddedAssets;

/// Source of asset bytes. Handler code doesn't care which variant it
/// got — it just calls [`AssetSource::load`].
///
/// - `Embedded` — pull from the compile-time tree baked in via
///   `rust-embed`. Default for production / shipped binaries.
/// - `Disk(dir)` — read live from `dir` on disk. Set via the
///   `CONDASH_ASSET_DIR` env var. Handy for iterating on CSS or the
///   dashboard HTML without a rebuild.
#[derive(Clone, Debug)]
pub enum AssetSource {
    Embedded,
    Disk(PathBuf),
}

impl AssetSource {
    /// Look up `rel_path` (forward-slash, no leading slash). Returns the
    /// bytes + a guessed MIME type when found. The MIME comes from
    /// `mime_guess` in both variants so the Disk override matches
    /// production byte-for-byte.
    pub fn load(&self, rel_path: &str) -> Option<(Cow<'static, [u8]>, String)> {
        match self {
            AssetSource::Embedded => {
                let file = EmbeddedAssets::get(rel_path)?;
                let mime = mime_for(rel_path);
                Some((Cow::Owned(file.data.into_owned()), mime))
            }
            AssetSource::Disk(root) => load_from_disk(root, rel_path),
        }
    }

    /// Snapshot of a disk-override root for diagnostics. Returns the
    /// path when this source reads from disk; `None` when embedded.
    pub fn disk_root(&self) -> Option<&Path> {
        match self {
            AssetSource::Disk(p) => Some(p.as_path()),
            AssetSource::Embedded => None,
        }
    }
}

impl Default for AssetSource {
    fn default() -> Self {
        AssetSource::Embedded
    }
}

/// Pick an `AssetSource` based on the `CONDASH_ASSET_DIR` environment
/// variable. Unset / empty means embedded (production); a non-empty
/// value is taken as the on-disk root.
pub fn pick_from_env() -> AssetSource {
    match std::env::var_os("CONDASH_ASSET_DIR") {
        Some(v) if !v.is_empty() => AssetSource::Disk(PathBuf::from(v)),
        _ => AssetSource::Embedded,
    }
}

fn load_from_disk(root: &Path, rel_path: &str) -> Option<(Cow<'static, [u8]>, String)> {
    // Mirror the traversal guard `serve_under` applies: reject empty
    // paths, `\0` bytes, and any segment that's `..` or empty. A
    // legitimate relative path here is already regex-gated by the
    // routing layer, but defense-in-depth is cheap.
    if rel_path.is_empty() || rel_path.contains('\0') {
        return None;
    }
    for part in rel_path.split('/') {
        if part.is_empty() || part == ".." {
            return None;
        }
    }
    let full = root.join(rel_path);
    let canonical = std::fs::canonicalize(&full).ok()?;
    let root_canonical = std::fs::canonicalize(root).ok()?;
    if !canonical.starts_with(&root_canonical) {
        return None;
    }
    let bytes = std::fs::read(&canonical).ok()?;
    let mime = mime_for(rel_path);
    Some((Cow::Owned(bytes), mime))
}

fn mime_for(rel_path: &str) -> String {
    match Path::new(rel_path).extension().and_then(|e| e.to_str()) {
        Some("html") => "text/html; charset=utf-8".into(),
        Some("svg") => "image/svg+xml".into(),
        Some("ico") => "image/vnd.microsoft.icon".into(),
        Some("css") => "text/css; charset=utf-8".into(),
        Some("js") | Some("mjs") => "text/javascript; charset=utf-8".into(),
        Some("json") | Some("map") => "application/json".into(),
        Some("wasm") => "application/wasm".into(),
        Some("woff2") => "font/woff2".into(),
        Some("woff") => "font/woff".into(),
        Some("ttf") => "font/ttf".into(),
        _ => mime_guess::from_path(rel_path)
            .first_or_octet_stream()
            .essence_str()
            .to_string(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn embedded_ships_dashboard_html() {
        let src = AssetSource::Embedded;
        let (bytes, mime) = src.load("dashboard.html").expect("dashboard embedded");
        assert!(!bytes.is_empty());
        assert!(mime.starts_with("text/html"));
        // Sanity: the template has Jinja placeholders the Rust renderer
        // substitutes. They must be present in the embedded copy too.
        let s = std::str::from_utf8(&bytes).expect("utf-8");
        assert!(s.contains("{{CARDS}}") || s.contains("{{ CARDS }}"));
    }

    #[test]
    fn embedded_ships_favicon() {
        let (bytes, mime) = AssetSource::Embedded
            .load("favicon.svg")
            .expect("favicon embedded");
        assert!(!bytes.is_empty());
        assert_eq!(mime, "image/svg+xml");
    }

    #[test]
    fn embedded_returns_none_for_missing() {
        assert!(AssetSource::Embedded.load("does-not-exist.xyz").is_none());
    }

    #[test]
    fn disk_override_rejects_traversal() {
        let tmp = tempfile::TempDir::new().unwrap();
        let src = AssetSource::Disk(tmp.path().to_path_buf());
        assert!(src.load("../etc/passwd").is_none());
        assert!(src.load("a/../b").is_none());
        assert!(src.load("").is_none());
        assert!(src.load("a\0b").is_none());
    }

    #[test]
    fn disk_override_serves_existing_file() {
        let tmp = tempfile::TempDir::new().unwrap();
        std::fs::write(tmp.path().join("dashboard.html"), b"<!doctype html>").unwrap();
        let src = AssetSource::Disk(tmp.path().to_path_buf());
        let (bytes, mime) = src.load("dashboard.html").expect("found");
        assert_eq!(&*bytes, b"<!doctype html>");
        assert!(mime.starts_with("text/html"));
    }

    #[test]
    fn pick_from_env_respects_variable() {
        // Saved state so we don't trample a real env var.
        let prior = std::env::var_os("CONDASH_ASSET_DIR");
        std::env::remove_var("CONDASH_ASSET_DIR");
        match pick_from_env() {
            AssetSource::Embedded => {}
            other => panic!("expected Embedded, got {other:?}"),
        }
        std::env::set_var("CONDASH_ASSET_DIR", "/nowhere");
        match pick_from_env() {
            AssetSource::Disk(p) => assert_eq!(p, PathBuf::from("/nowhere")),
            other => panic!("expected Disk, got {other:?}"),
        }
        // Restore.
        match prior {
            Some(v) => std::env::set_var("CONDASH_ASSET_DIR", v),
            None => std::env::remove_var("CONDASH_ASSET_DIR"),
        }
    }
}
