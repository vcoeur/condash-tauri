---
title: Configure the conception path · condash guide
description: Point condash at the directory it should render — persistently, for one run, or from the gear modal.
---

# Configure the conception path

**When to read this.** You want condash to render a tree other than the one it's using now, or you want to know all the ways that path can be set.

The conception path is the only piece of configuration condash needs before it can start. Everything else has a sensible default.

## Option 1 — first-launch folder picker

On first launch with no tree configured, condash opens a native folder picker. Pick the directory containing your `projects/` + (optional) `configuration.yml` and condash writes the choice to `${XDG_CONFIG_HOME:-~/.config}/condash/settings.yaml`. Subsequent launches reuse the saved path automatically.

This is the right setup for your main tree — the path you work in every day.

## Option 2 — via `CONDASH_CONCEPTION_PATH`

condash reads the path from the `CONDASH_CONCEPTION_PATH` environment variable. For a one-shot run against a scratch tree:

```bash
CONDASH_CONCEPTION_PATH=/tmp/experimental-tree condash
```

To make it persistent, export it from your shell's rc file:

```bash
# ~/.bashrc, ~/.zshrc, etc.
export CONDASH_CONCEPTION_PATH="$HOME/conception"
```

Useful for:

- Trying a fresh tree layout without disturbing your saved path.
- Running two condash instances side-by-side (pin each with a different `CONDASH_PORT` on `condash-serve`) to compare trees.
- Scripts and demos where you want an explicit path in the recipe.

## Option 3 — edit `settings.yaml` by hand

Change the saved path without re-launching the picker by editing `${XDG_CONFIG_HOME:-~/.config}/condash/settings.yaml` directly:

```yaml
conception_path: /home/you/another-tree
```

Delete the file to force the folder picker on the next launch.

## Resolution order

On startup condash checks, in order:

1. `CONDASH_CONCEPTION_PATH` environment variable (wins when set).
2. `conception_path` in `settings.yaml`.
3. First-launch folder picker (Tauri build only). Writes the choice back to `settings.yaml`.
4. Hard error — condash refuses to start.

## When to use a scratch tree

A scratch tree is any directory with a minimal `projects/YYYY-MM/` layout that you point condash at temporarily. Common reasons:

- **Learning** — the bundled `conception-demo` tree, fetched in [First run](../tutorials/first-run.md).
- **Onboarding a teammate** — fork a small sample tree, have them point condash at it, walk them through creating their first item, then point them at the team tree.
- **Snapshot of a bug** — reduce a broken tree to a minimal reproducer, commit it, and file the issue with a `CONDASH_CONCEPTION_PATH=...` command in the repro steps.

The cheapest way to make one:

```bash
mkdir -p /tmp/scratch-tree/projects/2026-04
CONDASH_CONCEPTION_PATH=/tmp/scratch-tree condash
```

The Projects tab will be empty but the dashboard will render. Add README files under `projects/2026-04/` and refresh.

## Multiple machines pointed at the same tree

If you sync the conception tree between machines via git, each machine keeps its own `conception_path` in `settings.yaml` — the absolute path typically differs (different users, different mount points). The tree itself carries the team-shared config in `configuration.yml`; per-machine preferences live in each machine's `settings.yaml`. See [Multi-machine setup](multi-machine.md) for the full split.
