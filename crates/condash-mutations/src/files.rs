//! File-level mutations — the write side of the dashboard beyond step
//! rewrites. 1:1 with the `write_note`, `rename_note`, `create_note`,
//! `create_notes_subdir`, `store_uploads`, and `create_item` helpers in
//! `src/condash/mutations.py`.
//!
//! Path validation is the caller's job — each helper here takes already-
//! resolved absolute paths (the route handler calls into
//! `src-tauri/src/paths.rs` first). The only non-absolute inputs are
//! short string fragments (new stem, filename, subdir) which are
//! re-validated inline.

use std::fs;
use std::io::{self, Read};
use std::path::{Path, PathBuf};
use std::sync::LazyLock;
use std::time::UNIX_EPOCH;

use regex::Regex;
use serde::Serialize;

// ---------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------

fn mtime_seconds(meta: &fs::Metadata) -> f64 {
    meta.modified()
        .ok()
        .and_then(|t| t.duration_since(UNIX_EPOCH).ok())
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0)
}

fn path_mtime_seconds(path: &Path) -> io::Result<f64> {
    let meta = fs::metadata(path)?;
    Ok(mtime_seconds(&meta))
}

/// `**Key**: value` — non-regex, fast-path check used by `_VALID_NOTE_FILENAME_RE`
/// consumers. Purely a guard so callers don't accidentally create names
/// like `.` or `..`.
fn is_reserved_filename(name: &str) -> bool {
    matches!(name, "." | "..")
}

// ---------------------------------------------------------------------
// write_note
// ---------------------------------------------------------------------

/// Result of `write_note` — mirrors the `{ok, mtime | reason}` shape of
/// `mutations.write_note`.
#[derive(Debug, Serialize)]
#[serde(untagged)]
pub enum WriteNoteResult {
    Ok {
        ok: bool,
        mtime: f64,
    },
    Err {
        ok: bool,
        reason: String,
        #[serde(skip_serializing_if = "Option::is_none")]
        mtime: Option<f64>,
    },
}

impl WriteNoteResult {
    pub fn is_ok(&self) -> bool {
        matches!(self, WriteNoteResult::Ok { .. })
    }
}

/// Atomically rewrite `full_path` with `content`. Refuses when the
/// on-disk mtime doesn't match `expected_mtime` so a stale editor
/// never silently overwrites out-of-band edits. When `expected_mtime`
/// is `None`, skips the guard.
pub fn write_note(
    full_path: &Path,
    content: &str,
    expected_mtime: Option<f64>,
) -> io::Result<WriteNoteResult> {
    let current_mtime = match path_mtime_seconds(full_path) {
        Ok(m) => m,
        Err(e) if e.kind() == io::ErrorKind::NotFound => {
            return Ok(WriteNoteResult::Err {
                ok: false,
                reason: "file vanished".into(),
                mtime: None,
            });
        }
        Err(e) => return Err(e),
    };

    if let Some(expected) = expected_mtime {
        if (current_mtime - expected).abs() > 1e-6 {
            return Ok(WriteNoteResult::Err {
                ok: false,
                reason: "file changed on disk".into(),
                mtime: Some(current_mtime),
            });
        }
    }

    // Tmp sibling + rename for atomic replace. Python uses
    // `full_path.with_suffix(suffix + ".tmp")` — append, don't replace.
    let tmp = append_suffix(full_path, ".tmp");
    fs::write(&tmp, content)?;
    fs::rename(&tmp, full_path)?;

    Ok(WriteNoteResult::Ok {
        ok: true,
        mtime: path_mtime_seconds(full_path)?,
    })
}

/// Python's `Path.with_suffix(p.suffix + ".tmp")` appends `.tmp` to the
/// existing suffix (so `foo.md` → `foo.md.tmp`). Rust's equivalent takes
/// a couple of lines.
fn append_suffix(path: &Path, extra: &str) -> PathBuf {
    let mut s = path.as_os_str().to_os_string();
    s.push(extra);
    PathBuf::from(s)
}

// ---------------------------------------------------------------------
// rename_note
// ---------------------------------------------------------------------

