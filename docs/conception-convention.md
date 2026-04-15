---
title: Conception convention · condash
description: The directory structure, README template, and status model condash expects. Projects, incidents, documents — all as plain Markdown files, live-rendered by the dashboard.
---

# Conception convention

`condash` parses a directory tree of Markdown READMEs into three item types — **projects**, **incidents**, and **documents** — then renders them as a live dashboard. This page is the short specification the parser follows. Copy the layout, and everything else in the docs (the skill, the getting-started walkthrough, `condash tidy`, the kanban view) works without further configuration.

## The three item types

| Type | Folder | Purpose |
|---|---|---|
| **Projects** | `projects/` | Planned work — features, improvements, migrations, anything with a clear outcome |
| **Incidents** | `incidents/` | Bugs, outages, surprises, anything reactive that needs investigating and fixing |
| **Documents** | `documents/` | Plans, investigations, research reports, audits — deliverable-shaped work |

The split matters because each type has a different lifecycle. Projects progress through statuses and eventually ship. Incidents get triaged, fixed, written up, closed. Documents are typically drafted, reviewed, and published once. The dashboard groups items by type and by status so you can see the three at a glance.

## Folder layout

```
conception/
├── projects/
│   ├── 2026-04-10-auth-rewrite/
│   │   ├── README.md
│   │   └── notes/
│   │       └── investigation.md
│   ├── 2026-04-15-billing-export/
│   │   └── README.md
│   └── 2026-03/                        ← done items grouped by month
│       └── 2026-03-22-ci-upgrade/
│           └── README.md
├── incidents/
│   ├── 2026-04-14-login-500s/
│   │   └── README.md
│   └── 2026-02/
│       └── 2026-02-08-backup-restore-fails/
│           └── README.md
└── documents/
    ├── 2026-04-01-gdpr-audit/
    │   ├── README.md
    │   ├── rapport-technique.md
    │   ├── rapport-technique.pdf
    │   └── notes/
    │       └── sources.md
    └── 2026-01/
        └── 2026-01-15-stack-comparison/
            └── README.md
```

Rules:

- Each item is a **directory**, not a single `.md` file. The directory name starts with `YYYY-MM-DD-` and continues with a URL-safe slug.
- Each item directory must contain a `README.md`. Everything else (`notes/`, `*.pdf`, extra markdown files) is optional and ignored by the parser unless referenced from the README.
- **Active items** (anything with `Status` != `done`) live at the top level of their type folder.
- **Done items** are grouped into `YYYY-MM/` subfolders by the month they were closed. `condash tidy` does this automatically — you do not move them by hand.

## README header

Every item's `README.md` starts with a header of bold-key metadata fields, one per line:

```markdown
# Migrate auth to session-cookie hybrid

**Date**: 2026-04-10
**Status**: now
**Apps**: `notes.vcoeur.com`, `vcoeur.com`
**Branch**: `feat/session-cookie-auth`
```

Required:

