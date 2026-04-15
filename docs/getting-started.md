---
title: Getting started · condash
description: Install condash, copy the starter conception tree, install the management skill, and run through a full project lifecycle — from creation to archive — in five minutes.
---

# Getting started

End-to-end walkthrough: install `condash`, point it at a starter tree, install the management skill, create a project via Claude Code, watch the dashboard render it, close it, archive it. Five minutes from a fresh machine.

## 1. Install condash

```bash
pipx install condash
# or: uv tool install condash
```

`condash` bundles its native-window backend (`pywebview[qt]` → `PyQt6` + `PyQt6-WebEngine`) as a Python dependency, so a vanilla install is self-contained on Linux, macOS, and Windows. No system Qt or GTK install required. Install size is around 100 MB; the trade is "works everywhere with one command".

Verify:

```bash
condash --version
```

If `command not found`, run `pipx ensurepath` and reopen the shell.

## 2. Seed a starter conception tree

The repo ships a minimum working tree at [`examples/conception-starter/`](https://github.com/vcoeur/condash/tree/main/examples/conception-starter) — three items (one project, one incident, one document) plus a short README explaining the convention. Copy it to a working location:

```bash
mkdir -p ~/conception
curl -fsSL https://codeload.github.com/vcoeur/condash/tar.gz/main \
  | tar -xz --strip-components=2 -C ~/conception \
      condash-main/examples/conception-starter
```

Or, if you already have the condash source checked out:

```bash
cp -r ~/src/condash/examples/conception-starter/* ~/conception/
```

Inspect what you got:

```
~/conception/
├── README.md
├── projects/
│   └── 2026-04-15-first-project/
│       └── README.md
├── incidents/
│   └── 2026-04-15-first-incident/
│       └── README.md
└── documents/
    └── 2026-04-15-first-document/
        └── README.md
```

## 3. Bootstrap the condash config

```bash
condash init
condash config edit         # opens ~/.config/condash/config.toml in $VISUAL / $EDITOR
```

Uncomment and set `conception_path`:

```toml
conception_path = "/home/<you>/conception"
```

Everything else is optional for this walkthrough — leave `workspace_path`, `[repositories]`, and the `[open_with]` sections commented out. You can configure them later from the in-app gear icon once the dashboard is running.

## 4. Launch the dashboard

```bash
condash
```

A native window opens. You should see three cards:

- **Projects** → "First project" (status `now`)
- **Incidents** → "First incident" (status `now`)
- **Documents** → "First document" (status `review`)

Click any card to expand the item. Each one has a `## Steps` checklist you can toggle by clicking the checkboxes. Try flipping one and watch the progress counter update in the header.

## 5. Install the management skill

`condash` does not create or close items itself — it renders what it finds. For creating, updating, and closing items from a Claude Code session, install the minimal skill shipped alongside the starter tree:

```bash
mkdir -p ~/.claude/skills/conception-items
curl -fsSL https://raw.githubusercontent.com/vcoeur/condash/main/examples/skills/conception-items/SKILL.md \
  -o ~/.claude/skills/conception-items/SKILL.md
```

Set an environment variable so the skill knows which tree to manage:

```bash
export CONCEPTION_PATH=~/conception
```

(Persist it in your shell rc file if you want it available in every session.)

Reload Claude Code and confirm `/conception-items` is available.

## 6. Create a project via the skill

In a Claude Code session:

```
You: /conception-items create a project called "Add dark mode toggle"
     in the vcoeur.com app, status now, with three steps:
     audit colours, wire the toggle, ship

Claude:
→ write projects/2026-04-15-add-dark-mode-toggle/README.md
✓ Created projects/2026-04-15-add-dark-mode-toggle/
```

Switch back to the `condash` window and refresh (Ctrl-R on Linux/Windows, Cmd-R on macOS, or click the refresh icon). The new project appears in the `now` column.

The skill wrote a file. `condash` read the file. That is the entire integration between the two.

## 7. Progress and close the project

Mark the first step as in-progress:

```
You: /conception-items mark "Audit colours" as in progress
     in the dark-mode project
```

Refresh the dashboard — the progress counter shows `0 done, 1 in progress`.

Mark everything done and close the project:

```
You: /conception-items mark all steps done in the dark-mode project,
     then close it
```

Refresh. The project is now in the `done` column.

## 8. Archive with `tidy`

Click the **tidy** button in the dashboard footer (or run `condash tidy` from a shell). The "Add dark mode toggle" directory moves from:

```
projects/2026-04-15-add-dark-mode-toggle/
```

to:

```
projects/2026-04/2026-04-15-add-dark-mode-toggle/
```

The dashboard re-renders without the done item in the active columns; it still exists under the archive and a search will still find it.

That is the full lifecycle — create, progress, close, archive — all on plain files, with `condash` as the view layer and a Claude Code skill as the write layer. You never had to leave the terminal and your AI agent.

## What to do next

- Replace the starter tree with your own. The convention is short — re-read [Conception convention](conception-convention.md) as you go.
- Configure the repo strip: set `workspace_path = "/path/to/your/code"` in the config, restart `condash`, and the dashboard gains a card for every `.git/` directory found under that path, with the three `[open_with]` buttons on each.
- Fork the management skill and add the operations you find yourself doing repeatedly — custom templates, note indexing, deliverable scaffolding.
- Open the [Reference](reference.md) when you need to know exactly what the parser accepts, how `tidy` decides what to move, or how to configure the open-with slots.

## Troubleshooting

- **Dashboard shows an empty tree.** `conception_path` is wrong or points to a directory that does not contain `projects/`, `incidents/`, or `documents/`. Check `condash config show`.
- **`/conception-items` is not available in Claude Code.** The skill file is not being picked up. Confirm the path is exactly `~/.claude/skills/conception-items/SKILL.md`, then restart Claude Code.
- **The native window fails to open on Linux.** `pywebview` cannot find a backend. Set `native = false` in the config and `condash` will serve the dashboard in your browser at `http://127.0.0.1:<port>` instead.
- **`condash tidy` moves nothing.** No items at the top level have `**Status**: done`. Tidy is idempotent — running it on a clean tree is a no-op.
