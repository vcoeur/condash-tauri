//! Path validation for user-supplied paths used by the write-side
//! routes: a `safe_resolve` helper plus regex-gated validators for
//! READMEs, notes, item dirs, and filenames.
//!
//! Every validator follows the same four-step shape:
//!
//! 1. Reject empty / NUL / literal `..` outright.
//! 2. Gate with one or more regexes.
//! 3. Resolve under `base_dir`, refuse anything whose canonical path
//!    escapes it.
//! 4. Optionally require the resolved entry be a file on disk.

use std::path::{Path, PathBuf};
use std::sync::LazyLock;

use regex::Regex;

/// Common item-path prefix — `projects/YYYY-MM/YYYY-MM-DD-<slug>/`.
const VALID_ITEM_PREFIX: &str = r"^projects/\d{4}-\d{2}/\d{4}-\d{2}-\d{2}-[\w.-]+/";

/// `projects/YYYY-MM/YYYY-MM-DD-<slug>/README.md`.
static VALID_README_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(&format!("{VALID_ITEM_PREFIX}README\\.md$")).expect("VALID_README_RE compiles")
});

/// `<item>/<anything>.md`.
static VALID_NOTE_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(&format!(r"{VALID_ITEM_PREFIX}[\w./-]+\.md$")).expect("VALID_NOTE_RE compiles")
});

/// `knowledge/<file>.md`. Matches `knowledge/` at any depth.
static VALID_KNOWLEDGE_NOTE_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^knowledge/(?:[\w.-]+/)*[\w.-]+\.md$").expect("VALID_KNOWLEDGE_NOTE_RE compiles")
});

/// Any file at any depth inside an item directory.
static VALID_ITEM_FILE_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(&format!(r"{VALID_ITEM_PREFIX}[\w./-]+$")).expect("VALID_ITEM_FILE_RE compiles")
});

/// Restricted to files directly under `<item>/notes/` — used by rename
/// (only notes are user-renamable).
pub(crate) static VALID_ITEM_NOTES_FILE_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(&format!(r"{VALID_ITEM_PREFIX}notes/[\w./-]+$"))
        .expect("VALID_ITEM_NOTES_FILE_RE compiles")
});

/// Item directory itself — `projects/YYYY-MM/YYYY-MM-DD-<slug>/`, with
/// or without the trailing slash.
static VALID_ITEM_DIR_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^projects/\d{4}-\d{2}/\d{4}-\d{2}-\d{2}-[\w.-]+/?$")
        .expect("VALID_ITEM_DIR_RE compiles")
});

/// `<name>.<ext>` — validates the target filename of create_note /
/// rename_note.
pub static VALID_NOTE_FILENAME_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^[\w.-]+\.[A-Za-z0-9]+$").expect("VALID_NOTE_FILENAME_RE compiles")
});

/// Bare filename allowed for the rename target's new stem.
pub static VALID_NEW_STEM_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^[\w.-]+$").expect("VALID_NEW_STEM_RE compiles"));

/// Subdirectory path (possibly nested). Used by `resolve_under_item`
/// to reject anything that doesn't look like a sequence of `[\w.-]+`
/// segments.
pub static VALID_SUBDIR_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^[\w.-]+(/[\w.-]+)*$").expect("VALID_SUBDIR_RE compiles"));

/// Upload filename regex — more permissive than the note regex to
/// accept typical Camera/PDF exports (spaces, parentheses).
pub static VALID_UPLOAD_FILENAME_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^[\w. \-()]+\.[A-Za-z0-9]+$").expect("VALID_UPLOAD_FILENAME_RE compiles")
});

