//! Runtime context + workspace cache for condash.
//!
//! Rust port of `src/condash/context.py` + `src/condash/cache.py`.
//! Split into two modules that mirror their Python counterparts:
//!
//! - [`ctx`] — immutable runtime context built from a config. Threaded
//!   through every helper that needs config (base_dir, workspace, repo
//!   structure, etc). Module-globals in Python live here instead.
//! - [`cache`] — memoize the hot read paths (`collect_items`,
//!   `collect_knowledge`) behind an `RwLock` so reads from route
//!   handlers are safe alongside invalidations driven by the filesystem
//!   watcher.

pub mod cache;
pub mod ctx;

pub use cache::{Tab, WorkspaceCache};
pub use ctx::RenderCtx;
