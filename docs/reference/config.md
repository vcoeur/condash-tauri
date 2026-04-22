---
title: Config files · condash reference
description: The two tree-level YAML config files — one team-shared, one per-machine — and every key in each.
---

# Config files

## At a glance

condash reads **two** config files, both under `<conception_path>/config/`. Which file owns which key is not cosmetic — it's how per-team and per-machine boundaries are kept separate.

| File | Location | Scope | Owns |
|------|----------|-------|------|
| `repositories.yml` | `<conception_path>/config/repositories.yml` | Per-tree, versioned in git | `workspace_path`, `worktrees_path`, `repositories`, `open_with` |
| `preferences.yml` | `<conception_path>/config/preferences.yml` | Per-tree but **not** versioned — per-machine preferences for this tree | `pdf_viewer`, `terminal` |

The two YAML files live *inside* the conception tree itself. On any given machine, they're merged at load time: `preferences.yml` overrides `repositories.yml` on overlapping keys. Moving a team-wide setting into `repositories.yml` automatically propagates to every developer who pulls the tree.

One thing that isn't a file: the conception path itself. That comes from the `CONDASH_CONCEPTION_PATH` environment variable (defaulting to `$HOME/src/vcoeur/conception`), because the tree doesn't know where it lives on disk. See [Environment variables](env.md).

## `repositories.yml` (per-tree, versioned)

Lives at `<conception_path>/config/repositories.yml`. Commit it — every developer who pulls the tree gets the same workspace layout and "open with" commands.

```yaml
workspace_path: /home/you/src
worktrees_path: /home/you/src/worktrees

repositories:
  primary:
    - condash
    - { name: helio, submodules: [apps/web, apps/api] }
  secondary:
    - conception

open_with:
  main_ide:
    label: Open in main IDE
    commands:
      - idea {path}
      - idea.sh {path}
  secondary_ide:
    label: Open in secondary IDE
    commands:
      - code {path}
      - codium {path}
  terminal:
    label: Open terminal here
    commands:
      - ghostty --working-directory={path}
      - gnome-terminal --working-directory {path}
```

| Key | Meaning |
|-----|---------|
| `workspace_path` | Directory condash scans for git repositories. Every direct subdirectory containing a `.git/` shows up in the **Code** tab. If unset, the tab is hidden. |
| `worktrees_path` | Additional sandbox for the "open in IDE" buttons. Paths outside `workspace_path` and `worktrees_path` are rejected before the shell sees them. |
| `repositories.primary` | List of bare directory names (not paths) matched against the scan. Shown in the `PRIMARY` card. |
| `repositories.secondary` | Same as primary, shown in the `SECONDARY` card. Anything under `workspace_path` not named in either list lands in an `OTHERS` card. |
| Entry with `submodules` | An inline map `{name: repo, submodules: [sub/one, sub/two]}` renders the repo as an expandable row with sub-rows for each listed subdirectory. Each submodule keeps its own dirty count and "open with" buttons. Useful for monorepos where different subtrees are edited independently. |
| Entry with `run` | Either a top-level inline map `{name: repo, run: "<cmd>"}` or a sub-repo map `{name: apps/web, run: "<cmd>"}` wires an [inline dev-server runner](inline-runner.md) into that row. `run:` is independent of `submodules:` — a parent's `run:` is **not** inherited by its submodules. |
| `open_with.<slot>` | Three vendor-neutral launcher slots (`main_ide`, `secondary_ide`, `terminal`). Each slot has a `label` (tooltip) and a `commands` fallback chain. |

### `{path}` substitution

Each `commands` entry is a single shell-style string. The literal `{path}` is replaced with the absolute path of the repo / worktree being opened. Commands are tried in order until one starts successfully — if `idea {path}` isn't on `$PATH`, the button falls through to `idea.sh {path}` automatically.

Built-in defaults reproduce common IntelliJ / VS Code / terminal behaviour, so a `repositories.yml` with no `open_with` section still gives functional buttons. Override only the slots you want to customise.

