//! Config loader — reads `<conception>/configuration.yml` into a
//! [`RenderCtx`].
//!
//! Flat YAML: the top level carries both the workspace layout
//! (`workspace_path`, `worktrees_path`, `repositories`, `open_with`)
//! and the user preferences (`pdf_viewer`, `terminal`). Replaces the
//! old split between `config/repositories.yml` and
//! `config/preferences.yml` — those split files are still written on
//! disk for the retired Python build (`condash-python`) but condash no
//! longer reads them.

use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};

use anyhow::{Context, Result};
use condash_state::{OpenWithSlot, RenderCtx, RepoEntry, RepoSection, TerminalPrefs};
use serde::Deserialize;

#[derive(Debug, Deserialize, Default)]
struct ConfigurationYaml {
    #[serde(default)]
    workspace_path: Option<String>,
    #[serde(default)]
    worktrees_path: Option<String>,
    #[serde(default)]
    repositories: Option<RepoBuckets>,
    #[serde(default)]
    open_with: Option<HashMap<String, OpenWithSlotYaml>>,
    #[serde(default)]
    pdf_viewer: Vec<String>,
    #[serde(default)]
    terminal: Option<TerminalYaml>,
}

#[derive(Debug, Deserialize, Default)]
struct TerminalYaml {
    #[serde(default)]
    shell: Option<String>,
    #[serde(default)]
    shortcut: Option<String>,
    #[serde(default)]
    screenshot_dir: Option<String>,
    #[serde(default)]
    screenshot_paste_shortcut: Option<String>,
    #[serde(default)]
    launcher_command: Option<String>,
    #[serde(default)]
    move_tab_left_shortcut: Option<String>,
    #[serde(default)]
    move_tab_right_shortcut: Option<String>,
}

impl TerminalYaml {
    fn into_prefs(self) -> TerminalPrefs {
        let TerminalYaml {
            shell,
            shortcut,
            screenshot_dir,
            screenshot_paste_shortcut,
            launcher_command,
            move_tab_left_shortcut,
            move_tab_right_shortcut,
        } = self;
        // Treat empty strings as unset so the YAML idiom `shell: ''` —
        // how the preferences file ships — round-trips as None.
        let squash = |s: Option<String>| s.filter(|v| !v.is_empty());
        TerminalPrefs {
            shell: squash(shell),
            shortcut: squash(shortcut),
            screenshot_dir: squash(screenshot_dir),
            screenshot_paste_shortcut: squash(screenshot_paste_shortcut),
            launcher_command: squash(launcher_command),
            move_tab_left_shortcut: squash(move_tab_left_shortcut),
            move_tab_right_shortcut: squash(move_tab_right_shortcut),
        }
    }
}

#[derive(Debug, Deserialize, Default)]
struct RepoBuckets {
    #[serde(default)]
    primary: Vec<RepoEntryYaml>,
    #[serde(default)]
    secondary: Vec<RepoEntryYaml>,
}

/// One entry under `repositories.primary` / `secondary`. Accepts either
/// a bare string (repo name) or a mapping with `name`, `submodules`,
/// `run` — Python's config parser has the same flexibility. We skip
/// `run` for Phase 2 and just remember that the key exists so the
/// fingerprint layer emits `|run:off` for those rows.
#[derive(Debug, Deserialize)]
#[serde(untagged)]
enum RepoEntryYaml {
    Bare(String),
    Full {
        name: String,
        #[serde(default)]
        submodules: Vec<SubmoduleYaml>,
        /// Present iff the user configured a `run:` command on this repo.
        /// We record it as a runner key; the command value is consumed
        /// by the runners module (Phase 4).
        #[serde(default)]
        run: Option<String>,
        /// Optional "nuclear" stop command. Invoked by the force-stop
        /// button when a port is held by a process condash didn't start
        /// (stale gunicorn, another terminal). The tri-state Start/Stop
        /// button only knows about condash-managed sessions.
        #[serde(default, alias = "force-stop")]
        force_stop: Option<String>,
    },
}

#[derive(Debug, Deserialize)]
#[serde(untagged)]
enum SubmoduleYaml {
    Bare(String),
    Full {
        name: String,
        #[serde(default)]
        run: Option<String>,
        #[serde(default, alias = "force-stop")]
        force_stop: Option<String>,
    },
}

#[derive(Debug, Deserialize, Default)]
struct OpenWithSlotYaml {
    #[serde(default)]
    label: Option<String>,
    #[serde(default)]
    commands: Vec<String>,
}

/// Path to the merged configuration file inside a conception tree.
pub fn configuration_path(conception_path: &Path) -> PathBuf {
    conception_path.join("configuration.yml")
}

/// Parse `body` as a well-formed `configuration.yml`. Returns Ok on
/// success. The config modal calls this before writing so invalid YAML
/// never hits disk.
pub fn validate_configuration_yaml(body: &str) -> Result<()> {
    let _: ConfigurationYaml =
        serde_yaml_ng::from_str(body).with_context(|| "parsing configuration.yml body")?;
    Ok(())
}

/// Atomically write `body` as `<conception>/configuration.yml`. Rejects
/// invalid YAML; on success, the file on disk is replaced in a single
/// rename so a crash mid-write cannot truncate the user's config.
pub fn write_configuration(conception_path: &Path, body: &str) -> Result<PathBuf> {
    validate_configuration_yaml(body)?;
    let path = configuration_path(conception_path);
    let tmp = {
        let mut p = path.to_path_buf();
        let name = path
            .file_name()
            .map(|n| n.to_string_lossy().into_owned())
            .unwrap_or_else(|| "configuration.yml".into());
        p.set_file_name(format!(".{name}.tmp"));
        p
    };
    fs::write(&tmp, body.as_bytes()).with_context(|| format!("writing {}", tmp.display()))?;
    fs::rename(&tmp, &path)
        .with_context(|| format!("renaming {} -> {}", tmp.display(), path.display()))?;
    Ok(path)
}

