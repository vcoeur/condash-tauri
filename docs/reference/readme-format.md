---
title: README format · condash reference
description: The header fields condash reads from each item's README.md — types, allowed values, kind-specific extras.
---

# README format

## At a glance

Every item lives at `projects/YYYY-MM/YYYY-MM-DD-slug/README.md`. The first line is the title (`# …`); everything from line 2 up to the first `##` heading is the **header**, a sequence of `**Key**: value` lines.

| Field | Required | Applies to | Notes |
|---|---|---|---|
| `**Date**` | no | all | ISO `YYYY-MM-DD`. Defaults to the directory's date prefix when missing. |
| `**Kind**` | no | all | `project` / `incident` / `document`. Defaults to `project`. |
| `**Status**` | **yes** | all | `now` / `soon` / `later` / `backlog` / `review` / `done`. Unknown values coerce to `backlog`, log a parser warning, and surface a `!?` badge on the card. |
| `**Apps**` | no | all | Comma-separated backtick-wrapped app names. Powers the per-app filter. |
| `**Branch**` | no | projects | Git branch name. Hints the `/pr` skill + worktree isolation rules. |
| `**Base**` | no | projects | Base branch for `/pr`. Defaults to `origin/HEAD`. |
| `**Environment**` | no | incidents | `prod` / `staging` / `dev` / `all`. Free-form — not validated. |
| `**Severity**` | no | incidents | Free-form: `sev-1`, `major`, `minor`, … |
| `**Languages**` | no | documents | Output language for deliverables. `en` / `fr` / … |

Field names are case-insensitive; values are trimmed. Order inside the header block does not matter. Unknown fields are silently ignored — safe to add your own.

## Header parsing

The parser ([`crates/condash-parser/src/readme.rs`](https://github.com/vcoeur/condash/blob/main/crates/condash-parser/src/readme.rs)) scans every line between the title and the first `##` heading. A line is treated as metadata if it matches `**<Key>**: <value>`. The first blank line is not a terminator — only the first `##` heading is.

```markdown
# Helio benchmark harness

**Date**: 2026-04-18
**Kind**: project
**Status**: now
**Apps**: `helio`
**Branch**: `feat/bench-harness`

## Goal
…
```

Output of the parse, as consumed by the rest of the package:

- `title` — the first-line `# <text>`, else the directory name.
- `date`, `kind`, `status` (aka `priority`), `apps`, `severity` — typed fields.
- `summary` — first paragraph after the first `##` heading, truncated to 300 chars.
- `sections` — every `## <heading>` with checkboxes under it (see [conception convention](conception-convention.md)).
- `deliverables` — every `## Deliverables` link to a `.pdf` (see [conception convention](conception-convention.md)).

## Examples

### Project

```markdown
# Migrate auth to session-cookie hybrid

**Date**: 2026-04-10
**Kind**: project
**Status**: now
**Apps**: `notes.vcoeur.com`, `vcoeur.com`
**Branch**: `feat/session-cookie-auth`
**Base**: `main`

## Goal

One-paragraph intent. Becomes the card summary.

## Scope
…
## Steps
- [ ] Audit current session-cookie usage
- [~] Implement hybrid read path
- [x] Decide cookie attributes

## Timeline
- 2026-04-10 — Project created
```

### Incident

```markdown
# Login returns 500 under concurrent load

**Date**: 2026-04-14
**Kind**: incident
**Status**: review
**Apps**: `vcoeur.com`
**Environment**: prod
**Severity**: sev-2

## Summary

First paragraph is the card summary. Keep it one sentence for the dashboard.

## Timeline
- 2026-04-14 11:04 — Pager fires
- 2026-04-14 11:42 — Rollback to previous release
- 2026-04-14 14:20 — Root cause: connection pool exhaustion
```

`**Environment**` and `**Severity**` are incident-only in convention, but the parser will accept them on any kind. Nothing enforces the type split — the dashboard simply renders whatever it finds.

### Document

```markdown
# GDPR audit — 2026 spring review

**Date**: 2026-04-01
**Kind**: document
**Status**: review
**Apps**: `notes.vcoeur.com`, `vcoeur.com`, `alicepeintures.com`
**Languages**: `fr`, `en`

## Deliverables

- [Rapport technique](rapport-technique.pdf) — full French version with code references
- [Executive summary](summary-en.pdf) — one-page English abridgement
```

## Status

Six values, in this exact order:

```
now → soon → later → backlog → review → done
```

Anything outside this set is **coerced to `backlog`** with two side-effects so the typo doesn't slip past you:

- The parser logs a `WARNING` with the offending value and the item's path, e.g. `unknown Status 'wip' in projects/2026-04/2026-04-17-foo/README.md — coerced to 'backlog'`.
- The card renders a red **`!? <value>`** badge next to the status pill, with a tooltip showing the valid enum. It disappears as soon as the README is fixed — the next poll cycle re-parses, finds a valid Status, and drops the badge.

![Backlog card showing a red `!? WIP` badge next to its status pill](../assets/screenshots/status-unknown-badge-light.png#only-light)
![Backlog card showing a red `!? WIP` badge next to its status pill](../assets/screenshots/status-unknown-badge-dark.png#only-dark)

Without the badge, a typo like `active` would silently land in the `backlog` column; with it, the item sticks out visibly until corrected.

See [conception convention](conception-convention.md) for the status model and what each value means.

## Apps

Parsed as comma-separated. Backticks and trailing `(…)` parentheticals are stripped, so `` `vcoeur.com` (frontend) `` becomes `vcoeur.com`. Resulting list is used by the dashboard's per-app filter chips.

```markdown
**Apps**: `vcoeur.com`, `notes.vcoeur.com`, `condash`
```

## Body conventions

Header fields only describe the item's metadata. The body (everything after the first `##`) carries the content — goal, scope, steps, timeline, deliverables, notes. See:

- [conception convention](conception-convention.md) — the required and conventional `##` sections.
- [Linking items with wikilinks](../guides/wikilinks.md) — `[[slug]]` / `[[slug|label]]` syntax inside the body and notes.
- [Deliverables and PDFs](../guides/deliverables.md) — the PDF link pattern the dashboard recognises.

## What the parser never looks at

- YAML or TOML frontmatter — treated as opaque text. Safe to use for your own tooling.
- `##` sections other than `Steps` and `Deliverables` — rendered verbatim as Markdown; not parsed for structure.
- `notes/` subdirectories — indexed as files under the card but never mined for metadata.
- Any file in the item directory other than `README.md`.
