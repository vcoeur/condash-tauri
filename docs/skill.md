---
title: Management skill · condash
description: A minimal Claude Code skill for managing conception items — create, list, close — by editing Markdown files directly. Pair it with condash for a zero-friction project tracker driven from the terminal and your AI agent.
---

# Management skill

`condash` renders a conception tree; it does not manage the items themselves. Creating a new project, adding a note to an incident, or closing a document is a plain file-write: write a new `README.md`, edit an existing one, flip a `**Status**` field. You can do it in your editor, from a shell script, or from a Claude Code session via a skill.

This page ships a minimal Claude Code skill that drives those file operations on your behalf. Pair it with `condash` and you have:

- **Claude Code** creates, lists, and closes items by editing Markdown.
- **`condash`** renders the dashboard on top of the same files.

No API between the two — they just meet at the filesystem.

## What the skill does

`/conception-items` (the slash command the skill installs) takes a natural-language request and translates it into one of four operations:

| Operation | What it does |
|---|---|
| **create** | Write a new `projects/YYYY-MM-DD-slug/README.md`, `incidents/…`, or `documents/…` with the canonical header, a goal, and a `## Steps` checklist. |
| **list** | Scan the tree for items matching a filter (type, status, app, keyword) and print a compact summary. |
| **update** | Add a timeline entry, toggle a step, append a note, change status. |
| **close** | Set `**Status**: done`, add a closing timeline entry. (The next `condash tidy` run will archive it.) |

It deliberately does **not** run `condash tidy`. Archiving is a file-moving operation with non-trivial blast radius; the user should run it intentionally from the dashboard footer or the CLI.

## Install

The skill file ships in the repo at [`examples/skills/conception-items/SKILL.md`](https://github.com/vcoeur/condash/tree/main/examples/skills/conception-items). Drop it into one of the Claude Code skill locations:

```bash
# Globally available
mkdir -p ~/.claude/skills/conception-items
curl -fsSL https://raw.githubusercontent.com/vcoeur/condash/main/examples/skills/conception-items/SKILL.md \
  -o ~/.claude/skills/conception-items/SKILL.md

# Or project-local — auto-loaded only inside a specific repo
mkdir -p <your-project>/.claude/skills/conception-items
curl -fsSL https://raw.githubusercontent.com/vcoeur/condash/main/examples/skills/conception-items/SKILL.md \
  -o <your-project>/.claude/skills/conception-items/SKILL.md
```

Reload skills in Claude Code (or start a new session) and `/conception-items` becomes available as a slash command.

Set the `CONCEPTION_PATH` environment variable (or tell Claude the path explicitly the first time) so the skill knows which tree to operate on:

```bash
export CONCEPTION_PATH=~/conception
```

## A first session

Assume you just copied the starter template from the [Getting started](getting-started.md) page and `condash` is open in the background.

### Create a project

```
You: /conception-items create a project called "add dark mode toggle"
     in the vcoeur.com app, status now

Claude: I'll create the project.
→ write projects/2026-04-15-add-dark-mode-toggle/README.md

Created projects/2026-04-15-add-dark-mode-toggle/ with:
  **Date**: 2026-04-15
  **Status**: now
  **Apps**: `vcoeur.com`
  ## Goal, ## Scope, ## Steps (empty), ## Timeline (seeded)
```

Refresh the `condash` dashboard — the new project card appears in the `now` column.

### List what's active

```
You: /conception-items list active projects

Claude:
→ scan projects/ for items with status != done
now:
  2026-04-15-add-dark-mode-toggle (vcoeur.com)
soon:
  2026-04-10-billing-export (vcoeur.com)
```

### Update a step

```
You: /conception-items mark "audit feedback-form colours" as in progress
     in the dark-mode project

Claude:
→ edit projects/2026-04-15-add-dark-mode-toggle/README.md
   - [ ] Audit feedback-form colours  →  - [~] Audit feedback-form colours
✓ Step updated.
```

Toggle happens immediately. The dashboard's progress count (`0/4` → `1/4` in progress) updates on the next poll.

### Close a project

```
You: /conception-items close the dark-mode project

Claude:
→ edit projects/2026-04-15-add-dark-mode-toggle/README.md
   **Status**: now  →  **Status**: done
   append to ## Timeline: "- 2026-04-15 — Closed"
✓ Closed.
```

The project now shows in the `done` column. Run `condash tidy` (or click the tidy button in the dashboard footer) to move the directory into `projects/2026-04/`.

## How it is implemented

The skill is a handful of file operations wrapped in natural-language routing. The full text is in the repo — read [`examples/skills/conception-items/SKILL.md`](https://github.com/vcoeur/condash/tree/main/examples/skills/conception-items) for the canonical version. The short shape:

- Reads the `CONCEPTION_PATH` environment variable (or accepts an explicit path argument) to locate the tree.
- Uses `Read`, `Write`, and `Edit` for every mutation. No `condash` CLI calls — the skill is an orthogonal thing that only knows about the filesystem.
- For **create**, generates a slug from the title (`lowercase, spaces-to-dashes, strip-punct`) and picks the date from `date +%Y-%m-%d`.
- For **list**, uses `Grep` against `**Status**:` lines under each type folder.
- For **update** and **close**, uses `Edit` to perform the minimum possible rewrite.

## Adapting the skill

The shipped version is intentionally minimal. Things you might want to add when you fork it:

- **Templates.** The skill creates a stock "goal / scope / steps / timeline" README. If you prefer a different template per item type, replace the body builder.
- **Branch isolation.** Projects that touch code should fill in a `**Branch**` field and, optionally, set up a git worktree. The shipped skill does not handle that.
- **Deliverables.** For `documents/`, you might want a "generate a PDF from `rapport-technique.md`" verb. The shipped skill stops at file creation.
- **Notes auto-indexing.** A verb that appends `notes/<slug>.md` and updates the `## Notes` index in the README.

Each of these is a ten-minute extension on top of the base skill. Fork it and keep going.

## Why not just use the dashboard?

The dashboard is for browsing and for quick status toggles. Creating a new item via the dashboard would require a form-based UI, which ties the look-and-feel and the data model together in a way that's hard to version. Keeping creation in a skill (or in your editor, or in a shell script) means:

- The template is a file in your repo, editable like any other file.
- You can create items from any tool that writes files — including shell scripts, CI pipelines, and incident webhooks.
- The dashboard stays a pure view layer, which is the whole point of the approach.

## Next

- **[Getting started](getting-started.md)** — install `condash`, copy the starter tree, install this skill, run through the full lifecycle from an empty directory to an archived project.
- **[Reference](reference.md)** — the CLI surface, config keys, parser internals, and how `tidy` decides what to move.
