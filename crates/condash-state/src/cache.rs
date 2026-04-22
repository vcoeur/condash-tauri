//! Filesystem-walk memoization — Rust port of `cache.py::WorkspaceCache`.
//!
//! Without a cache every request re-walks the conception tree: `/`,
//! `/check-updates`, `/fragment`, and `/search-history` all call
//! `collect_items` (which parses every `README.md` under `projects/`)
//! and `collect_knowledge` (which walks `knowledge/` recursively).
//!
//! [`WorkspaceCache`] memoizes the two hot paths behind an `RwLock` so
//! reads from Tauri route handlers are cheap and stay safe alongside
//! invalidations driven by the filesystem watcher. The watcher coarsely
//! routes tab events (`projects` / `knowledge`) to [`invalidate_items`]
//! and [`invalidate_knowledge`] — matching Python's coarse-by-design
//! invalidation scheme.
//!
//! The wikilink cache from Python lives separately in Phase 3 with the
//! render layer; putting it here would force a dependency on a crate
//! that doesn't exist yet.
//!
//! [`invalidate_items`]: WorkspaceCache::invalidate_items
//! [`invalidate_knowledge`]: WorkspaceCache::invalidate_knowledge

use std::sync::{Arc, RwLock};

use condash_parser::{collect_items, collect_knowledge, Item, KnowledgeNode};

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
    items: Option<Arc<Vec<Item>>>,
    /// Separate `loaded` flag so `None` legitimately means "no
    /// knowledge/ directory on disk" (vs. "not yet warmed"). Matches
    /// Python's `_knowledge_loaded` sentinel.
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
    pub fn get_items(&self, ctx: &RenderCtx) -> Arc<Vec<Item>> {
        if let Some(items) = self.inner.read().unwrap().items.clone() {
            return items;
        }
        let fresh = Arc::new(collect_items(&ctx.base_dir));
        let mut w = self.inner.write().unwrap();
        // Another writer may have populated the slot between our read
        // miss and this write — honor whatever's there so two readers
        // that race end up with the same `Arc`.
        w.items.get_or_insert_with(|| fresh.clone()).clone()
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

    /// Flush the items slice — next `get_items` re-walks `projects/`.
    /// Python also flushes its wikilink cache here; we do the same once
    /// wikilinks move into this crate.
    pub fn invalidate_items(&self) {
        self.inner.write().unwrap().items = None;
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
        w.knowledge = None;
    }

    /// Route a filesystem-watcher tab event to the right invalidator.
    /// Matches Python's `on_event` sync subscriber.
    pub fn on_event(&self, tab: Tab) {
        match tab {
            Tab::Projects => self.invalidate_items(),
            Tab::Knowledge => self.invalidate_knowledge(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs::{self, File};
    use std::io::Write;
    use std::path::Path;

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
}
