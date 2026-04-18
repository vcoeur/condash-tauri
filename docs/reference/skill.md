---
title: Management skill · condash reference
description: Reference for the shipped /conception-items Claude Code skill — actions, arguments, and the files each action writes.
---

# Management skill

## At a glance

`condash` renders items but does not create them. The shipped **[`/conception-items`](https://github.com/vcoeur/condash/tree/main/examples/skills/conception-items)** Claude Code skill covers the creation + update + close lifecycle by editing files directly. It has **no knowledge of the condash CLI or HTTP server** — the two tools meet at the filesystem and nowhere else.

For the learn-by-doing walkthrough, see [tutorials/first-project](../tutorials/first-project.md). For the extension patterns, see [guides/skill-extensions](../guides/skill-extensions.md).

## Actions

Every action is a natural-language verb that the skill parses and translates into a small set of file operations.

| Action | What it writes | Typical arguments |
|---|---|---|
| `create` | New `projects/YYYY-MM/YYYY-MM-DD-slug/README.md` with header + goal + empty `## Steps` + seeded `## Timeline` | title, `Kind`, `Status`, optional `Apps`, optional `Branch` |
| `list` | — (read-only) | filter: `Kind`, `Status`, `Apps`, or a keyword |
| `add-note` | New `projects/<...>/notes/<slug>.md` (creates `notes/` if missing); optionally appends a link to the README's `## Notes` section | parent item, note slug |
| `update` | Line-level edits to `README.md`: step text, step marker, `**Status**:`, appending to `## Timeline` | item slug, update kind |
| `close` | Sets `**Status**: done`, appends a closing line to `## Timeline` | item slug |

The skill deliberately does **not** delete items, does not rename directories, and does not move files between months. Those are manual operations — reviewable in `git diff`.

## Install

The skill file ships in the repo at [`examples/skills/conception-items/SKILL.md`](https://github.com/vcoeur/condash/tree/main/examples/skills/conception-items). Copy it to one of the Claude Code skill locations:

```bash
# Global — available in every session
mkdir -p ~/.claude/skills/conception-items
curl -fsSL https://raw.githubusercontent.com/vcoeur/condash/main/examples/skills/conception-items/SKILL.md \
  -o ~/.claude/skills/conception-items/SKILL.md

# Project-local — auto-loaded inside a specific repo
mkdir -p <repo>/.claude/skills/conception-items
curl -fsSL https://raw.githubusercontent.com/vcoeur/condash/main/examples/skills/conception-items/SKILL.md \
  -o <repo>/.claude/skills/conception-items/SKILL.md
```

Reload skills (or start a new session) and `/conception-items` becomes available.

Set the `CONCEPTION_PATH` environment variable so the skill knows which tree to operate on:

```bash
export CONCEPTION_PATH=~/conception
```

(condash itself does not read `CONCEPTION_PATH` — only the skill does. See [env vars](env.md).)

## Files written per action

| Action | File | Operation |
|---|---|---|
| `create` | `projects/YYYY-MM/YYYY-MM-DD-slug/README.md` | `Write` (whole file, from template) |
| `create` | `projects/YYYY-MM/YYYY-MM-DD-slug/notes/` | `mkdir` (empty directory) |
| `list` | — | none |
| `add-note` | `projects/<...>/notes/<slug>.md` | `Write` |
| `add-note` | `projects/<...>/README.md` | `Edit` (appends to `## Notes` if present; no-op otherwise) |
| `update` (step toggle) | `projects/<...>/README.md` | `Edit` (rewrites one `- [<marker>] <text>` line) |
| `update` (status) | `projects/<...>/README.md` | `Edit` (rewrites `**Status**:` line) |
| `update` (timeline) | `projects/<...>/README.md` | `Edit` (appends a dated line to `## Timeline`) |
| `close` | `projects/<...>/README.md` | `Edit` × 2 — status to `done`, append `## Timeline` entry |

Every operation uses Claude Code's `Write` / `Edit` tools — no shell, no CLI, no direct git. The user reviews changes in `git diff` before committing.

## Slug generation

`create` derives the slug from the title:

1. Lowercase.
2. Replace spaces with dashes.
3. Strip everything outside `[a-z0-9-]`.
4. Prepend today's date: `YYYY-MM-DD-<slug>`.
5. Place under `projects/YYYY-MM/` using today's month.

If the resulting path collides with an existing item, the skill appends `-2`, `-3`, … until it's unique.

## Header emitted by `create`

```markdown
# <Title>

**Date**: <today>
**Kind**: <project | incident | document>
**Status**: <status>
**Apps**: <apps, if provided>
**Branch**: <branch, if provided>

## Goal

<prompt the user for one paragraph>

## Scope

## Steps

## Timeline

- <today> — Project created
```

`## Notes` is not seeded by default — it's added by the first `add-note` call when appending the index link.

## What the skill does not do

| Not included | Why |
|---|---|
| Generate PDFs | Deliverable generation is out of scope — use the [deliverables guide](../guides/deliverables.md) or a dedicated skill. |
| Run `condash`-level CLI commands | The two tools are orthogonal; the skill has no dependency on condash being installed. |
| Move or archive items | Items live at `projects/YYYY-MM/YYYY-MM-DD-slug/` for life. Status flips, directories don't. |
| Create a git branch | Branch isolation is the user's call. Add that as an extension — see [guides/skill-extensions](../guides/skill-extensions.md). |
| Edit the config | Use the dashboard's gear modal, `condash config edit`, or your editor. |

## Extending the shipped skill

The shipped version is intentionally minimal. Typical extensions:

- **Per-kind templates.** Replace the body builder with per-Kind variants (richer for documents, flatter for incidents).
- **Branch + worktree provisioning.** For projects with `**Branch**`, set up a git worktree under `worktrees_path` so the code lives apart from the main checkout.
- **Deliverable generation.** A `generate-deliverable` verb for documents — render Markdown to PDF, update `## Deliverables` to link it.
- **Notes auto-index.** Keep the `## Notes` section in sync with the contents of the `notes/` subdirectory.

Each is a ten-minute extension on top of the base skill. See [guides/skill-extensions](../guides/skill-extensions.md) for worked examples.

## Related

- [Tutorials — first project](../tutorials/first-project.md) — learn-by-doing walkthrough.
- [Guides — extending the skill](../guides/skill-extensions.md) — concrete extension patterns.
- [Mutation model](mutations.md) — the **dashboard's** mutation surface; disjoint from the skill's.
