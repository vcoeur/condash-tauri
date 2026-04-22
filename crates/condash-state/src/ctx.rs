//! Immutable runtime context — Rust port of `context.py::RenderCtx`.
//!
//! The Python module carries a dataclass with `base_dir`, `workspace`,
//! `worktrees`, `repo_structure`, `open_with`, `pdf_viewer`, `repo_run`,
//! and `template`. Phase 2 only needs the read-only subset: `base_dir`
//! for the parser, `template` for the dashboard shell. The config-heavy
//! fields (`open_with`, `pdf_viewer`, `repo_run`, `repo_structure`) are
//! stubbed as empty collections and will grow as mutations + openers +
//! runners land in Phases 3–4.

use std::path::PathBuf;

/// One section of the repository explorer tab: a label (e.g. `"Primary"`)
/// with a list of `(repo_name, submodules)` pairs. Matches Python's
/// `list[tuple[str, list[tuple[str, list[str]]]]]` verbatim in shape.
#[derive(Debug, Clone, Default)]
pub struct RepoSection {
    pub label: String,
    pub repos: Vec<RepoEntry>,
}

/// One repo in a section, with the list of submodule names it owns.
#[derive(Debug, Clone, Default)]
pub struct RepoEntry {
    pub name: String,
    pub submodules: Vec<String>,
}

/// Immutable runtime context carried by every helper that needs config.
///
/// Built once per effective config; rebuilt and swapped into the shared
/// app state whenever the config editor posts a new config. Cloning is
/// cheap (Arc-friendly fields) so handlers can take an owned ctx by
/// value without worrying about lifetimes.
#[derive(Debug, Clone, Default)]
pub struct RenderCtx {
    /// Conception tree root. `/nonexistent` when the user has not
    /// configured a path yet — the parser's `is_dir()` short-circuits
    /// and the dashboard renders the setup prompt.
    pub base_dir: PathBuf,
    pub workspace: Option<PathBuf>,
    pub worktrees: Option<PathBuf>,
    pub repo_structure: Vec<RepoSection>,
    /// Dashboard HTML template shipped with the wheel. Loaded once at
    /// ctx-build time so render helpers don't re-read it per request.
    pub template: String,
}

impl RenderCtx {
    /// Bare-minimum context for tests and early-phase wiring — points at
    /// an on-disk conception tree with nothing else configured.
    pub fn with_base_dir<P: Into<PathBuf>>(base_dir: P) -> Self {
        RenderCtx {
            base_dir: base_dir.into(),
            ..Default::default()
        }
    }
}
