---
title: Multi-machine setup · condash guide
description: Sync a conception tree between machines via git. What goes in version control, what stays per-machine, and how condash layers the two.
---

# Multi-machine setup

**When to read this.** You work across two (or more) machines — a desktop and a laptop, your work box and a personal box — and you want the same tree on each, with per-machine tweaks that don't fight each other.

condash was designed for this split from day one. One versioned YAML file at the tree root, one per-machine YAML file in your XDG config directory. The two layer at launch with clear precedence.

## The two config files

| File | Lives in | Committed? | Per-machine or per-tree? |
|---|---|---|---|
| `configuration.yml` | `<conception_path>/configuration.yml` | **Yes** | Per-tree (shared) |
| `settings.yaml` | `${XDG_CONFIG_HOME:-~/.config}/condash/` | **No** — outside the tree | Per-user, per-machine |

- **`configuration.yml`** — inside the tree. **Commit this.** It's the team-shared config: workspace layout, repo grouping, optional `run:` / `force_stop:` commands. When a teammate pulls, their repo strip matches yours.
- **`settings.yaml`** — outside the tree, in your XDG config. **Not versioned.** Holds `conception_path` (which tree to render) plus the three blocks that naturally differ per machine: `terminal.*`, `pdf_viewer`, `open_with.*`.

The two layer at launch: `configuration.yml` loads first, then `settings.yaml` overrides matching keys field by field. See [Precedence on overlap](#precedence-on-overlap) below for the exact rules.

## Installing condash on each machine

Each machine needs its own condash build. Two options:

- **Download from GitHub Releases.** Each release ships a per-OS installer: `.AppImage` / `.deb` on Linux, `.dmg` on macOS, `.msi` on Windows. See [Install](../get-started/install.md) for the first-launch bypass each OS asks for.
- **Build from source.** Clone the repo, then `make setup && make frontend && make build`. Handy when you want to match a specific commit across machines.

The two machines don't need to run the same condash version — the HTTP API, README format, and config files are stable across minor versions.

## Syncing the tree via git

Treat the conception tree as a plain git repository:

```bash
cd ~/conception
git init
git add projects/ knowledge/ configuration.yml
git commit -m "Initial conception tree"
git remote add origin git@github.com:you/conception.git
git push -u origin main
```

On the other machine:

```bash
git clone git@github.com:you/conception.git ~/conception
```

Then tell condash on the second machine where the tree lives — either set the env var per shell session, or let the first-launch folder picker write it to `settings.yaml`:

```bash
# ~/.bashrc or ~/.zshrc on each machine
export CONDASH_CONCEPTION_PATH="$HOME/conception"
```

Paths typically differ per machine (different usernames, different home directories), which is exactly why `conception_path` is per-machine rather than part of the versioned tree.

## `.gitignore` for the tree

Drop this into the tree's `.gitignore`:

```
*.local.md
.DS_Store
```

`settings.yaml` does not need to appear here — it lives outside the tree (in `${XDG_CONFIG_HOME:-~/.config}/condash/`), so git inside the conception tree cannot see it.

If you use the `/conception` skill suite or have `.claude/` subdirectories, add them too:

```
.claude/*
!.claude/skills/
!.claude/scripts/
```

Negate only the directories you intentionally share. Default is to hide everything.

## Per-machine terminal tweaks

Example: your desktop has `ghostty`, your laptop has only `gnome-terminal`. Wire the fallback in the **tree**'s `configuration.yml` so both machines see the same chain:

```yaml
# configuration.yml
open_with:
  terminal:
    commands:
      - ghostty --working-directory={path}
      - gnome-terminal --working-directory {path}
```

The first command that resolves on each machine wins — no per-machine edit needed.

But if you want a different **terminal toggle shortcut** on each machine (say `` Ctrl+` `` on one and `Ctrl+T` on the other because the laptop's keyboard intercepts the backtick), put the override in each machine's `settings.yaml`:

```yaml
# ~/.config/condash/settings.yaml on the laptop
conception_path: /home/you/conception
terminal:
  shortcut: Ctrl+T
```

Leave that key absent on the desktop and condash falls back to whatever `configuration.yml` declares (or the built-in default if the tree doesn't set it either).

The same pattern works for `screenshot_dir` (different directories per OS), `launcher_command` (different Claude Code install paths), and the `pdf_viewer` chain.

## Precedence on overlap

When condash boots, each key is resolved in this order — the first layer that sets it wins:

1. **`settings.yaml`** (`${XDG_CONFIG_HOME:-~/.config}/condash/settings.yaml`) — per-machine.
2. **`configuration.yml`** (`<conception_path>/configuration.yml`) — tree-level.
3. Built-in defaults compiled into the binary.

Merging is **per field**:

- `terminal.<field>`: each field set in `settings.yaml` replaces the tree's value; missing fields fall through.
- `pdf_viewer`: a non-empty list in `settings.yaml` replaces the tree's; empty or missing falls through.
- `open_with.<slot>`: merged per slot. A user `commands` replaces the tree's commands; a user `label` replaces the tree's label. A slot only set in the tree survives.

`CONDASH_CONCEPTION_PATH` is orthogonal — it only decides which tree the tree-level file belongs to; it does not affect merging between the two files.

Full details in the [config reference](../reference/config.md).

## Handling conflicts in `configuration.yml`

Because `configuration.yml` is versioned, any team-wide layout change is a git commit. If two teammates edit it simultaneously, resolve conflicts the usual way — the file is plain YAML, conflicts are readable, and no binary format gets in the way.

Typical flow when you need to tweak a machine-local value:

1. **Tempted to edit `configuration.yml`?** Stop — if the change only makes sense for your machine, put it in `settings.yaml` instead. No conflict with teammates.
2. **Change is team-wide?** Edit `configuration.yml`, commit, push. Teammates get it on the next pull.

## Next

- [Configure the conception path](configure-conception-path.md) — the basic `CONDASH_CONCEPTION_PATH` setup, per-machine.
- [Repositories and open-with buttons](repositories-and-open-with.md) — the full `repositories` schema inside `configuration.yml`.
- [Config reference](../reference/config.md) — every key in both files.
