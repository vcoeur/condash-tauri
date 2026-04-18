# Knowledge

Permanent reference material for the helio project. Stable facts, conventions, cross-cutting topics — not time-bound project work.

## Root body files

`conventions.md` is the only body file permitted at the tree root; everything else lives under a subdir.

- [`conventions.md`](conventions.md) — *durable team rules: commit style, branch naming, PR hygiene, review expectations; stable by design.* `[conventions, team-rules, commits, branches, pr-review]`

## Structure

Each subdirectory has its own `index.md` describing what goes there and listing its current files.

- [`topics/`](topics/index.md) — *cross-cutting subjects that span more than one repo: performance guidance, release checklist.* `[cross-cutting, performance, releases]`
- [`internal/`](internal/index.md) — *per-repo conception-side knowledge for `helio`, `helio-web`, `helio-docs`. Each file links back to that repo's own `CLAUDE.md` and captures anything that is weird to handle from the sandbox.* `[apps, helio, helio-web, helio-docs]`

## Read rules

Consult `knowledge/` whenever the request touches something it could cover. Start at this file, walk to a sub-index, open a body file only when tags or description match.
