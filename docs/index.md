---
title: condash — Markdown project dashboard
description: Live desktop dashboard for a Markdown-first project-tracking convention. Your projects, incidents, and documents are plain .md files you already edit; condash gives you the polished view on top.
---

# condash

<p class="tagline">A dashboard for the Markdown you already write.</p>

`condash` is a single-user desktop app that renders a live dashboard of a directory tree of **projects**, **incidents**, and **documents** written as Markdown. No database, no sync server, no account — the Markdown files are the source of truth, and `condash` is the view layer.

## Why condash

The idea: **your project tracker should be plain files in git, not a SaaS**.

- Project descriptions, incident reports, research notes, and to-dos should all be editable in your usual editor, diffable in git, grep-able from a shell, and ignorable from any tool that does not understand them.
- A dashboard on top should be a live view of those files — zero friction to pick it up, zero lock-in to put it down.
- When you finish an item, you should be able to sweep it into an archive without losing it. When you search for it six months later, it should still be there.

`condash` implements exactly that. You keep editing a directory tree of Markdown READMEs in any editor you like; the dashboard window shows status, progress, quick filters, open-with-IDE buttons, and an archive sweeper — and every action it takes is a mutation of the same files you see in `git diff`.

Concrete scenarios this is good for:

- **Solo developer juggling several apps.** One `projects/` folder for features, one `incidents/` folder for bugs and outages, one `documents/` folder for plans and investigations. The dashboard gives you "what's active across all apps" at a glance; the archives keep the noise away.
- **Engineering logbook.** Every non-trivial piece of work gets a dated README with steps, status, and notes. Re-reading it a year later is not a "scroll through Slack" exercise — it is a `grep` away.
- **Shared-with-AI-agent workspace.** Claude Code can create projects, close incidents, and add notes just by editing files. No API, no webhook, no permissions — it's just filesystem I/O.
- **Post-mortem tracker.** Incidents with `**Severity**` and `**Environment**` fields, a `## Steps` checklist for the investigation, and a deliverable PDF generated from the same directory.

You do not need the `conception` convention described on the next page to use condash — any directory tree of Markdown READMEs with a `**Status**` field and optional `## Steps` checklists will render. But following the convention means everything (status groups, archives, kanban, `condash tidy`) works with zero config.

## What it does

- **Live dashboard.** Reads the directory tree on every page load. Edit a README in your editor, refresh the window, see the change. No build step, no database.
- **`## Steps` checklists.** Each item's README can declare a `## Steps` section with `[ ]` / `[~]` / `[x]` / `[-]` markers. The dashboard renders them as live checkboxes, toggles via click, and supports drag-and-drop reordering.
- **Status-aware layout.** Items declare `**Status**: now|soon|later|backlog|review|done` in their README header. Kanban view groups by status; `condash tidy` moves `done` items into `YYYY-MM/` archive folders so the active directories stay focused on in-progress work.
- **Open-with slots.** Three vendor-neutral launcher buttons per repo (`main_ide`, `secondary_ide`, `terminal`) with configurable fallback chains — `idea {path}`, `code {path}`, `ghostty --working-directory={path}`, etc. Tried in order until one starts.
- **Repo strip.** If you set `workspace_path`, every direct subdirectory that contains a `.git/` shows up as a card. Primary / secondary / others bucketed via the `[repositories]` config.
- **In-app config editor.** Gear icon in the header opens a modal with form fields for every option. Saves atomically via `tomlkit` (preserves your comments) and reloads the dashboard.
- **Cross-platform.** Linux-first (most tested), macOS and Windows should work. `pywebview` picks the native backend per OS — GTK/WebKit on Linux if available, Cocoa/WebKit on macOS, Edge WebView2 on Windows — and falls back to bundled Qt elsewhere.

## Read in order

The pages below are written to be read top-to-bottom the first time:

1. **[Conception convention](conception-convention.md)** — the directory structure and README format `condash` expects. Start here even if you already have your own tree: this is a short spec that explains why the defaults work.
2. **[Management skill](skill.md)** — a minimal Claude Code skill for creating, listing, and closing conception items by editing files directly. Drop it into `~/.claude/skills/`, then ask Claude to create a project and watch the dashboard pick it up on the next refresh.
3. **[Getting started](getting-started.md)** — end-to-end walkthrough: install `condash`, point it at a starter `conception/` tree, create your first project via the skill, watch it render, close it, run `tidy`, see it archived. Five minutes.
4. **[Reference](reference.md)** — the long form: CLI surface, config keys, how the parser extracts status and steps, how `tidy` decides what to move, how `## Deliverables` is rendered, what the dashboard mutates and what it never touches.

## Links

- [Source on GitHub](https://github.com/vcoeur/condash)
- [`condash` on PyPI](https://pypi.org/project/condash/)
- [Author](https://vcoeur.com)
