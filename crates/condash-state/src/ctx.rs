//! Immutable runtime context — Rust port of `context.py::RenderCtx`.
//!
//! The Python module carries a dataclass with `base_dir`, `workspace`,
//! `worktrees`, `repo_structure`, `open_with`, `pdf_viewer`, `repo_run`,
//! and `template`. Phase 2 only needs the read-only subset: `base_dir`
//! for the parser, `template` for the dashboard shell. The config-heavy
//! fields (`open_with`, `pdf_viewer`, `repo_run`, `repo_structure`) are
//! stubbed as empty collections and will grow as mutations + openers +
//! runners land in Phases 3–4.

use std::collections::HashMap;
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

/// One "Open with …" slot config entry. Mirrors Python's
/// `OpenWithSlot`: the user-visible `label` drives rendering, and the
/// `commands` fallback chain is tried in order by the openers layer.
/// Each command is a shell template with `{path}` substitution — the
/// first that exits 0 wins.
#[derive(Debug, Clone, Default)]
pub struct OpenWithSlot {
    pub label: String,
    pub commands: Vec<String>,
}

/// Embedded-terminal preferences. Carries the Python
/// `TerminalConfig` fields verbatim, all optional so the YAML
/// round-trip via the plain-text config modal preserves whatever
/// the user wrote. The renderer applies built-in defaults when a
/// field is `None`.
#[derive(Debug, Clone, Default)]
pub struct TerminalPrefs {
    pub shell: Option<String>,
    pub shortcut: Option<String>,
    pub screenshot_dir: Option<String>,
    pub screenshot_paste_shortcut: Option<String>,
    pub launcher_command: Option<String>,
    pub move_tab_left_shortcut: Option<String>,
    pub move_tab_right_shortcut: Option<String>,
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
    /// "Open with …" slots keyed by slot name (`main_ide`,
    /// `secondary_ide`, `terminal`, …). Only the `label` is consumed
    /// here; the command list itself lives on the mutations side and
    /// lands in Phase 3+.
    pub open_with: HashMap<String, OpenWithSlot>,
    /// Names of repo checkouts that carry a configured dev-runner.
    /// Parent repos use their `name`; subrepos use `<parent>--<sub>`.
    /// Matches the keyspace of Python's `ctx.repo_run`. Used by the
    /// Code-tab node fingerprint to emit `|run:<token>` fragments for
    /// configured rows and `""` for unconfigured ones — runner state
    /// itself is Phase 4+ territory, but the fingerprint needs to
    /// agree *now* so `/check-updates` stays consistent across the
    /// Python / Rust builds.
    pub repo_run_keys: std::collections::HashSet<String>,
    /// Runner command template per repo key. Populated from
    /// `repositories.yml`'s `run:` fields alongside [`Self::repo_run_keys`].
    /// The `{path}` placeholder is replaced with the absolute checkout
    /// path at spawn time (see `condash_mutations` / `pty.rs` callers).
    /// A key present in `repo_run_keys` but missing here means the
    /// config layer hasn't populated templates yet — the runner
    /// `/api/runner/start` handler treats that as "no command
    /// configured" and 404s, matching Python.
    pub repo_run_templates: HashMap<String, String>,
    /// Optional per-repo "nuclear" stop command. Same keyspace as
    /// [`Self::repo_run_templates`] (parent: `name`, subrepo:
    /// `<parent>--<sub>`). Populated from the `force_stop:` YAML field.
    /// Runs even when `runner_registry` has no live session, so the user
    /// can free a port held by a process condash didn't start. Missing
    /// key = no force-stop button rendered for that repo.
    pub repo_force_stop_templates: HashMap<String, String>,
    /// PDF-viewer command fallback chain (e.g. `["evince {path}",
    /// "okular {path}"]`). Empty = use the built-in chain. Consumed by
    /// the openers layer (Phase 3+).
    pub pdf_viewer: Vec<String>,
    /// Embedded-terminal preferences. All fields optional; absent ones
    /// fall back to the renderer's built-in defaults.
    pub terminal: TerminalPrefs,
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
