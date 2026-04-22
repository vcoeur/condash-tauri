//! Item files-tree — `files` field on a parsed item README.
//!
//! Rust port of `_list_item_tree` + `_flatten_tree_paths` in
//! `src/condash/parser.py`. Filesystem-walking, unlike the rest of the
//! crate, so tests exercise it against `tempfile`-built fixtures.

use std::fs;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

use crate::note_kind::note_kind;

/// One leaf file inside an item's tree. Mirrors the Python dict shape:
/// `{name, path, kind}` where `path` is relative to `ctx.base_dir`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct FileEntry {
    pub name: String,
    pub path: String,
    pub kind: String,
}

/// One subdirectory group. Mirrors `{rel_dir, label, files, groups}`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct GroupEntry {
    pub rel_dir: String,
    pub label: String,
    pub files: Vec<FileEntry>,
    pub groups: Vec<GroupEntry>,
}

/// The two-key root returned by `_list_item_tree` — `{files, groups}`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct ItemTree {
    pub files: Vec<FileEntry>,
    pub groups: Vec<GroupEntry>,
}

const DEFAULT_MAX_DEPTH: usize = 3;

/// Recursive tree of files under `item_dir`, grouped per subdirectory.
///
/// `item_dir` is the item folder on disk. `base_dir` is the conception
/// root — used to render each file's `path` relative to it. Hidden
/// entries (`.…`) and the item's top-level `README.md` are skipped.
/// Empty subdirectories are kept so a freshly-created folder shows up
/// immediately as an empty group. Walks up to `max_depth` levels
/// (default 3, matching Python's signature).
pub fn list_item_tree(base_dir: &Path, item_dir: &Path) -> ItemTree {
    list_item_tree_with_depth(base_dir, item_dir, DEFAULT_MAX_DEPTH)
}

pub fn list_item_tree_with_depth(base_dir: &Path, item_dir: &Path, max_depth: usize) -> ItemTree {
    if !item_dir.is_dir() {
        return ItemTree::default();
    }
    walk(base_dir, item_dir, item_dir, 1, max_depth)
}

fn walk(
    base_dir: &Path,
    item_dir: &Path,
    current: &Path,
    depth: usize,
    max_depth: usize,
) -> ItemTree {
    let mut files: Vec<FileEntry> = Vec::new();
    let mut groups: Vec<GroupEntry> = Vec::new();

    let entries: Vec<PathBuf> = match fs::read_dir(current) {
        Ok(iter) => {
            let mut v: Vec<PathBuf> = iter.flatten().map(|e| e.path()).collect();
            v.sort();
            v
        }
        Err(_) => return ItemTree::default(),
    };

    for entry in entries {
        let name = match entry.file_name().and_then(|n| n.to_str()) {
            Some(n) => n.to_string(),
            None => continue,
        };
        if name.starts_with('.') {
            continue;
        }
        let ft = match fs::metadata(&entry) {
            Ok(m) => m.file_type(),
            Err(_) => continue,
        };
        if ft.is_dir() {
            if depth >= max_depth {
                continue;
            }
            let child = walk(base_dir, item_dir, &entry, depth + 1, max_depth);
            let rel_dir = rel_to(item_dir, &entry);
            groups.push(GroupEntry {
                rel_dir,
                label: name,
                files: child.files,
                groups: child.groups,
            });
            continue;
        }
        if !ft.is_file() {
            continue;
        }
        if depth == 1 && name == "README.md" {
            continue;
        }
        files.push(FileEntry {
            name: name.clone(),
            path: rel_to(base_dir, &entry),
            kind: note_kind(&entry).to_string(),
        });
    }

    ItemTree { files, groups }
}

/// `path` relative to `base`, rendered with forward slashes (matching
/// Python's `str(PosixPath)` on Linux).
fn rel_to(base: &Path, path: &Path) -> String {
    path.strip_prefix(base)
        .map(|r| r.to_string_lossy().replace('\\', "/"))
        .unwrap_or_else(|_| path.to_string_lossy().into_owned())
}

/// Flatten a tree to its file paths in depth-first order. Mirrors
/// Python's `_flatten_tree_paths` — used by the fingerprint helpers.
pub fn flatten_tree_paths(tree: &ItemTree) -> Vec<String> {
    let mut out: Vec<String> = tree.files.iter().map(|f| f.path.clone()).collect();
    for g in &tree.groups {
        flatten_group(g, &mut out);
    }
    out
}