/// `{ok, path, mtime}` / `{ok: false, reason}` — mirrors
/// `mutations.rename_note`.
#[derive(Debug, Serialize)]
#[serde(untagged)]
pub enum RenameResult {
    Ok { ok: bool, path: String, mtime: f64 },
    Err { ok: bool, reason: String },
}

impl RenameResult {
    pub fn is_ok(&self) -> bool {
        matches!(self, RenameResult::Ok { .. })
    }
}

static VALID_NEW_STEM_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^[\w.-]+$").expect("VALID_NEW_STEM_RE compiles"));

static VALID_NOTE_FILENAME_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^[\w.-]+\.[A-Za-z0-9]+$").expect("VALID_NOTE_FILENAME_RE compiles")
});

/// Rename `full_path` — which must already have been validated as a file
/// under `<item>/notes/` — to `<same_dir>/<new_stem><same_ext>`. Returns
/// the rel_path (relative to `base_dir`) + new mtime on success.
///
/// The caller is responsible for confirming `full_path` is under an
/// item's `notes/` directory (see `paths::is_item_notes_file` +
/// `validate_note_path`). This keeps the helper ctx-free.
pub fn rename_note(full_path: &Path, new_stem: &str, base_dir: &Path) -> io::Result<RenameResult> {
    let new_stem = new_stem.trim();
    if new_stem.is_empty()
        || !VALID_NEW_STEM_RE.is_match(new_stem)
        || is_reserved_filename(new_stem)
    {
        return Ok(RenameResult::Err {
            ok: false,
            reason: "invalid filename".into(),
        });
    }

    let suffix = full_path
        .extension()
        .map(|e| {
            let mut s = String::from(".");
            s.push_str(&e.to_string_lossy());
            s
        })
        .unwrap_or_default();
    let new_filename = format!("{new_stem}{suffix}");
    if !VALID_NOTE_FILENAME_RE.is_match(&new_filename) {
        return Ok(RenameResult::Err {
            ok: false,
            reason: "invalid filename".into(),
        });
    }

    let parent = full_path.parent().ok_or_else(|| {
        io::Error::new(io::ErrorKind::Other, "rename_note: full_path has no parent")
    })?;
    let new_path = parent.join(&new_filename);

    if new_path.exists() {
        let same_file = match (fs::canonicalize(&new_path), fs::canonicalize(full_path)) {
            (Ok(a), Ok(b)) => a == b,
            _ => false,
        };
        if !same_file {
            return Ok(RenameResult::Err {
                ok: false,
                reason: "target already exists".into(),
            });
        }
    }

    if new_path == *full_path {
        let mtime = path_mtime_seconds(full_path)?;
        let rel = rel_under(base_dir, full_path)?;
        return Ok(RenameResult::Ok {
            ok: true,
            path: rel,
            mtime,
        });
    }

    fs::rename(full_path, &new_path)?;
    let mtime = path_mtime_seconds(&new_path)?;
    let rel = rel_under(base_dir, &new_path)?;
    Ok(RenameResult::Ok {
        ok: true,
        path: rel,
        mtime,
    })
}

/// Compute a forward-slash relative path of `child` under `base`. Fails
/// with a descriptive `io::Error` if `child` isn't actually under `base`
/// after canonicalising — should never happen when the caller validates
/// `child` up front, but we surface it rather than silently return
/// something misleading.
fn rel_under(base: &Path, child: &Path) -> io::Result<String> {
    let base_c = fs::canonicalize(base)?;
    let child_c = fs::canonicalize(child)?;
    let rel = child_c
        .strip_prefix(&base_c)
        .map_err(|e| io::Error::new(io::ErrorKind::Other, format!("strip_prefix: {e}")))?;
    Ok(rel
        .components()
        .map(|c| c.as_os_str().to_string_lossy().to_string())
        .collect::<Vec<_>>()
        .join("/"))
}

// ---------------------------------------------------------------------
// create_note
// ---------------------------------------------------------------------

/// `{ok, path, mtime}` / `{ok: false, reason}`.
#[derive(Debug, Serialize)]
#[serde(untagged)]
pub enum CreateNoteResult {
    Ok { ok: bool, path: String, mtime: f64 },
    Err { ok: bool, reason: String },
}

