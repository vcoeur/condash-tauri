---
title: condash — Markdown project dashboard
description: Standalone desktop dashboard for markdown-based projects, incidents, and documents — live-rendered from the files you edit by hand.
---

# condash

<p class="tagline">A dashboard for the markdown you already write.</p>

Single-user native-feeling desktop app that renders a live dashboard of a directory tree of projects, incidents, and documents written as Markdown. Browse them, track `## Steps` checklists, toggle item status, reorder steps, open files in your IDE, and tidy done items into monthly archive folders — all from one window backed by the same `.md` files you edit by hand.

Built for the `conception` convention (`projects/YYYY-MM-DD-slug/README.md`, `incidents/…`, `documents/…`), but it works with any directory tree of Markdown READMEs that follows the same shape.

## Install

```bash
pipx install condash
# or
uv tool install condash
```

`condash` bundles its native-window backend (`pywebview[qt]` → `PyQt6` + `PyQt6-WebEngine`) as a Python dependency, so a vanilla install is self-contained on Linux, macOS, and Windows — no system Qt or GTK install required. Install size is ~100 MB; the trade is "works everywhere with one command". See [Install](install.md) for per-platform notes and the fallback to a plain browser window.

## 60-second quickstart

```bash
# One-time setup — writes a commented config template to ~/.config/condash/config.toml.
condash init
condash config edit                # opens it in $VISUAL / $EDITOR
```

In the config, uncomment and set at minimum:

```toml
conception_path = "/path/to/your/markdown/tree"
```

Then:

```bash
condash                            # opens the dashboard window
```

If you prefer the dashboard in a browser tab instead of a native window, set `native = false` in the config — condash will serve it at `http://127.0.0.1:<port>`.

## What it does

- **Live dashboard.** Reads the directory tree on every page load. Edit a README in your editor, refresh the window, see the change. No build step, no database — the Markdown files are the source of truth.
- **`## Steps` checklists.** Each item's README can declare a `## Steps` section with `[ ]` / `[~]` / `[x]` / `[!]` markers. The dashboard renders them as live checkboxes, lets you toggle status, and reorders them with drag-and-drop.
- **Status-aware layout.** Items with status `now`, `soon`, or `done` are grouped and sorted. `condash tidy` moves done items into `YYYY-MM/` archive folders so the main directory stays focused on what's active.
- **Open-with slots.** Three vendor-neutral launcher buttons per repo (`main_ide`, `secondary_ide`, `terminal`) with configurable fallback chains — `idea {path}`, `code {path}`, `ghostty --working-directory={path}`, etc. Tried in order until one starts.
- **Repo strip.** If you set `workspace_path`, every direct subdirectory that contains a `.git/` shows up as a card with the three launcher buttons. Primary / secondary / others bucketed via the `[repositories]` config.
- **In-app config editor.** Gear icon in the header opens a modal with form fields for every option. Saves atomically via `tomlkit` (preserves your comments) and reloads the dashboard.
- **Cross-platform.** Linux first (most tested), macOS and Windows should work. pywebview picks the native backend per OS — GTK/WebKit on Linux if available, Cocoa/WebKit on macOS, Edge WebView2 on Windows — and falls back to Qt elsewhere.

## Why condash

The dashboard is a live view, not a source of truth. You keep editing the same Markdown files in your usual editor (git diffs, commits, everything unchanged), and `condash` gives you a polished navigation layer on top: at-a-glance status, step progress, one-click "open this repo in IntelliJ", and a tidy command that sweeps finished work out of the way. Good for personal systems-documentation repos, engineering logbooks, and anyone who wants "markdown files + dashboard UI" without committing to a heavier tool like Obsidian or Notion.

## Learn more

- [Install guide](install.md) — per-platform notes, first launch, config reference, Linux desktop entry
- [Commands](commands.md) — full CLI reference
- [Source on GitHub](https://github.com/vcoeur/condash)
- [`condash` on PyPI](https://pypi.org/project/condash/)
