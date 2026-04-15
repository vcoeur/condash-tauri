---
name: condash
description: Inspect and maintain a conception-style markdown project tree (projects / incidents / documents) via the `condash` CLI. Bootstrap a config file, verify the effective configuration, move done items into monthly archive directories (`condash tidy`), and optionally register the app with the XDG desktop launcher on Linux. Use when the user asks to check or edit their condash config, archive done items, install the desktop entry, or understand what condash thinks its state is. Launching the native dashboard window is not part of this skill — run `condash` by hand for that.
argument-hint: "<natural language request>"
allowed-tools: Read, Write, Edit, Bash(condash --version), Bash(condash --help), Bash(condash init:*), Bash(condash config show:*), Bash(condash config path:*), Bash(condash config edit:*), Bash(condash tidy:*), Bash(condash install-desktop:*), Bash(condash uninstall-desktop:*), Bash(command -v condash:*)
---

Thin wrapper around the [`condash`](https://github.com/vcoeur/condash) CLI. `condash` is a standalone desktop dashboard for markdown-based conception projects, incidents, and documents — the native window is meant for interactive use. This skill exposes the **non-interactive** CLI surface only: bootstrap, config inspection, `tidy`, and desktop-launcher registration.

**This is a minimal example skill.** It does not encode any particular project-tree convention. Fork it and add your own rules (repository layout, custom deliverable format, per-item templates, etc.) as needed.

## Use at your own risk

`condash` is MIT-licensed software provided **as-is, with no warranty**. This skill runs `condash tidy`, which **moves files** inside your conception tree (done items into `YYYY-MM/` archive subdirectories). Keep the tree under version control, review the diff after every `tidy` run, and never point `conception_path` at a directory you care about without a recent commit.

This skill intentionally does not launch the native window from inside a Claude Code session. `condash` (no subcommand) opens a pywebview / Qt window — that is a long-running, interactive desktop process and is not useful under an agent. If the user wants to see the dashboard, they should open a terminal and run `condash` themselves.

## Prerequisites

```bash
command -v condash
```

If missing, install from PyPI:

```bash
pipx install condash
# or, fully isolated:
uv tool install condash
```

Installation is self-contained on Linux, macOS, and Windows — `pywebview[qt]` bundles a full PyQt6 stack so there are no system prerequisites. Install footprint is roughly 100 MB.

## First launch

`condash` has no working default config. Bootstrap one:

```bash
condash init         # writes a commented template at ~/.config/condash/config.toml
condash config path  # prints where it landed
condash config edit  # opens the template in $VISUAL / $EDITOR
```

The template is fully commented out. The only mandatory field is:

```toml
conception_path = "/path/to/your/conception/tree"
```

Optional fields worth knowing about when explaining the config to the user:

- `workspace_path` — directory containing code repositories; each direct subdirectory with a `.git/` is shown in the dashboard's repo strip. Leave unset to hide the strip entirely.
- `worktrees_path` — additional sandbox directory for the "open in IDE" action (extra git worktrees outside the main workspace tree).
- `port` — TCP port for the embedded HTTP server. `0` (default) asks the OS for a free port; pin a value if the user wants to reach the dashboard from a browser at `http://127.0.0.1:<port>`.
- `native` — `true` (default) opens a desktop window via pywebview; `false` serves the dashboard in whatever browser the user prefers.
- `[repositories]` — `primary` and `secondary` lists of bare directory names (not paths) that slot into the repo strip; anything left over lands in "Others". Both are ignored when `workspace_path` is unset.

## Request

> $ARGUMENTS

## Inspect the effective configuration

```bash
condash config show
```

Use this before editing anything — the output tells you which config file `condash` actually loaded (useful when `--config PATH` is in play) and the resolved values for every field.

## Tidy done items into monthly archives

```bash
condash tidy
```

`condash tidy` walks `conception_path` and moves items whose README has `Status: done` into a `YYYY-MM/` subdirectory under their type folder, grouped by the month of the closing timeline entry (or the file mtime if none is found). It is idempotent — running it again when there is nothing to tidy is a no-op.

**Always review the diff afterwards.** The move is a `git mv`-friendly rename, but it still changes file paths and any absolute links in your notes will need updating. Do not run `tidy` on a dirty conception tree — commit or stash first so you can inspect exactly what the command did.

## Register the desktop entry (Linux only)

```bash
condash install-desktop
```

Writes:

- `~/.local/share/applications/condash.desktop` — XDG launcher entry pointing at the absolute path of whichever `condash` binary you ran the command with
- `~/.local/share/icons/hicolor/scalable/apps/condash.svg` — the SVG app icon

No `sudo`, no system-wide changes. Reverse with:

```bash
condash uninstall-desktop
```

## Diagnosing problems

When the user reports that condash "does not work", start with:

```bash
condash --version
condash config show
condash config path
```

Typical failure modes to check for:

- `conception_path` unset or pointing at a non-existent directory → fix in the config file.
- Config file at an unexpected path because `--config PATH` was used or `CONDASH_CONFIG` is set in the environment.
- The user is on Linux without GTK/Qt Python bindings and `native = true` → suggest setting `native = false` to fall back to serving the dashboard in a browser.
- Port collision on a pinned `port` value → suggest `port = 0` (OS-assigned).

None of these require launching the native window — which is the point of this skill.

## Adapting this skill to your workflow

This skill stops at "inspect and tidy". Realistic conception workflows layer on top:

- Custom templates for new projects / incidents / documents (create them by writing files, not via `condash`).
- Automated deliverable generation (`condash` exposes the tree; the build step is yours).
- Cross-repo status reporting, dashboards, or notifications.

Those belong in a forked, user-specific `SKILL.md` — not here.

## Installation

Drop this `SKILL.md` into either:

- `~/.claude/skills/condash/SKILL.md` — available in every Claude Code session
- `<project>/.claude/skills/condash/SKILL.md` — project-local (auto-loaded when Claude Code opens that project)

See [Claude Code's skill documentation](https://docs.claude.com/en/docs/claude-code/skills) for details.

$ARGUMENTS
