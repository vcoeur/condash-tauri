//! Runtime context + workspace cache for condash.
//!
//! - [`ctx`] — immutable runtime context built from a config.
//!   Threaded through every helper that needs config (base_dir,
//!   workspace, repo structure, …).
//! - [`cache`] — memoize the hot read paths (`collect_items`,
//!   `collect_knowledge`) behind an `RwLock` so reads from route
//!   handlers are safe alongside invalidations driven by the
//!   filesystem watcher.
//! - [`git`] — per-repo HEAD / branch / dirty-count queries, shelled
//!   out to `git` rather than via `libgit2`.
//! - [`search`] — the history-tab search backend.

pub mod cache;
pub mod ctx;
pub mod git;
pub mod search;

pub use cache::{MutationOutput, Tab, WorkspaceCache};
pub use ctx::{OpenWithSlot, RenderCtx, RepoEntry, RepoSection, TerminalPrefs};
pub use git::{collect_git_repos, Checkout, Family, Group, Member};
pub use search::{search_items, Hit, SearchResult};
