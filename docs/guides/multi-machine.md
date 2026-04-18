---
title: Multi-machine setup · condash guide
description: Sync a conception tree between machines via git. What goes in version control, what stays local, how to split configs.
---

# Multi-machine setup

**When to read this.** You work across two (or more) machines — a desktop and a laptop, your work box and a personal box — and you want the same tree on each, with per-machine tweaks that don't fight each other.

condash was designed for this split from day one. The two-file config layout (per-tree YAML, per-machine TOML) is the whole answer.

## The three config files

| File | Lives in | Committed? | Per-machine or per-tree? |
|---|---|---|---|
| `config.toml` | `~/.config/condash/` | No (outside the tree) | Per-machine |
| `repositories.yml` | `<conception_path>/config/` | **Yes** | Per-tree (shared) |
| `preferences.yml` | `<conception_path>/config/` | **No** | Per-tree, per-machine |

- **`config.toml`** — lives outside the conception tree, one per user per machine. Never in version control. Holds `conception_path`, `port`, `native`, and fallback terminal/PDF settings.
- **`repositories.yml`** — lives inside the tree. **Commit this.** It's the team-shared config: workspace layout, repo grouping, open-with command chains. When a teammate pulls, their repo strip matches yours.
- **`preferences.yml`** — lives inside the tree. **Don't commit it.** Per-machine overrides scoped to this tree. Useful when machine A has Ghostty and machine B has gnome-terminal, or when you want a different terminal shortcut on each host.

## Syncing via git

Treat the conception tree as a plain git repository:

```bash
cd ~/conception
git init
git add projects/ knowledge/ config/repositories.yml
git commit -m "Initial conception tree"
git remote add origin git@github.com:you/conception.git
git push -u origin main
```

On the other machine:

```bash
git clone git@github.com:you/conception.git ~/conception
```

Edit `~/.config/condash/config.toml` on each machine to point `conception_path` at the local clone. Paths typically differ (different usernames, different home directories), which is exactly why this lives in per-machine TOML.

## `.gitignore` for the tree

Drop this into the tree's `.gitignore`:

```
config/preferences.yml
*.local.md
.DS_Store
```

The first line is the important one — it's the only file inside `config/` that should never be versioned.

If you use the `/conception` skill suite or have `.claude/` subdirectories, add them too:

```
.claude/*
!.claude/skills/
!.claude/scripts/
```

Negate only the directories you intentionally share. Default is to hide everything.

## Per-machine terminal tweaks

Example: your desktop has `ghostty`, your laptop has only `gnome-terminal`. The shared `repositories.yml` wires a fallback chain that works on both:

```yaml
open_with:
  terminal:
    commands:
      - ghostty --working-directory={path}
      - gnome-terminal --working-directory {path}
```

No per-machine edit needed — the first command that resolves wins.

But if you want a different **terminal toggle shortcut** on each machine (say `` Ctrl+` `` on one and `Ctrl+T` on the other because the laptop's keyboard intercepts the backtick), put the override in `preferences.yml` on each machine:

```yaml
# preferences.yml on the laptop
terminal:
  shortcut: Ctrl+T
```

Leave `preferences.yml` absent on the desktop and condash falls back to `config.toml` or its defaults.

The same pattern works for `screenshot_dir` (different directories per OS), `launcher_command` (different Claude Code install paths), and the `pdf_viewer` chain.

## Merge order (recap)

When condash boots, the effective config is the result of layering in this order, top to bottom wins:

1. Built-in defaults.
2. `~/.config/condash/config.toml`.
3. `<conception_path>/config/repositories.yml`.
4. `<conception_path>/config/preferences.yml`.

A key set in `preferences.yml` overrides everything else. A key set only in `config.toml` survives because nothing above overrode it.

Full details in the [config reference](../reference/config.md).

## Debugging "why is condash picking X?"

Two commands tell you everything:

```bash
condash config path
```

Prints the location of the TOML file. If this isn't what you expected, check `$XDG_CONFIG_HOME` and any `--config` flag you may have passed.

```bash
condash config show --json
```

Prints the fully-merged configuration as JSON, after all four layers have been applied. Diff this between machines when something renders differently on each — the diff is usually obvious.

## Handling conflicts in the shared `repositories.yml`

Because `repositories.yml` is versioned, any team-wide layout change is a git commit. If two teammates edit it simultaneously, resolve conflicts the usual way — the file is YAML, conflicts are readable, and no binary format gets in the way.

One rule of thumb: **keep `workspace_path` and `worktrees_path` at the top of the file**, even though they're per-user. Different teammates will have different absolute paths, which means this file is technically per-user even though it's committed — each teammate edits their two path lines post-clone.

The cleaner approach: leave those two keys out of `repositories.yml` and put them in `preferences.yml` instead. Yes, this breaks the "repositories.yml is shared, preferences.yml is local" rule slightly — but it avoids a merge conflict on every pull. Pick whichever trade-off bothers you less.

## Next

- [Configure the conception path](configure-conception-path.md) — the basic `conception_path` setup, per-machine.
- [Repositories and open-with buttons](repositories-and-open-with.md) — the full `repositories.yml` schema.