impl CreateNoteResult {
    pub fn is_ok(&self) -> bool {
        matches!(self, CreateNoteResult::Ok { .. })
    }
}

/// Create an empty note file under `<item_dir>/[subdir]/<filename>`.
///
/// `subdir` is relative to the item directory (empty string places the
/// file at the item root, alongside `README.md`). When `subdir` is
/// non-empty, the directory must already exist — `+ folder` is a
/// separate action.
///
/// `target_dir` is the already-resolved, already-sandboxed directory
/// under `item_dir` — typically computed via
/// `paths::resolve_under_item(item_dir, subdir)` in the route handler.
pub fn create_note(
    target_dir: &Path,
    filename: &str,
    base_dir: &Path,
    subdir_was_supplied: bool,
) -> io::Result<CreateNoteResult> {
    if !VALID_NOTE_FILENAME_RE.is_match(filename) {
        return Ok(CreateNoteResult::Err {
            ok: false,
            reason: "invalid filename".into(),
        });
    }
    if subdir_was_supplied && !target_dir.exists() {
        return Ok(CreateNoteResult::Err {
            ok: false,
            reason: "subdirectory does not exist".into(),
        });
    }
    fs::create_dir_all(target_dir)?;
    let target = target_dir.join(filename);
    if target.exists() {
        return Ok(CreateNoteResult::Err {
            ok: false,
            reason: "file exists".into(),
        });
    }
    fs::write(&target, "")?;
    let mtime = path_mtime_seconds(&target)?;
    let rel = rel_under(base_dir, &target)?;
    Ok(CreateNoteResult::Ok {
        ok: true,
        path: rel,
        mtime,
    })
}

// ---------------------------------------------------------------------
// create_notes_subdir
// ---------------------------------------------------------------------

/// `{ok, rel_dir, subdir_key}` / `{ok: false, reason}`.
#[derive(Debug, Serialize)]
#[serde(untagged)]
pub enum CreateSubdirResult {
    Ok {
        ok: bool,
        rel_dir: String,
        subdir_key: String,
    },
    Err {
        ok: bool,
        reason: String,
    },
}

impl CreateSubdirResult {
    pub fn is_ok(&self) -> bool {
        matches!(self, CreateSubdirResult::Ok { .. })
    }
}

/// Create a (possibly nested) directory at `target_dir`. The caller
/// passes the already-resolved absolute path and the normalised
/// `rel_sub` (what the user typed, stripped of leading/trailing slashes).
/// `item_dir_name` is the last segment of the item directory (used to
/// build the `subdir_key` the frontend consumes).
pub fn create_notes_subdir(
    target_dir: &Path,
    rel_sub: &str,
    item_dir_name: &str,
) -> io::Result<CreateSubdirResult> {
    if rel_sub.is_empty() {
        return Ok(CreateSubdirResult::Err {
            ok: false,
            reason: "invalid subdirectory name".into(),
        });
    }
    if target_dir.exists() {
        return Ok(CreateSubdirResult::Err {
            ok: false,
            reason: "exists".into(),
        });
    }
    fs::create_dir_all(target_dir)?;
    Ok(CreateSubdirResult::Ok {
        ok: true,
        rel_dir: rel_sub.into(),
        subdir_key: format!("{item_dir_name}/{rel_sub}"),
    })
}

// ---------------------------------------------------------------------
// store_uploads
// ---------------------------------------------------------------------

static VALID_UPLOAD_FILENAME_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^[\w. \-()]+\.[A-Za-z0-9]+$").expect("VALID_UPLOAD_FILENAME_RE compiles")
});

/// Per-upload rejection record.
#[derive(Debug, Serialize, Clone)]
pub struct UploadRejection {
    pub filename: String,
    pub reason: String,
}

/// `{ok, stored: [rel], rejected: [{filename, reason}]}`.
#[derive(Debug, Serialize)]
pub struct StoreUploadsResult {
    pub ok: bool,
    pub stored: Vec<String>,
    pub rejected: Vec<UploadRejection>,
}

