//! Filesystem-walk memoization.
//!
//! Without a cache every request re-walks the conception tree: `/`,
//! `/check-updates`, `/fragment`, and `/search-history` all call
//! `collect_items` (which parses every `README.md` under `projects/`)
//! and `collect_knowledge` (which walks `knowledge/` recursively).
//!
//! [`WorkspaceCache`] memoizes the two hot paths behind an `RwLock` so
//! reads from Tauri route handlers are cheap and stay safe alongside
//! invalidations driven by the filesystem watcher.
//!
//! The items side is keyed by README path: a mutation that touches one
//! item (step toggle, note save) calls [`invalidate_item_at`] to drop
//! just that entry, so the next read re-parses one README instead of
//! the whole tree. The watcher-driven path ([`on_event`]) stays
//! coarse — a `Tab::Projects` event from the filesystem watcher doesn't
//! carry a specific path, so it flushes the whole map.
//!
//! [`invalidate_item_at`]: WorkspaceCache::invalidate_item_at
//! [`on_event`]: WorkspaceCache::on_event

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::{Arc, RwLock};

use condash_parser::{collect_knowledge, parse_readme, Item, KnowledgeNode};

use crate::RenderCtx;

/// Coarse tab identifier the filesystem watcher publishes. Only
/// `Projects` and `Knowledge` matter for the cache — other tabs (code,
/// config, etc.) are watched but don't invalidate parsed-item state.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Tab {
    Projects,
    Knowledge,
}

#[derive(Default)]
struct CacheInner {
    /// Parsed items keyed by absolute README path. `None` means we've
    /// never walked `projects/` — distinguishes "cold" from "walked but
    /// empty".
    items: Option<HashMap<PathBuf, Item>>,
    /// Memoized ordered view of `items`. Built lazily on the first
    /// `get_items` after any invalidation; invalidators clear it so the
    /// next read rebuilds it.
    items_snapshot: Option<Arc<Vec<Item>>>,
    /// Separate `loaded` flag so `None` legitimately means "no
    /// knowledge/ directory on disk" (vs. "not yet warmed").
    knowledge: Option<Arc<Option<KnowledgeNode>>>,
}

/// Memoize `collect_items` + `collect_knowledge` behind an `RwLock`.
///
/// Reads return `Arc`-wrapped snapshots so callers don't hold the lock
/// for the duration of whatever they do with the data. Writes
/// (invalidation + re-warm) are short — they swap the `Arc` pointer and
/// drop the lock before the next reader arrives.
#[derive(Default)]
pub struct WorkspaceCache {
    inner: RwLock<CacheInner>,
}

impl WorkspaceCache {
    pub fn new() -> Self {
        Self::default()
    }

    /// Return the memoized parsed-item list, warming on first access.
    /// The returned `Arc` stays valid across invalidations — the next
    /// `get_items` call will rebuild a fresh one from a new read.
    #[tracing::instrument(skip_all, fields(base_dir = %ctx.base_dir.display()))]
    pub fn get_items(&self, ctx: &RenderCtx) -> Arc<Vec<Item>> {
        if let Some(snap) = self.inner.read().unwrap().items_snapshot.clone() {
            return snap;
        }
        // Walk the tree and rebuild missing entries. Cheap when nothing
        // is missing (snapshot was just cleared, map still populated);
        // pays the full parser cost only on cold start or after a
        // coarse invalidation.
        let readmes = collect_readmes(&ctx.base_dir);
        let mut w = self.inner.write().unwrap();
        let map = w.items.get_or_insert_with(HashMap::new);
        // Prune entries whose README is no longer on disk (handles
        // deletions between invalidations).
        let on_disk: std::collections::HashSet<&PathBuf> = readmes.iter().collect();
        map.retain(|k, _| on_disk.contains(k));

        let mut items: Vec<Item> = Vec::with_capacity(readmes.len());
        for path in &readmes {
            if let Some(cached) = map.get(path) {
                items.push(cached.clone());
                continue;
            }
            if let Some(item) = parse_readme(&ctx.base_dir, path, None) {
                map.insert(path.clone(), item.clone());
                items.push(item);
            }
        }
        let snap = Arc::new(items);
        w.items_snapshot = Some(snap.clone());
        snap
    }

