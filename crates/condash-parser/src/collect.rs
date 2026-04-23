//! Disk-reading wrappers around `parse_readme_content` and
//! `list_item_tree` — glue the pure parse step to the filesystem.

use std::fs;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

use crate::readme::{parse_readme_content, ItemReadme};
use crate::tree::{list_item_tree, ItemTree};

/// A parsed README combined with its files-tree.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Item {
    #[serde(flatten)]
    pub readme: ItemReadme,
    pub files: ItemTree,
}

/// Read one README off disk and assemble the `Item`. Returns `None`
/// on read / UTF-8 failures — the collector silently skips unreadable
/// items so one malformed README doesn't fail the whole `/` render.
pub fn parse_readme(
    base_dir: &Path,
    readme_path: &Path,
    fallback_kind: Option<&str>,
) -> Option<Item> {
    let content = match fs::read_to_string(readme_path) {
        Ok(s) => s,
        Err(_) => return None,
    };

    let parent = readme_path.parent()?;
    let slug = parent.file_name().and_then(|n| n.to_str())?.to_string();
    let rel_path = rel_to(base_dir, readme_path);
    let item_dir = rel_to(base_dir, parent);

    let readme = parse_readme_content(&content, &slug, &rel_path, &item_dir, fallback_kind)?;
    let files = list_item_tree(base_dir, parent);
    Some(Item { readme, files })
}

/// Find and parse every item README under `<base_dir>/projects/`.
/// Walks the `*/*/README.md` glob in sorted order so the output is
/// deterministic; items that fail to parse are skipped silently.
pub fn collect_items(base_dir: &Path) -> Vec<Item> {
    let projects = base_dir.join("projects");
    if !projects.is_dir() {
        return Vec::new();
    }

    let mut readmes = collect_readmes(&projects);
    readmes.sort();

    readmes
        .into_iter()
        .filter_map(|p| parse_readme(base_dir, &p, None))
        .collect()
}

/// Walk `projects/*/*/README.md` — exactly two levels of subdirectory
/// (month then slug), matching the on-disk layout.
fn collect_readmes(projects: &Path) -> Vec<PathBuf> {
    let mut out: Vec<PathBuf> = Vec::new();
    let Ok(months) = fs::read_dir(projects) else {
        return out;
    };
    for month in months.flatten() {
        let month_path = month.path();
        if !month_path.is_dir() {
            continue;
        }
        let Ok(items) = fs::read_dir(&month_path) else {
            continue;
        };
        for item in items.flatten() {
            let item_path = item.path();
            if !item_path.is_dir() {
                continue;
            }
            let readme = item_path.join("README.md");
            if readme.is_file() {
                out.push(readme);
            }
        }
    }
    out
}

fn rel_to(base: &Path, path: &Path) -> String {
    path.strip_prefix(base)
        .map(|r| r.to_string_lossy().replace('\\', "/"))
        .unwrap_or_else(|_| path.to_string_lossy().into_owned())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs::{self, File};
    use std::io::Write;

    fn write(p: &Path, contents: &str) {
        if let Some(parent) = p.parent() {
            fs::create_dir_all(parent).unwrap();
        }
        File::create(p)
            .unwrap()
            .write_all(contents.as_bytes())
            .unwrap();
    }

    const SIMPLE_README: &str = "# Foo

**Date**: 2026-04-22
**Kind**: project
**Status**: now

## Steps

- [x] One
- [ ] Two
";

    #[test]
    fn parse_readme_reads_and_walks_files() {
        let td = tempfile::tempdir().unwrap();
        let base = td.path();
        let item = base.join("projects/2026-04/2026-04-22-foo");
        write(&item.join("README.md"), SIMPLE_README);
        write(&item.join("notes/a.md"), "body\n");

        let item_out = parse_readme(base, &item.join("README.md"), None).unwrap();
        assert_eq!(item_out.readme.slug, "2026-04-22-foo");
        assert_eq!(item_out.readme.priority, "now");
        assert_eq!(
            item_out.readme.path,
            "projects/2026-04/2026-04-22-foo/README.md"
        );
        // README.md at the item root is excluded from the tree.
        assert!(item_out.files.files.is_empty());
        assert_eq!(item_out.files.groups[0].label, "notes");
        assert_eq!(item_out.files.groups[0].files[0].name, "a.md");
    }

    #[test]
    fn parse_readme_returns_none_on_missing_file() {
        let td = tempfile::tempdir().unwrap();
        let item = td.path().join("projects/2026-04/slug/README.md");
        assert!(parse_readme(td.path(), &item, None).is_none());
    }

    #[test]
    fn collect_items_empty_when_no_projects_dir() {
        let td = tempfile::tempdir().unwrap();
        assert!(collect_items(td.path()).is_empty());
    }

    #[test]
    fn collect_items_walks_glob_and_sorts() {
        let td = tempfile::tempdir().unwrap();
        let base = td.path();
        write(
            &base.join("projects/2026-04/2026-04-01-alpha/README.md"),
            SIMPLE_README,
        );
        write(
            &base.join("projects/2026-04/2026-04-22-zeta/README.md"),
            SIMPLE_README,
        );
        write(
            &base.join("projects/2026-03/2026-03-15-beta/README.md"),
            SIMPLE_README,
        );

        let items = collect_items(base);
        let slugs: Vec<_> = items.iter().map(|i| i.readme.slug.clone()).collect();
        // Sorted by full path: 2026-03 month sorts before 2026-04.
        assert_eq!(
            slugs,
            vec!["2026-03-15-beta", "2026-04-01-alpha", "2026-04-22-zeta",]
        );
    }

    #[test]
    fn collect_items_skips_folders_without_readme() {
        let td = tempfile::tempdir().unwrap();
        let base = td.path();
        write(
            &base.join("projects/2026-04/with-readme/README.md"),
            SIMPLE_README,
        );
        fs::create_dir_all(base.join("projects/2026-04/no-readme")).unwrap();

        let items = collect_items(base);
        assert_eq!(items.len(), 1);
        assert_eq!(items[0].readme.slug, "with-readme");
    }
}