- **Date** — ISO `YYYY-MM-DD`. Usually matches the directory's date prefix, but the field is authoritative when the two disagree.
- **Status** — one of `now`, `soon`, `later`, `backlog`, `review`, `done`. See the [status model](#status-model) below.

Optional (common):

- **Apps** — backtick-delimited, comma-separated list of affected apps or repositories. Used by the dashboard to filter items to a single repo.
- **Branch** — the git branch used for the code changes, if the item involves code. When set, enforces a branch-isolation rule (edit the code under the worktree, not the main checkout).

Incident-specific:

- **Environment** — `prod` / `staging` / `dev` / `all`.
- **Severity** — free-form; `sev-1`, `major`, `minor`, etc.

Document-specific:

- **Languages** — override the default output language for deliverables (`en`, `fr`, etc.).

The parser is permissive about field order and about which fields are present — only `Status` is strictly required for the dashboard to render an item.

## Status model

Statuses are ordered by urgency. The dashboard's kanban view groups items by status in this order:

| Status | Meaning |
|---|---|
| `now` | Actively being worked on this week |
| `soon` | Next up; will start within a week or two |
| `later` | Agreed to do, not scheduled yet |
| `backlog` | Possible; worth keeping, not committed |
| `review` | Work done, waiting on review or verification |
| `done` | Closed. `condash tidy` will move it into `YYYY-MM/` on the next run |

Any value that is not in this list is treated as `backlog` (the parser falls back silently rather than refusing to render the item).

## Steps — live checklists

Items can declare a `## Steps` section with Markdown checklist items. The dashboard renders each item as a live checkbox, lets you toggle it by clicking, and shows a done/total progress count in the item header.

```markdown
## Steps

- [ ] Audit current session-cookie usage across the stack
- [~] Implement the hybrid read path
- [ ] Migration script for existing tokens
- [x] Decide on cookie attributes
- [-] Add a feature flag (abandoned — decided to ship directly)
```

Recognised markers:

| Marker | Status |
|---|---|
| `[ ]` | open |
| `[~]` | in progress |
| `[x]` or `[X]` | done |
| `[-]` | abandoned |

Keep the `## Steps` list **short** — three to eight high-level milestones. Per-file tasks, acceptance criteria, implementation checklists, and everything else detail-shaped go in `notes/<name>.md`, not in the README. The README is the bird's-eye view; the notes folder is the workshop.

## Timeline

An append-only log of meaningful events on the item. The dashboard does not render this specially — it's for humans re-reading the item later.

```markdown
## Timeline

- 2026-04-10 — Project created
- 2026-04-12 — Auth audit complete; see notes/investigation.md
- 2026-04-15 — Hybrid read path merged to main
```

One line per event, dated, imperative, linkable.

## Notes

Anything that does not belong in the README itself goes in a `notes/` subdirectory. Reference it from a `## Notes` section so it is discoverable:

```markdown
## Notes

- [`notes/investigation.md`](notes/investigation.md) — audit of every place session cookies are read
- [`notes/cookie-attrs.md`](notes/cookie-attrs.md) — decision record for `SameSite=Lax` + `Secure`
```

The dashboard does not parse the notes themselves — they are just files. But keeping the index in the README means you can grep for an item and find everything linked to it in one pass.

## Deliverables — optional

Documents (and occasionally projects) may produce PDF deliverables: a technical report, an executive summary, a legal audit. Declare them in a `## Deliverables` section:

```markdown
## Deliverables

- [Technical report](rapport-technique.pdf) — full analysis with code references
- [Executive summary](summary.pdf) — one-page version for stakeholders
```

The dashboard parses this section and renders each bullet as a download link in the item card. The format is strict: every line must be a Markdown link to a `.pdf` file (path relative to the item directory), optionally followed by an em-dash and a short description.

## Done-item grouping

When an item's `**Status**` flips to `done`, it should be moved into a `YYYY-MM/` subfolder of its type, keyed by the month of closure. The archived layout for a `projects/` item:

```
projects/
├── 2026-04-20-new-feature/       ← still active (status != done)
└── 2026-03/
    ├── 2026-03-05-other-feature/
    └── 2026-03-22-ci-upgrade/
```

You never do this move manually. Run `condash tidy` (or click the tidy button in the dashboard footer) and it walks the tree, finds every item at the top level whose status is `done`, and moves it into the right `YYYY-MM/` bucket. Items that bounce back to active (`done` → `now`) get moved back out on the next tidy run.

## Starter template

A minimum working `conception/` tree lives at [`examples/conception-starter/`](https://github.com/vcoeur/condash/tree/main/examples/conception-starter) in the repo. Three items — one project, one incident, one document — plus a short README. Copy it to `~/conception/` (or wherever you want), point `condash` at it, and you have a functioning dashboard in under a minute. The [Getting started](getting-started.md) walkthrough uses this template.

## What condash does NOT require

- **No frontmatter.** Fields live in the body as bold-key metadata lines. You can still use YAML frontmatter for your own tooling — the parser ignores it.
- **No IDs, no UUIDs.** The directory name is the identity.
- **No schema version.** If `condash` upgrades the format, it stays backwards-compatible with existing trees or ships a migration. You should never have to touch READMEs because of a condash release.
- **No lock files, no state files.** Everything the dashboard knows is derived from the tree on every request.

The convention on this page is deliberately the smallest thing that gives you live status, progress, and archiving. Add more structure only when the plain version stops being enough.

## Next

- **[Management skill](skill.md)** — how to create, list, and close items from a Claude Code session without remembering the template by hand.
- **[Getting started](getting-started.md)** — install `condash`, point it at the starter tree, run through a full lifecycle.