    /// Return the memoized knowledge tree, warming on first access.
    /// The outer `Arc` layer makes the `Option<KnowledgeNode>` cheap to
    /// share; the inner `Option` mirrors Python's "directory missing"
    /// case.
    pub fn get_knowledge(&self, ctx: &RenderCtx) -> Arc<Option<KnowledgeNode>> {
        if let Some(k) = self.inner.read().unwrap().knowledge.clone() {
            return k;
        }
        let fresh = Arc::new(collect_knowledge(&ctx.base_dir));
        let mut w = self.inner.write().unwrap();
        w.knowledge.get_or_insert_with(|| fresh.clone()).clone()
    }

    /// Flush every cached item — next `get_items` re-parses every
    /// README. Used by full-rescan endpoints and by the watcher when
    /// the event carries no specific path.
    pub fn invalidate_items(&self) {
        let mut w = self.inner.write().unwrap();
        w.items = None;
        w.items_snapshot = None;
    }

    /// Drop the single item whose folder contains `path` and clear the
    /// snapshot. Pass the absolute path to any file under the item —
    /// the README itself (`.../README.md`), a note
    /// (`.../notes/x.md`), etc. Falls back to a full invalidation when
    /// no item-dir is found above `path`, which is the safe default.
    pub fn invalidate_item_at(&self, path: &Path) {
        let Some(readme) = readme_for(path) else {
            self.invalidate_items();
            return;
        };
        let mut w = self.inner.write().unwrap();
        if let Some(map) = w.items.as_mut() {
            map.remove(&readme);
        }
        w.items_snapshot = None;
    }

    /// Flush the knowledge tree slice.
    pub fn invalidate_knowledge(&self) {
        self.inner.write().unwrap().knowledge = None;
    }

    /// Flush every cached slice — used when `ctx` itself is swapped
    /// (e.g. after a config edit that moves `base_dir`).
    pub fn invalidate_all(&self) {
        let mut w = self.inner.write().unwrap();
        w.items = None;
        w.items_snapshot = None;
        w.knowledge = None;
    }

    /// Route a filesystem-watcher tab event to the right invalidator.
    /// The watcher only publishes a coarse tab id, so this stays coarse
    /// too — per-item invalidation is reserved for code paths that
    /// know exactly which item just changed.
    pub fn on_event(&self, tab: Tab) {
        match tab {
            Tab::Projects => self.invalidate_items(),
            Tab::Knowledge => self.invalidate_knowledge(),
        }
    }
}