/// Low-level: resolve `rel_path` under `base_dir`, rejecting anything
/// outside. `require_file=true` additionally checks that the resolved
/// entry exists as a regular file; `require_file=false` only requires
/// the path to resolve (which on Unix implies existence, since we go
/// through `canonicalize`).
pub fn safe_resolve(
    base: &Path,
    rel_path: &str,
    regexes: &[&Regex],
    require_file: bool,
) -> Option<PathBuf> {
    if rel_path.is_empty() || rel_path.contains('\0') || rel_path.contains("..") {
        return None;
    }
    if !regexes.is_empty() && !regexes.iter().any(|r| r.is_match(rel_path)) {
        return None;
    }
    let candidate = base.join(rel_path);
    let canonical = std::fs::canonicalize(&candidate).ok()?;
    let base_canonical = std::fs::canonicalize(base).ok()?;
    if !canonical.starts_with(&base_canonical) {
        return None;
    }
    if require_file && !canonical.is_file() {
        return None;
    }
    Some(canonical)
}

/// Validate a README path (`projects/YYYY-MM/<slug>/README.md`). The
/// README must resolve to an existing file under `base_dir`. Every
/// step-mutation handler reads the file immediately after, so
/// `require_file=true` is hardcoded.
pub fn validate_readme_path(base_dir: &Path, rel_path: &str) -> Option<PathBuf> {
    safe_resolve(base_dir, rel_path, &[&VALID_README_RE], true)
}

/// Validate a note-like path — item-tree file, `<item>/notes/*.md`, or
/// `knowledge/**/*.md`. The target must resolve to an existing file.
pub fn validate_note_path(base_dir: &Path, rel_path: &str) -> Option<PathBuf> {
    safe_resolve(
        base_dir,
        rel_path,
        &[
            &VALID_NOTE_RE,
            &VALID_KNOWLEDGE_NOTE_RE,
            &VALID_ITEM_FILE_RE,
        ],
        true,
    )
}

/// Validate a project-item folder path (`projects/YYYY-MM/<slug>/`) under
/// `base_dir`. Used by `/open-folder` so the "open folder in file
/// manager" card button resolves against the conception tree (not the
/// workspace/worktrees sandbox).
pub fn validate_item_dir(base_dir: &Path, rel_path: &str) -> Option<PathBuf> {
    let full = safe_resolve(base_dir, rel_path, &[&VALID_ITEM_DIR_RE], false)?;
    if !full.is_dir() {
        return None;
    }
    Some(full)
}

