//! Minimal config loader — reads `<conception>/config/repositories.yml`
//! into a [`RenderCtx`] suitable for the Phase 2 read-only routes.
//!
//! Scoped intentionally narrow: parses `workspace_path`, `worktrees_path`,
//! `repositories.{primary,secondary}` (repo names + optional submodule
//! lists + optional `run:` commands), and `open_with` labels. The
//! Python build has a richer config.py with TOML layering, defaults,
//! and preferences.yml — those belong in a later phase once the Rust
//! app runs real user workflows.

use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};

use anyhow::{Context, Result};
use condash_state::{OpenWithSlot, RenderCtx, RepoEntry, RepoSection};
use serde::Deserialize;

#[derive(Debug, Deserialize, Default)]
struct RepositoriesYaml {
    #[serde(default)]
    workspace_path: Option<String>,
    #[serde(default)]
    worktrees_path: Option<String>,
    #[serde(default)]
    repositories: Option<RepoBuckets>,
    #[serde(default)]
    open_with: Option<HashMap<String, OpenWithSlotYaml>>,
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
    },
}

#[derive(Debug, Deserialize, Default)]
struct OpenWithSlotYaml {
    #[serde(default)]
    label: Option<String>,
    // commands: skipped for Phase 2 — consumed by the mutations layer.
}

/// Build a [`RenderCtx`] for the conception tree at `conception_path`.
///
/// Reads `<conception>/config/repositories.yml` when present; falls
/// back to minimal state when absent (no workspace, no git strip).
/// Also loads `<conception_path>/../<template>` — the dashboard shell —
/// into `ctx.template`. The template itself lives next to the Python
/// package's `assets/` directory; `template_path` points the loader at
/// it explicitly so the Tauri binary can be launched from anywhere.
pub fn build_ctx(conception_path: &Path, template_path: &Path) -> Result<RenderCtx> {
    let template = fs::read_to_string(template_path)
        .with_context(|| format!("reading dashboard template at {}", template_path.display()))?;

    let yaml_path = conception_path.join("config").join("repositories.yml");
    let mut ctx = RenderCtx {
        base_dir: conception_path.to_path_buf(),
        template,
        ..Default::default()
    };

    if !yaml_path.is_file() {
        // No repositories.yml yet — return a minimal ctx; the dashboard
        // renders without the Code tab populated.
        return Ok(ctx);
    }
    let raw = fs::read_to_string(&yaml_path)
        .with_context(|| format!("reading {}", yaml_path.display()))?;
    let parsed: RepositoriesYaml = serde_yaml_ng::from_str(&raw)
        .with_context(|| format!("parsing YAML at {}", yaml_path.display()))?;

    ctx.workspace = parsed.workspace_path.as_deref().map(expand_tilde);
    ctx.worktrees = parsed.worktrees_path.as_deref().map(expand_tilde);

    let mut repo_structure = Vec::new();
    let mut repo_run_keys = std::collections::HashSet::new();
    if let Some(buckets) = &parsed.repositories {
        if !buckets.primary.is_empty() {
            repo_structure.push(RepoSection {
                label: "Primary".into(),
                repos: entries_from(&buckets.primary, &mut repo_run_keys),
            });
        }
        if !buckets.secondary.is_empty() {
            repo_structure.push(RepoSection {
                label: "Secondary".into(),
                repos: entries_from(&buckets.secondary, &mut repo_run_keys),
            });
        }
    }
    ctx.repo_structure = repo_structure;
    ctx.repo_run_keys = repo_run_keys;

    if let Some(open_with) = parsed.open_with {
        ctx.open_with = open_with
            .into_iter()
            .map(|(key, slot)| {
                let label = slot.label.unwrap_or_else(|| key.clone());
                (key, OpenWithSlot { label })
            })
            .collect();
    }

    Ok(ctx)
}

fn entries_from(
    yaml: &[RepoEntryYaml],
    repo_run_keys: &mut std::collections::HashSet<String>,
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
            } => {
                if run.is_some() {
                    repo_run_keys.insert(name.clone());
                }
                let mut sub_names = Vec::with_capacity(submodules.len());
                for s in submodules {
                    match s {
                        SubmoduleYaml::Bare(n) => sub_names.push(n.clone()),
                        SubmoduleYaml::Full { name: sub, run } => {
                            if run.is_some() {
                                repo_run_keys.insert(format!("{name}--{sub}"));
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
