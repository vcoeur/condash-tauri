---
title: First launch · condash
description: What happens the first time you open condash, how to pick your conception tree, and where the setting is stored.
---

# First launch

The first time you launch condash, it needs to know which Markdown tree to render. There's no hard-coded default — if it can't find one, a native folder picker opens and asks you to select it.

## The conception tree

A conception tree is a directory on your disk with at least one of:

- A `configuration.yml` file at the root (optional for a fresh tree, required for the repo strip and "open with" buttons to do anything useful).
- A `projects/` subdirectory containing your item READMEs.

Optional siblings — `knowledge/`, a `documents/` drop-point, and so on — add features but aren't required to boot condash. See the **[conception convention](../reference/conception-convention.md)** for the full shape.

If you don't already have a tree, a minimal bootstrap is a scratch directory with an empty `projects/` inside:

```bash
mkdir -p /tmp/condash-scratch/projects
CONDASH_CONCEPTION_PATH=/tmp/condash-scratch condash
```

That's enough for the dashboard to render — use the **+ Item** button to create your first README.

## The three ways condash finds your tree

On startup condash checks, in order:

1. **`CONDASH_CONCEPTION_PATH` environment variable.** Wins over everything. Useful for scripts, demos, and running condash against a scratch tree without touching your saved settings:
   ```bash
   CONDASH_CONCEPTION_PATH=/tmp/scratch-tree condash
   ```
2. **Saved user setting.** If the env var is unset, condash reads `${XDG_CONFIG_HOME:-~/.config}/condash/settings.yaml` (Linux/macOS) or `%APPDATA%\condash\settings.yaml` (Windows). The file has one key:
   ```yaml
   conception_path: /home/you/src/conception
   ```
   It's written automatically after the folder picker on first launch.
3. **Folder picker.** If neither the env var nor the settings file supply a path, condash opens a native OS folder picker. Pick the directory that holds your `projects/` + (optional) `configuration.yml`. On **Cancel**, condash exits cleanly.

## Changing your mind later

To point condash at a different tree:

- **Temporarily**: set `CONDASH_CONCEPTION_PATH` for one run, then relaunch without it to go back to the saved tree.
- **Permanently**: edit `${XDG_CONFIG_HOME:-~/.config}/condash/settings.yaml` directly, or delete the file to get the folder picker again on the next launch.

## What else you can configure

The conception path is the only thing condash needs to boot. Everything else — the workspace of code repos shown in the Code tab, the "open with" launcher chains, terminal preferences — lives inside the conception tree itself as `configuration.yml`. Edit it by hand or through the gear icon in the dashboard header (which opens a plain YAML editor).

See **[Config file reference](../reference/config.md)** for the full schema.