fn flatten_group(g: &GroupEntry, out: &mut Vec<String>) {
    for f in &g.files {
        out.push(f.path.clone());
    }
    for sub in &g.groups {
        flatten_group(sub, out);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs::{self, File};
    use std::io::Write;

    fn touch(p: &Path) {
        if let Some(parent) = p.parent() {
            fs::create_dir_all(parent).unwrap();
        }
        File::create(p).unwrap().write_all(b"").unwrap();
    }

    fn sandbox() -> tempfile::TempDir {
        tempfile::tempdir().unwrap()
    }

    #[test]
    fn missing_dir_returns_empty_tree() {
        let td = sandbox();
        let tree = list_item_tree(td.path(), &td.path().join("nope"));
        assert_eq!(tree.files.len(), 0);
        assert_eq!(tree.groups.len(), 0);
    }

    #[test]
    fn skips_readme_at_top_level_only() {
        let td = sandbox();
        let item = td.path().join("projects/2026-04/2026-04-21-x");
        touch(&item.join("README.md"));
        touch(&item.join("notes.md"));
        touch(&item.join("sub/README.md"));

        let tree = list_item_tree(td.path(), &item);
        let names: Vec<_> = tree.files.iter().map(|f| f.name.clone()).collect();
        assert_eq!(names, vec!["notes.md"]);

        let sub = tree
            .groups
            .iter()
            .find(|g| g.label == "sub")
            .expect("sub group");
        let sub_names: Vec<_> = sub.files.iter().map(|f| f.name.clone()).collect();
        // A README.md in a subfolder is a regular file, not the item root.
        assert_eq!(sub_names, vec!["README.md"]);
    }

    #[test]
    fn skips_hidden_entries() {
        let td = sandbox();
        let item = td.path().join("item");
        touch(&item.join(".git/config"));
        touch(&item.join(".DS_Store"));
        touch(&item.join("keep.txt"));

        let tree = list_item_tree(td.path(), &item);
        let names: Vec<_> = tree.files.iter().map(|f| f.name.clone()).collect();
        assert_eq!(names, vec!["keep.txt"]);
        assert!(tree.groups.is_empty());
    }

    #[test]
    fn respects_max_depth() {
        let td = sandbox();
        let item = td.path().join("item");
        touch(&item.join("a/b/c/deep.txt"));

        let tree = list_item_tree_with_depth(td.path(), &item, 2);
        // With max_depth=2, the recursive walker enters `a/` (depth 1 → 2)
        // but skips `b/` entirely (`depth >= max_depth`), matching Python's
        // `if depth >= max_depth: continue`.
        let a = &tree.groups[0];
        assert_eq!(a.label, "a");
        assert!(a.groups.is_empty());
        assert!(a.files.is_empty());
    }

    #[test]
    fn paths_relative_to_base_dir() {
        let td = sandbox();
        let item = td.path().join("projects/2026-04/item-slug");
        touch(&item.join("notes/a.md"));

        let tree = list_item_tree(td.path(), &item);
        let notes = &tree.groups[0];
        assert_eq!(notes.files[0].path, "projects/2026-04/item-slug/notes/a.md");
        assert_eq!(notes.rel_dir, "notes");
    }

    #[test]
    fn entries_sorted_lexicographically() {
        let td = sandbox();
        let item = td.path().join("item");
        for n in ["z.txt", "a.txt", "m.txt"] {
            touch(&item.join(n));
        }
        let tree = list_item_tree(td.path(), &item);
        let names: Vec<_> = tree.files.iter().map(|f| f.name.clone()).collect();
        assert_eq!(names, vec!["a.txt", "m.txt", "z.txt"]);
    }

    #[test]
    fn flatten_tree_paths_depth_first() {
        let td = sandbox();
        let item = td.path().join("item");
        touch(&item.join("a.txt"));
        touch(&item.join("sub/b.txt"));
        touch(&item.join("sub/nested/c.txt"));

        let tree = list_item_tree(td.path(), &item);
        let paths = flatten_tree_paths(&tree);
        assert_eq!(
            paths,
            vec!["item/a.txt", "item/sub/b.txt", "item/sub/nested/c.txt",]
        );
    }

    #[test]
    fn empty_subdir_kept_as_empty_group() {
        let td = sandbox();
        let item = td.path().join("item");
        fs::create_dir_all(item.join("empty-dir")).unwrap();
        touch(&item.join("a.txt"));

        let tree = list_item_tree(td.path(), &item);
        let empty = tree.groups.iter().find(|g| g.label == "empty-dir").unwrap();
        assert!(empty.files.is_empty());
        assert!(empty.groups.is_empty());
    }
}