## `preferences.yml` (per-tree, **not** versioned)

Lives at `<conception_path>/config/preferences.yml`. **Do not** commit this file — add it to the tree's `.gitignore`. It holds per-machine overrides for this tree, so different trees on the same machine can use different terminal shortcuts or PDF viewers, and different machines sharing the same tree can carry their own preferences.

```yaml
pdf_viewer:
  - xdg-open {path}
  - evince {path}

terminal:
  shell: /bin/zsh
  shortcut: Ctrl+T
  screenshot_dir: /home/you/Pictures/Screenshots
  screenshot_paste_shortcut: Ctrl+Shift+V
  launcher_command: claude
  move_tab_left_shortcut: Ctrl+Left
  move_tab_right_shortcut: Ctrl+Right
```

### Top-level keys

| Key | Meaning |
|-----|---------|
| `pdf_viewer` | Bare list of shell-style commands, tried in order. `{path}` is replaced with the absolute path of the PDF. Unset or empty → falls back to the OS default. |

### `terminal`

| Key | Default | Meaning |
|-----|---------|---------|
| `shell` | `$SHELL` → `/bin/bash` | Absolute path to an interactive shell. |
| `shortcut` | `` Ctrl+` `` | Toggle the terminal pane. Modifiers: `Ctrl`, `Shift`, `Alt`, `Meta`. Key names follow the HTML `KeyboardEvent.key` convention. |
| `screenshot_dir` | `~/Pictures/Screenshots` on Linux, `~/Desktop` on macOS | Directory scanned for "most recent screenshot" by the paste shortcut. |
| `screenshot_paste_shortcut` | `Ctrl+Shift+V` | Inserts the absolute path of the newest image in `screenshot_dir` into the active terminal. No `Enter` — user confirms. |
| `launcher_command` | `claude` | Shell-style command spawned by the secondary `+` button in each terminal side. Empty hides the button. |
| `move_tab_left_shortcut` | `Ctrl+Left` | Move the active tab to the left pane. |
| `move_tab_right_shortcut` | `Ctrl+Right` | Move the active tab to the right pane. |

## Merge order

At load time:

1. Start with defaults compiled into the binary.
2. Merge `<conception_path>/config/repositories.yml` on top.
3. Merge `<conception_path>/config/preferences.yml` on top (overrides `repositories.yml` on overlapping keys — `pdf_viewer`, `terminal`).

Result: team-shared repo/IDE settings from the versioned YAML, plus per-tree per-machine tweaks from the untracked YAML.

## Editing from the dashboard

Click the gear icon in the header. A modal opens with three tabs:

![Gear modal General tab](../assets/screenshots/gear-modal-light.png#only-light)
![Gear modal General tab](../assets/screenshots/gear-modal-dark.png#only-dark)

- **General** → the conception path (written to `preferences.yml`) plus a few per-machine defaults.
- **Repositories** → writes `workspace_path`, `worktrees_path`, `repositories`, `open_with` to `repositories.yml`.
- **Preferences** → writes `pdf_viewer`, `terminal` to `preferences.yml`.

![Gear modal Repositories tab](../assets/screenshots/gear-modal-repositories-light.png#only-light)
![Gear modal Repositories tab](../assets/screenshots/gear-modal-repositories-dark.png#only-dark)

![Gear modal Preferences tab](../assets/screenshots/gear-modal-preferences-light.png#only-light)
![Gear modal Preferences tab](../assets/screenshots/gear-modal-preferences-dark.png#only-dark)

Saves are atomic and preserve comments you've added outside the managed blocks. Most changes reload live; a port or webview-host change requires a restart and the modal tells you so.

## Machine-local TOML

An earlier build also carried a per-machine TOML file (`~/.config/condash/config.toml`) for settings that didn't fit either YAML. That file is no longer read — the conception path lives in the `CONDASH_CONCEPTION_PATH` environment variable instead, and the remaining per-machine knobs are all in `preferences.yml`. A future release may reintroduce a machine-local override surface; for now there is none.
