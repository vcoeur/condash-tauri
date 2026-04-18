---
title: Status, steps, deliverables · condash reference
description: The content-level syntax condash reads out of each README body — step markers, deliverable links, and the folder layout that makes archiving free.
---

# Status, steps, deliverables

## At a glance

Every item is a directory under `projects/YYYY-MM/YYYY-MM-DD-slug/` containing a `README.md`. There is no top-level `incidents/` or `documents/` folder — the `**Kind**` field in the header discriminates. Three body sections are parsed: `## Steps`, `## Deliverables`, and anything whose heading is used by the step-add-by-section flow (`## Timeline`, etc., are left alone).

For the header format, see [README format](readme-format.md).

## Folder layout

```
conception/
├── projects/
│   ├── 2026-04/
│   │   ├── 2026-04-10-auth-rewrite/
│   │   │   ├── README.md
│   │   │   └── notes/
│   │   │       └── investigation.md
│   │   └── 2026-04-14-login-500s/           ← incident, same layout
│   │       └── README.md
│   └── 2026-03/
│       └── 2026-03-22-ci-upgrade/
│           └── README.md
├── knowledge/                                ← optional, explorer tab
│   └── …
└── config/                                   ← repositories.yml + preferences.yml
    └── repositories.yml
```

Rules, enforced or conventional:

| Rule | Enforced by | Notes |
|---|---|---|
| Items live at `projects/YYYY-MM/YYYY-MM-DD-slug/README.md` | parser glob | Anything not matching `projects/*/*/README.md` is invisible. |
| Month folder is `YYYY-MM` | convention | The parser does not validate the folder name, but the wikilink resolver expects it. |
| Item folder starts with `YYYY-MM-DD-` | convention | Dashes; no spaces. The part after the date prefix is the short slug wikilinks resolve against. |
| Kind lives in the body as `**Kind**: …` | convention | Defaults to `project`. No separate directory per kind — they coexist under one month folder. |

The flat-month layout was a deliberate simplification of an earlier `projects/<slug>/` + `projects/YYYY-MM/<slug>/` split. Items never move between active and archive; a `Status: done` flip is the only archive signal, and there's nothing for `condash` to rename. See [why Markdown-first](../explanation/why-markdown.md) for the rationale.

## Status model

Six ordered values, highest-urgency first:

| Value | Meaning |
|---|---|
| `now` | Actively being worked on this week |
| `soon` | Next up; starts within a week or two |
| `later` | Agreed to do, not scheduled |
| `backlog` | Possible; worth keeping, not committed |
| `review` | Work done, awaiting review or verification |
| `done` | Closed. Stays in its `YYYY-MM/` folder indefinitely. |

The parser normalises the value to lowercase and falls back to `backlog` for anything unrecognised. Inside the dashboard, status changes via drag-and-drop rewrite the `**Status**:` line in place — see [mutations](mutations.md).

## Steps

Markdown checklists inside any `##`-level section. The dashboard's default "add step" target is a section literally named `## Steps`, but any section (for instance `## Phase 1`) can carry checkboxes and they all contribute to the item's progress count.

```markdown
## Steps

- [ ] Audit current session-cookie usage
- [~] Implement the hybrid read path
- [ ] Migration script for existing tokens
- [x] Decide on cookie attributes
- [-] Feature flag (abandoned — shipping directly)
```

### Marker map

| Marker | Parsed status | Counted as done? |
|---|---|---|
| `[ ]` | `open` | no |
| `[~]` | `progress` | no |
| `[x]` or `[X]` | `done` | yes |
| `[-]` | `abandoned` | yes |

The dashboard's checkbox-click cycle is `open → done → progress → abandoned → open`, implemented by [`mutations.py::_toggle_checkbox`](https://github.com/vcoeur/condash/blob/main/src/condash/mutations.py).

### Where to put steps

Keep the top-level `## Steps` list **short** — three to eight high-level milestones. Per-file tasks, acceptance criteria, and detailed implementation checklists belong in `notes/<name>.md`, not in the README. The README is the bird's-eye view; the notes folder is the workshop.

### Why no ordering semantics

The parser preserves source order. Drag-and-drop reorder rewrites the affected step lines in place (see [`mutations.py::_reorder_all`](https://github.com/vcoeur/condash/blob/main/src/condash/mutations.py)) — there is no explicit index, priority, or ID on a step. Two steps with identical text are indistinguishable.

## Deliverables

PDF outputs an item produces — technical reports, executive summaries, audits. Declared in a section literally named `## Deliverables`:

```markdown
## Deliverables

- [Technical report](rapport-technique.pdf) — full analysis with code references
- [Executive summary](summary.pdf) — one-page version for stakeholders
```

Strict syntax:

| Piece | Rule |
|---|---|
| Line start | `- [` |
| Label | any text until the next `]` |
| Path | Markdown link target ending in `.pdf`, relative to the item directory |
| Separator | optional em-dash (`—`), en-dash (`–`), or hyphen (`-`) |
| Description | optional free text after the separator |

The parser [`_parse_deliverables`](https://github.com/vcoeur/condash/blob/main/src/condash/parser.py) stops at the next `##` heading. Lines that do not match the pattern are silently skipped — a typo means your PDF disappears from the card, no error.

See [Deliverables and PDFs](../guides/deliverables.md) for the viewer config, the download route, and how the built-in PDF.js previewer kicks in.

## Timeline

An append-only human-facing log. **Not parsed** — the dashboard renders the section as plain Markdown, the same as any other `##` heading. It exists by convention, not by enforcement.

```markdown
## Timeline

- 2026-04-10 — Project created
- 2026-04-12 — Auth audit complete; see notes/investigation.md
- 2026-04-15 — Hybrid read path merged to main
```

One line per event, dated, imperative, linkable. Useful when re-reading the item months later — much cheaper than scrolling through commit history.

## Notes and subdirectories

Anything not in the README goes in `notes/<name>.md` (or any other subdirectory you create from the dashboard — `logs/`, `drafts/`, whatever). The card's **Files** section lists every non-README file in the item directory, grouped by subdirectory up to three levels deep. Hidden entries (leading `.`) and the top-level `README.md` are skipped.

See [mutations](mutations.md) for the create/rename/upload routes, and [Linking items with wikilinks](../guides/wikilinks.md) for the in-note link syntax.

## What is not part of the convention

- **No frontmatter.** YAML / TOML frontmatter is ignored. Use it for your own tooling if you want.
- **No IDs.** The directory name is the identity. No UUIDs, no auto-incrementing counters.
- **No schema version.** The parser is backwards-compatible within a major version; new fields are additive.
- **No lock files.** Everything the dashboard knows is derived from the tree on every request.
- **No `tidy` step.** Earlier versions shipped a `condash tidy` that moved `done` items into archive folders. The current flat-month layout makes it unnecessary — items never move.