/// Resolve `subdir` (relative to `item_dir`) and verify the result
/// stays inside the item directory. Empty `subdir` resolves to
/// `item_dir` itself. Returns `None` on traversal / regex failure.
pub fn resolve_under_item(item_dir: &Path, subdir: &str) -> Option<PathBuf> {
    let trimmed = subdir.trim().trim_matches('/');
    if trimmed.is_empty() {
        return Some(item_dir.to_path_buf());
    }
    if trimmed.split('/').any(|seg| seg == "..") {
        return None;
    }
    if !VALID_SUBDIR_RE.is_match(trimmed) {
        return None;
    }
    let target = item_dir.join(trimmed);
    // Use `canonicalize` when the target exists, and a literal
    // prefix check when it does not (the target may legitimately not
    // exist yet in the create_note / mkdir flows — the regex + `..`
    // reject above is enough to keep us safely inside).
    if let Ok(canonical_target) = std::fs::canonicalize(&target) {
        let canonical_base = std::fs::canonicalize(item_dir).ok()?;
        if !canonical_target.starts_with(&canonical_base) {
            return None;
        }
        return Some(canonical_target);
    }
    Some(target)
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
        fs::create_dir_all(item.join("notes")).unwrap();
        fs::write(item.join("README.md"), "# demo\n").unwrap();
        fs::write(item.join("notes/first.md"), "hello\n").unwrap();
        fs::create_dir_all(base.join("knowledge/topics")).unwrap();
        fs::write(base.join("knowledge/conventions.md"), "c\n").unwrap();
        fs::write(base.join("knowledge/topics/dev.md"), "d\n").unwrap();
        (dir, base)
    }

    #[test]
    fn accepts_well_formed_readme() {
        let (_tmp, base) = seeded_tree();
        assert!(
            validate_readme_path(&base, "projects/2026-04/2026-04-22-demo/README.md").is_some()
        );
    }

    #[test]
    fn rejects_traversal() {
        let (_tmp, base) = seeded_tree();
        assert!(validate_readme_path(&base, "projects/../etc/passwd").is_none());
        assert!(validate_note_path(&base, "projects/../../etc/passwd").is_none());
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
        assert!(
            validate_readme_path(&base, "projects/2026-04/2026-04-22-ghost/README.md").is_none()
        );
    }

    #[test]
    fn rejects_nul_and_empty() {
        let (_tmp, base) = seeded_tree();
        assert!(validate_readme_path(&base, "").is_none());
        assert!(validate_readme_path(&base, "a\0b").is_none());
    }

    #[test]
    fn accepts_note_under_item_notes_dir() {
        let (_tmp, base) = seeded_tree();
        assert!(
            validate_note_path(&base, "projects/2026-04/2026-04-22-demo/notes/first.md").is_some()
        );
    }

    #[test]
    fn accepts_knowledge_note() {
        let (_tmp, base) = seeded_tree();
        assert!(validate_note_path(&base, "knowledge/conventions.md").is_some());
        assert!(validate_note_path(&base, "knowledge/topics/dev.md").is_some());
    }

    #[test]
    fn valid_item_notes_file_re_gates_rename_source() {
        assert!(
            VALID_ITEM_NOTES_FILE_RE.is_match("projects/2026-04/2026-04-22-demo/notes/first.md")
        );
        assert!(!VALID_ITEM_NOTES_FILE_RE.is_match("projects/2026-04/2026-04-22-demo/README.md"));
        assert!(!VALID_ITEM_NOTES_FILE_RE.is_match("projects/2026-04/2026-04-22-demo/loose.md"));
    }

    #[test]
    fn resolve_under_item_empty_is_item_dir() {
        let (_tmp, base) = seeded_tree();
        let item = base.join("projects/2026-04/2026-04-22-demo");
        assert_eq!(resolve_under_item(&item, ""), Some(item.clone()));
        assert_eq!(resolve_under_item(&item, "   "), Some(item.clone()));
        assert_eq!(resolve_under_item(&item, "/"), Some(item.clone()));
    }

    #[test]
    fn resolve_under_item_nested() {
        let (_tmp, base) = seeded_tree();
        let item = base.join("projects/2026-04/2026-04-22-demo");
        let got = resolve_under_item(&item, "notes").expect("notes exists");
        assert!(got.ends_with("projects/2026-04/2026-04-22-demo/notes"));
    }

    #[test]
    fn resolve_under_item_rejects_traversal() {
        let (_tmp, base) = seeded_tree();
        let item = base.join("projects/2026-04/2026-04-22-demo");
        assert!(resolve_under_item(&item, "..").is_none());
        assert!(resolve_under_item(&item, "notes/..").is_none());
        assert!(resolve_under_item(&item, "../../etc").is_none());
    }

    #[test]
    fn resolve_under_item_allows_nonexistent_nested() {
        let (_tmp, base) = seeded_tree();
        let item = base.join("projects/2026-04/2026-04-22-demo");
        // The target doesn't exist yet — create_notes_subdir uses this
        // code path. Should still resolve, since the regex + ".." reject
        // keep us safe.
        let got = resolve_under_item(&item, "freshly/nested").expect("ok");
        assert!(got.ends_with("projects/2026-04/2026-04-22-demo/freshly/nested"));
    }

    #[test]
    fn valid_new_stem_accepts_reasonable_names() {
        for good in ["report", "report.draft", "report-2", "under_score"] {
            assert!(VALID_NEW_STEM_RE.is_match(good), "want match: {good}");
        }
        for bad in ["", "has space", "a/b", "../x"] {
            assert!(!VALID_NEW_STEM_RE.is_match(bad), "want reject: {bad}");
        }
    }
}