/// Persist a batch of uploads under `target_dir`. Each upload is
/// `(filename, Reader)` — the reader is drained in 64 KB chunks, with
/// the byte-count enforced against `max_bytes_per_file`. Name collisions
/// auto-suffix ` (2)`, ` (3)`, … (same as Finder/Nautilus).
pub fn store_uploads<R: Read>(
    target_dir: &Path,
    base_dir: &Path,
    uploads: Vec<(String, R)>,
    subdir_was_supplied: bool,
    max_bytes_per_file: u64,
) -> io::Result<StoreUploadsResult> {
    if subdir_was_supplied && !target_dir.exists() {
        // Python's `store_uploads` returns an ok=False with reason in
        // this case; the route handler short-circuits to a 400.
        return Ok(StoreUploadsResult {
            ok: false,
            stored: vec![],
            rejected: vec![UploadRejection {
                filename: String::new(),
                reason: "subdirectory does not exist".into(),
            }],
        });
    }
    fs::create_dir_all(target_dir)?;

    let mut stored = Vec::new();
    let mut rejected = Vec::new();

    for (filename, mut stream) in uploads {
        let name = filename.trim().to_string();
        if name.is_empty()
            || !VALID_UPLOAD_FILENAME_RE.is_match(&name)
            || is_reserved_filename(&name)
        {
            rejected.push(UploadRejection {
                filename: name,
                reason: "invalid filename".into(),
            });
            continue;
        }

        let target = disambiguate(&target_dir.join(&name));
        let tmp = append_suffix(&target, ".part");

        let mut written: u64 = 0;
        let mut buf = [0u8; 64 * 1024];
        let mut over = false;
        let mut ioerr: Option<io::Error> = None;
        {
            let mut out = match fs::File::create(&tmp) {
                Ok(f) => f,
                Err(e) => {
                    rejected.push(UploadRejection {
                        filename: name,
                        reason: format!("write failed: {e}"),
                    });
                    continue;
                }
            };
            loop {
                let n = match stream.read(&mut buf) {
                    Ok(n) => n,
                    Err(e) => {
                        ioerr = Some(e);
                        break;
                    }
                };
                if n == 0 {
                    break;
                }
                written += n as u64;
                if written > max_bytes_per_file {
                    over = true;
                    break;
                }
                if let Err(e) = std::io::Write::write_all(&mut out, &buf[..n]) {
                    ioerr = Some(e);
                    break;
                }
            }
        }

        if over {
            let _ = fs::remove_file(&tmp);
            rejected.push(UploadRejection {
                filename: name,
                reason: "exceeds size limit".into(),
            });
            continue;
        }
        if let Some(e) = ioerr {
            let _ = fs::remove_file(&tmp);
            rejected.push(UploadRejection {
                filename: name,
                reason: format!("write failed: {e}"),
            });
            continue;
        }

        if let Err(e) = fs::rename(&tmp, &target) {
            let _ = fs::remove_file(&tmp);
            rejected.push(UploadRejection {
                filename: name,
                reason: format!("write failed: {e}"),
            });
            continue;
        }
        match rel_under(base_dir, &target) {
            Ok(rel) => stored.push(rel),
            Err(e) => rejected.push(UploadRejection {
                filename: name,
                reason: format!("write failed: {e}"),
            }),
        }
    }

    Ok(StoreUploadsResult {
        ok: true,
        stored,
        rejected,
    })
}