/// Walk `<base>/projects/*/*/README.md` into a sorted `Vec<PathBuf>`.
/// Matches the two-level layout the parser itself walks.
fn collect_readmes(base_dir: &Path) -> Vec<PathBuf> {
    let projects = base_dir.join("projects");
    let Ok(months) = std::fs::read_dir(&projects) else {
        return Vec::new();
    };
    let mut out: Vec<PathBuf> = Vec::new();
    for month in months.flatten() {
        let month_path = month.path();
        if !month_path.is_dir() {
            continue;
        }
        let Ok(items) = std::fs::read_dir(&month_path) else {
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
    out.sort();
    out
}

/// Walk `path` upwards looking for an ancestor that holds a `README.md`
/// whose grandparent is a `projects/<month>/` directory. Returns the
/// README path when found — the cache keys items by this path.
fn readme_for(path: &Path) -> Option<PathBuf> {
    for ancestor in path.ancestors() {
        let dir = if ancestor.file_name().and_then(|n| n.to_str()) == Some("README.md") {
            ancestor.parent()?
        } else {
            ancestor
        };
        let readme = dir.join("README.md");
        if !readme.is_file() {
            continue;
        }
        let Some(month) = dir.parent() else { continue };
        let Some(projects) = month.parent() else {
            continue;
        };
        if projects.file_name().and_then(|n| n.to_str()) == Some("projects") {
            return Some(readme);
        }
    }
    None
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

    const SIMPLE_README: &str = "# Title\n\n**Status**: now\n\n## Steps\n\n- [x] one\n";

    fn seed(base: &Path) {
        write(
            &base.join("projects/2026-04/2026-04-22-foo/README.md"),
            SIMPLE_README,
        );
        write(&base.join("knowledge/index.md"), "# Knowledge\n\nroot.\n");
    }

    #[test]
    fn warms_on_first_access() {
        let td = tempfile::tempdir().unwrap();
        seed(td.path());
        let ctx = RenderCtx::with_base_dir(td.path());
        let cache = WorkspaceCache::new();

        let items = cache.get_items(&ctx);
        assert_eq!(items.len(), 1);
        let knowledge = cache.get_knowledge(&ctx);
        assert!(knowledge.is_some());
    }

    #[test]
    fn second_read_returns_the_same_arc() {
        let td = tempfile::tempdir().unwrap();
        seed(td.path());
        let ctx = RenderCtx::with_base_dir(td.path());
        let cache = WorkspaceCache::new();

        let a = cache.get_items(&ctx);
        let b = cache.get_items(&ctx);
        assert!(Arc::ptr_eq(&a, &b), "cache should hand back the same Arc");
    }

    #[test]
    fn invalidate_items_rewalks_only_items() {
        let td = tempfile::tempdir().unwrap();
        seed(td.path());
        let ctx = RenderCtx::with_base_dir(td.path());
        let cache = WorkspaceCache::new();

        let items_a = cache.get_items(&ctx);
        let knowledge_a = cache.get_knowledge(&ctx);
        cache.invalidate_items();
        let items_b = cache.get_items(&ctx);
        let knowledge_b = cache.get_knowledge(&ctx);

        assert!(
            !Arc::ptr_eq(&items_a, &items_b),
            "items Arc should be fresh"
        );
        assert!(
            Arc::ptr_eq(&knowledge_a, &knowledge_b),
            "knowledge Arc should survive items invalidation"
        );
    }

    #[test]
    fn invalidate_knowledge_rewalks_only_knowledge() {
        let td = tempfile::tempdir().unwrap();
        seed(td.path());
        let ctx = RenderCtx::with_base_dir(td.path());
        let cache = WorkspaceCache::new();

        let items_a = cache.get_items(&ctx);
        let knowledge_a = cache.get_knowledge(&ctx);
        cache.invalidate_knowledge();
        let items_b = cache.get_items(&ctx);
        let knowledge_b = cache.get_knowledge(&ctx);

        assert!(Arc::ptr_eq(&items_a, &items_b));
        assert!(!Arc::ptr_eq(&knowledge_a, &knowledge_b));
    }

    #[test]
    fn cache_reflects_filesystem_changes_after_invalidate() {
        let td = tempfile::tempdir().unwrap();
        seed(td.path());
        let ctx = RenderCtx::with_base_dir(td.path());
        let cache = WorkspaceCache::new();

        assert_eq!(cache.get_items(&ctx).len(), 1);
        write(
            &td.path().join("projects/2026-04/2026-04-22-bar/README.md"),
            SIMPLE_README,
        );
        // Without invalidation the cache still shows the old view.
        assert_eq!(cache.get_items(&ctx).len(), 1);
        cache.invalidate_items();
        assert_eq!(cache.get_items(&ctx).len(), 2);
    }

    #[test]
    fn on_event_routes_tabs_to_the_right_invalidator() {
        let td = tempfile::tempdir().unwrap();
        seed(td.path());
        let ctx = RenderCtx::with_base_dir(td.path());
        let cache = WorkspaceCache::new();

        let items_a = cache.get_items(&ctx);
        let knowledge_a = cache.get_knowledge(&ctx);
        cache.on_event(Tab::Projects);
        assert!(!Arc::ptr_eq(&cache.get_items(&ctx), &items_a));
        let knowledge_b = cache.get_knowledge(&ctx);
        assert!(Arc::ptr_eq(&knowledge_a, &knowledge_b));
        cache.on_event(Tab::Knowledge);
        assert!(!Arc::ptr_eq(&cache.get_knowledge(&ctx), &knowledge_a));
    }

    #[test]
    fn knowledge_absent_is_cached_as_none() {
        let td = tempfile::tempdir().unwrap();
        // No knowledge/ directory.
        let ctx = RenderCtx::with_base_dir(td.path());
        let cache = WorkspaceCache::new();
        let a = cache.get_knowledge(&ctx);
        assert!(a.is_none());
        // Second call returns the same Arc, proving it's memoized (not
        // re-walked every time when the directory is absent).
        let b = cache.get_knowledge(&ctx);
        assert!(Arc::ptr_eq(&a, &b));
    }

    #[test]
    fn invalidate_all_flushes_both_slices() {
        let td = tempfile::tempdir().unwrap();
        seed(td.path());
        let ctx = RenderCtx::with_base_dir(td.path());
        let cache = WorkspaceCache::new();

        let items_a = cache.get_items(&ctx);
        let knowledge_a = cache.get_knowledge(&ctx);
        cache.invalidate_all();
        assert!(!Arc::ptr_eq(&cache.get_items(&ctx), &items_a));
        assert!(!Arc::ptr_eq(&cache.get_knowledge(&ctx), &knowledge_a));
    }

    #[test]
    fn invalidate_item_at_drops_only_one_entry() {
        let td = tempfile::tempdir().unwrap();
        let base = td.path();
        let foo = base.join("projects/2026-04/2026-04-22-foo/README.md");
        let bar = base.join("projects/2026-04/2026-04-22-bar/README.md");
        write(&foo, SIMPLE_README);
        write(&bar, SIMPLE_README);
        let ctx = RenderCtx::with_base_dir(base);
        let cache = WorkspaceCache::new();

        // Warm the cache so both items are parsed and memoized.
        assert_eq!(cache.get_items(&ctx).len(), 2);
        let snap_a = cache.get_items(&ctx);

        cache.invalidate_item_at(&foo);
        let snap_b = cache.get_items(&ctx);
        // Snapshot rebuilt…
        assert!(!Arc::ptr_eq(&snap_a, &snap_b));
        // …and `bar`'s map entry must have been preserved across the
        // surgical invalidation (otherwise we've regressed to coarse).
        let guard = cache.inner.read().unwrap();
        let map = guard.items.as_ref().unwrap();
        assert!(map.contains_key(&bar));
        assert!(map.contains_key(&foo)); // re-parsed by the rebuild
    }

    #[test]
    fn invalidate_item_at_accepts_a_note_path() {
        let td = tempfile::tempdir().unwrap();
        let base = td.path();
        let readme = base.join("projects/2026-04/2026-04-22-foo/README.md");
        let note = base.join("projects/2026-04/2026-04-22-foo/notes/a.md");
        write(&readme, SIMPLE_README);
        write(&note, "body\n");
        let ctx = RenderCtx::with_base_dir(base);
        let cache = WorkspaceCache::new();

        assert_eq!(cache.get_items(&ctx).len(), 1);
        cache.invalidate_item_at(&note);
        // Map should have dropped the one entry; next read re-parses it.
        let snap_b = cache.get_items(&ctx);
        assert_eq!(snap_b.len(), 1);
    }

    #[test]
    fn invalidate_item_at_outside_projects_falls_back_to_full_flush() {
        let td = tempfile::tempdir().unwrap();
        seed(td.path());
        let ctx = RenderCtx::with_base_dir(td.path());
        let cache = WorkspaceCache::new();

        let snap_a = cache.get_items(&ctx);
        cache.invalidate_item_at(&td.path().join("some-random-file.txt"));
        let snap_b = cache.get_items(&ctx);
        assert!(!Arc::ptr_eq(&snap_a, &snap_b));
    }
}