/// Build a [`RenderCtx`] for the conception tree at `conception_path`.
///
/// Reads `<conception>/configuration.yml` when present; falls back to
/// a minimal ctx when absent (no workspace, no git strip, no
/// preferences). `template` is the dashboard shell HTML — loaded once
/// by the caller so render helpers don't re-read the asset per request.
pub fn build_ctx(conception_path: &Path, template: String) -> Result<RenderCtx> {
    let yaml_path = configuration_path(conception_path);
    let mut ctx = RenderCtx {
        base_dir: conception_path.to_path_buf(),
        template,
        ..Default::default()
    };

    if !yaml_path.is_file() {
        // No configuration.yml yet — return a minimal ctx; the dashboard
        // renders without the Code tab populated.
        return Ok(ctx);
    }
    let raw = fs::read_to_string(&yaml_path)
        .with_context(|| format!("reading {}", yaml_path.display()))?;
    let parsed: ConfigurationYaml = serde_yaml_ng::from_str(&raw)
        .with_context(|| format!("parsing YAML at {}", yaml_path.display()))?;

    ctx.workspace = parsed.workspace_path.as_deref().map(expand_tilde);
    ctx.worktrees = parsed.worktrees_path.as_deref().map(expand_tilde);

    let mut repo_structure = Vec::new();
    let mut repo_run_keys = std::collections::HashSet::new();
    let mut repo_run_templates: HashMap<String, String> = HashMap::new();
    let mut repo_force_stop_templates: HashMap<String, String> = HashMap::new();
    if let Some(buckets) = &parsed.repositories {
        if !buckets.primary.is_empty() {
            repo_structure.push(RepoSection {
                label: "Primary".into(),
                repos: entries_from(
                    &buckets.primary,
                    &mut repo_run_keys,
                    &mut repo_run_templates,
                    &mut repo_force_stop_templates,
                ),
            });
        }
        if !buckets.secondary.is_empty() {
            repo_structure.push(RepoSection {
                label: "Secondary".into(),
                repos: entries_from(
                    &buckets.secondary,
                    &mut repo_run_keys,
                    &mut repo_run_templates,
                    &mut repo_force_stop_templates,
                ),
            });
        }
    }
    ctx.repo_structure = repo_structure;
    ctx.repo_run_keys = repo_run_keys;
    ctx.repo_run_templates = repo_run_templates;
    ctx.repo_force_stop_templates = repo_force_stop_templates;

    if let Some(open_with) = parsed.open_with {
        ctx.open_with = open_with
            .into_iter()
            .map(|(key, slot)| {
                let label = slot.label.unwrap_or_else(|| key.clone());
                (
                    key,
                    OpenWithSlot {
                        label,
                        commands: slot.commands,
                    },
                )
            })
            .collect();
    }

    ctx.pdf_viewer = parsed.pdf_viewer;
    if let Some(term) = parsed.terminal {
        ctx.terminal = term.into_prefs();
    }

    Ok(ctx)
}

fn entries_from(
    yaml: &[RepoEntryYaml],
    repo_run_keys: &mut std::collections::HashSet<String>,
    repo_run_templates: &mut HashMap<String, String>,
    repo_force_stop_templates: &mut HashMap<String, String>,
) -> Vec<RepoEntry> {
    let mut out = Vec::with_capacity(yaml.len());
    for entry in yaml {
        match entry {
            RepoEntryYaml::Bare(name) => out.push(RepoEntry {
                name: name.clone(),
                submodules: Vec::new(),
            }),
            RepoEntryYaml::Full {
                name,
                submodules,
                run,
                force_stop,
            } => {
                if let Some(tpl) = run.as_deref() {
                    let trimmed = tpl.trim();
                    if !trimmed.is_empty() {
                        repo_run_keys.insert(name.clone());
                        repo_run_templates.insert(name.clone(), trimmed.into());
                    }
                }
                if let Some(tpl) = force_stop.as_deref() {
                    let trimmed = tpl.trim();
                    if !trimmed.is_empty() {
                        repo_force_stop_templates.insert(name.clone(), trimmed.into());
                    }
                }
                let mut sub_names = Vec::with_capacity(submodules.len());
                for s in submodules {
                    match s {
                        SubmoduleYaml::Bare(n) => sub_names.push(n.clone()),
                        SubmoduleYaml::Full {
                            name: sub,
                            run,
                            force_stop,
                        } => {
                            if let Some(tpl) = run.as_deref() {
                                let trimmed = tpl.trim();
                                if !trimmed.is_empty() {
                                    let key = format!("{name}--{sub}");
                                    repo_run_keys.insert(key.clone());
                                    repo_run_templates.insert(key, trimmed.into());
                                }
                            }
                            if let Some(tpl) = force_stop.as_deref() {
                                let trimmed = tpl.trim();
                                if !trimmed.is_empty() {
                                    let key = format!("{name}--{sub}");
                                    repo_force_stop_templates.insert(key, trimmed.into());
                                }
                            }
                            sub_names.push(sub.clone());
                        }
                    }
                }
                out.push(RepoEntry {
                    name: name.clone(),
                    submodules: sub_names,
                });
            }
        }
    }
    out
}

fn expand_tilde(s: &str) -> PathBuf {
    if let Some(stripped) = s.strip_prefix("~/") {
        if let Some(home) = std::env::var_os("HOME") {
            return PathBuf::from(home).join(stripped);
        }
    }
    PathBuf::from(s)
}