fn disambiguate(target: &Path) -> PathBuf {
    if !target.exists() {
        return target.to_path_buf();
    }
    let parent = target.parent().unwrap_or_else(|| Path::new("."));
    let stem = target
        .file_stem()
        .map(|s| s.to_string_lossy().into_owned())
        .unwrap_or_default();
    let suffix = target
        .extension()
        .map(|e| format!(".{}", e.to_string_lossy()))
        .unwrap_or_default();
    let mut n = 2;
    loop {
        let candidate = parent.join(format!("{stem} ({n}){suffix}"));
        if !candidate.exists() {
            return candidate;
        }
        n += 1;
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn item_tree() -> (TempDir, PathBuf, PathBuf) {
        let tmp = TempDir::new().unwrap();
        let base = tmp.path().to_path_buf();
        let item = base.join("projects/2026-04/2026-04-22-demo");
        fs::create_dir_all(item.join("notes")).unwrap();
        let readme = item.join("README.md");
        fs::write(&readme, "# T\n\n**Status**: now\n").unwrap();
        (tmp, base, item)
    }

    // ----- write_note -----

    #[test]
    fn write_note_ok_without_expected_mtime() {
        let (_t, base, item) = item_tree();
        let p = item.join("notes/new.md");
        fs::write(&p, "old\n").unwrap();
        let r = write_note(&p, "new bytes", None).unwrap();
        assert!(r.is_ok(), "{r:?}");
        assert_eq!(fs::read_to_string(&p).unwrap(), "new bytes");
        let _ = base;
    }

    #[test]
    fn write_note_rejects_stale_mtime() {
        let (_t, _base, item) = item_tree();
        let p = item.join("notes/note.md");
        fs::write(&p, "body\n").unwrap();
        // Pass a clearly-wrong expected_mtime.
        let r = write_note(&p, "x", Some(0.0)).unwrap();
        match r {
            WriteNoteResult::Err { reason, mtime, .. } => {
                assert_eq!(reason, "file changed on disk");
                assert!(mtime.is_some());
            }
            other => panic!("expected err, got {other:?}"),
        }
        // File unchanged.
        assert_eq!(fs::read_to_string(&p).unwrap(), "body\n");
    }

    #[test]
    fn write_note_reports_vanished() {
        let (_t, _base, item) = item_tree();
        let p = item.join("notes/ghost.md");
        let r = write_note(&p, "x", None).unwrap();
        match r {
            WriteNoteResult::Err { reason, .. } => assert_eq!(reason, "file vanished"),
            _ => panic!("expected err"),
        }
    }

    // ----- rename_note -----

    #[test]
    fn rename_note_renames_keeping_extension() {
        let (_t, base, item) = item_tree();
        let p = item.join("notes/old.md");
        fs::write(&p, "x").unwrap();
        let r = rename_note(&p, "new", &base).unwrap();
        match r {
            RenameResult::Ok { path, .. } => {
                assert_eq!(path, "projects/2026-04/2026-04-22-demo/notes/new.md");
            }
            _ => panic!("expected ok"),
        }
        assert!(item.join("notes/new.md").exists());
        assert!(!item.join("notes/old.md").exists());
    }

    #[test]
    fn rename_note_rejects_invalid_stem() {
        let (_t, base, item) = item_tree();
        let p = item.join("notes/old.md");
        fs::write(&p, "x").unwrap();
        for bad in ["", "has space", "../x", "."] {
            let r = rename_note(&p, bad, &base).unwrap();
            assert!(!r.is_ok(), "should reject {bad:?}: {r:?}");
        }
    }

    #[test]
    fn rename_note_rejects_existing_target() {
        let (_t, base, item) = item_tree();
        let a = item.join("notes/a.md");
        let b = item.join("notes/b.md");
        fs::write(&a, "A").unwrap();
        fs::write(&b, "B").unwrap();
        let r = rename_note(&a, "b", &base).unwrap();
        assert!(!r.is_ok());
        assert_eq!(fs::read_to_string(&a).unwrap(), "A");
        assert_eq!(fs::read_to_string(&b).unwrap(), "B");
    }

    #[test]
    fn rename_note_same_name_is_ok_noop() {
        let (_t, base, item) = item_tree();
        let p = item.join("notes/same.md");
        fs::write(&p, "x").unwrap();
        let r = rename_note(&p, "same", &base).unwrap();
        assert!(r.is_ok());
    }

    // ----- create_note -----

    #[test]
    fn create_note_at_item_root() {
        let (_t, base, item) = item_tree();
        let r = create_note(&item, "draft.md", &base, false).unwrap();
        match r {
            CreateNoteResult::Ok { path, .. } => {
                assert_eq!(path, "projects/2026-04/2026-04-22-demo/draft.md");
            }
            _ => panic!("expected ok"),
        }
        assert!(item.join("draft.md").exists());
    }

    #[test]
    fn create_note_in_subdir_that_must_exist() {
        let (_t, base, item) = item_tree();
        let sub = item.join("notes");
        let r = create_note(&sub, "n.md", &base, true).unwrap();
        assert!(r.is_ok());
    }

    #[test]
    fn create_note_rejects_missing_subdir() {
        let (_t, base, item) = item_tree();
        let sub = item.join("ghost");
        let r = create_note(&sub, "n.md", &base, true).unwrap();
        assert!(!r.is_ok());
    }

    #[test]
    fn create_note_rejects_existing_file() {
        let (_t, base, item) = item_tree();
        let sub = item.join("notes");
        fs::write(sub.join("dup.md"), "").unwrap();
        let r = create_note(&sub, "dup.md", &base, true).unwrap();
        assert!(!r.is_ok());
    }

    #[test]
    fn create_note_rejects_invalid_filename() {
        let (_t, base, item) = item_tree();
        let r = create_note(&item, "no extension", &base, false).unwrap();
        assert!(!r.is_ok());
    }

    // ----- create_notes_subdir -----

    #[test]
    fn create_notes_subdir_makes_dir() {
        let (_t, _base, item) = item_tree();
        let target = item.join("assets/ui");
        let r = create_notes_subdir(&target, "assets/ui", "2026-04-22-demo").unwrap();
        match r {
            CreateSubdirResult::Ok {
                rel_dir,
                subdir_key,
                ..
            } => {
                assert_eq!(rel_dir, "assets/ui");
                assert_eq!(subdir_key, "2026-04-22-demo/assets/ui");
            }
            _ => panic!("expected ok"),
        }
        assert!(target.is_dir());
    }

    #[test]
    fn create_notes_subdir_refuses_existing() {
        let (_t, _base, item) = item_tree();
        let target = item.join("notes");
        let r = create_notes_subdir(&target, "notes", "2026-04-22-demo").unwrap();
        match r {
            CreateSubdirResult::Err { reason, .. } => assert_eq!(reason, "exists"),
            _ => panic!("expected err"),
        }
    }

    // ----- store_uploads -----

    #[test]
    fn store_uploads_writes_files_and_returns_paths() {
        let (_t, base, item) = item_tree();
        let sub = item.join("notes");
        let uploads: Vec<(String, &[u8])> = vec![
            ("a.txt".into(), b"hello" as &[u8]),
            ("b.txt".into(), b"world" as &[u8]),
        ];
        let res = store_uploads(&sub, &base, uploads, true, 1024 * 1024).unwrap();
        assert!(res.ok);
        assert_eq!(res.stored.len(), 2);
        assert!(res.stored[0].ends_with("/notes/a.txt"));
        assert_eq!(fs::read_to_string(sub.join("a.txt")).unwrap(), "hello");
    }

    #[test]
    fn store_uploads_disambiguates_collisions() {
        let (_t, base, item) = item_tree();
        let sub = item.join("notes");
        fs::write(sub.join("dup.txt"), "old").unwrap();
        let uploads: Vec<(String, &[u8])> = vec![("dup.txt".into(), b"new" as &[u8])];
        let res = store_uploads(&sub, &base, uploads, true, 1024).unwrap();
        assert_eq!(res.stored.len(), 1);
        assert!(res.stored[0].ends_with("/notes/dup (2).txt"));
        assert_eq!(fs::read_to_string(sub.join("dup.txt")).unwrap(), "old");
    }

    #[test]
    fn store_uploads_enforces_size_cap() {
        let (_t, base, item) = item_tree();
        let sub = item.join("notes");
        let big = vec![0u8; 2048];
        let uploads: Vec<(String, &[u8])> = vec![("big.bin".into(), big.as_slice())];
        let res = store_uploads(&sub, &base, uploads, true, 1024).unwrap();
        assert!(res.stored.is_empty());
        assert_eq!(res.rejected.len(), 1);
        assert_eq!(res.rejected[0].reason, "exceeds size limit");
        assert!(!sub.join("big.bin").exists());
    }

    #[test]
    fn store_uploads_rejects_bad_filenames() {
        let (_t, base, item) = item_tree();
        let sub = item.join("notes");
        let uploads: Vec<(String, &[u8])> = vec![
            ("../etc/passwd".into(), b"x" as &[u8]),
            ("no_extension".into(), b"x" as &[u8]),
        ];
        let res = store_uploads(&sub, &base, uploads, true, 1024).unwrap();
        assert!(res.stored.is_empty());
        assert_eq!(res.rejected.len(), 2);
    }

}
