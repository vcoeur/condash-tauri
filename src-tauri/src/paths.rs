//! Path validation for user-supplied item paths. Mirrors the subset of
//! `src/condash/paths.py` that the write-side step routes need —
//! `_safe_resolve` + `_validate_path`. Same rules:
//!
//! 1. Reject empty / NUL / `..` outright.
//! 2. Gate with a regex that requires the standard
//!    `projects/YYYY-MM/YYYY-MM-DD-slug/README.md` shape.
//! 3. Resolve under `base_dir`, refuse anything whose canonical path
//!    escapes `base_dir`.
//!
//! The step mutations target READMEs that must already exist — so we
//! also require the target to resolve to an on-disk file.

use std::path::{Path, PathBuf};

use once_cell::sync::Lazy;
use regex::Regex;

/// `projects/YYYY-MM/YYYY-MM-DD-<slug>/README.md`. Same regex as
/// `_VALID_PATH_RE` in `paths.py`.
static VALID_README_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"^projects/\d{4}-\d{2}/\d{4}-\d{2}-\d{2}-[\w.-]+/README\.md$")
        .expect("VALID_README_RE compiles")
});

/// Validate `rel_path` under `base_dir`, returning the resolved absolute
/// path if it passes every check. Returns `None` otherwise. Mirrors
/// `paths._validate_path(ctx, rel_path)` — the README must resolve to an
/// existing *file* under `base_dir`.
pub fn validate_readme_path(base_dir: &Path, rel_path: &str) -> Option<PathBuf> {
    if rel_path.is_empty() || rel_path.contains('\0') || rel_path.contains("..") {
        return None;
    }
    if !VALID_README_RE.is_match(rel_path) {
        return None;
    }
    let candidate = base_dir.join(rel_path);
    let canonical = std::fs::canonicalize(&candidate).ok()?;
    let base_canonical = std::fs::canonicalize(base_dir).ok()?;
    if !canonical.starts_with(&base_canonical) {
        return None;
    }
    if !canonical.is_file() {
        return None;
    }
    Some(canonical)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use tempfile::TempDir;

    fn seeded_tree() -> (TempDir, PathBuf) {
        let dir = TempDir::new().unwrap();
        let base = dir.path().to_path_buf();
        let item = base.join("projects/2026-04/2026-04-22-demo");
        fs::create_dir_all(&item).unwrap();
        let readme = item.join("README.md");
        fs::write(&readme, "# demo\n").unwrap();
        (dir, base)
    }

    #[test]
    fn accepts_well_formed_readme() {
        let (_tmp, base) = seeded_tree();
        let full = validate_readme_path(&base, "projects/2026-04/2026-04-22-demo/README.md");
        assert!(full.is_some());
    }

    #[test]
    fn rejects_traversal() {
        let (_tmp, base) = seeded_tree();
        assert!(
            validate_readme_path(&base, "projects/../etc/passwd").is_none(),
            "must reject .."
        );
    }

    #[test]
    fn rejects_wrong_shape() {
        let (_tmp, base) = seeded_tree();
        assert!(validate_readme_path(&base, "README.md").is_none());
        assert!(validate_readme_path(&base, "projects/2026-04/demo/README.md").is_none());
        assert!(validate_readme_path(&base, "notes/some.md").is_none());
    }

    #[test]
    fn rejects_missing_file() {
        let (_tmp, base) = seeded_tree();
        let missing = "projects/2026-04/2026-04-22-ghost/README.md";
        assert!(validate_readme_path(&base, missing).is_none());
    }

    #[test]
    fn rejects_nul_and_empty() {
        let (_tmp, base) = seeded_tree();
        assert!(validate_readme_path(&base, "").is_none());
        assert!(validate_readme_path(&base, "a\0b").is_none());
    }
}
