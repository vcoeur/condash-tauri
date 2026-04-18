# Conventions

Durable team rules for the helio project. Each entry is a claim, with **Why** (the rationale) and **How to apply** (when and where it kicks in).

---

## Commits

### Imperative mood, no trailing period, ≤72 characters in the subject

Every commit subject starts with an imperative verb (`Add`, `Fix`, `Refactor`, `Drop`) and fits in 72 characters, no trailing period.

**Why:** the subject is how commits show up in `git log --oneline`, release notes, and GitHub Release pages. Consistency across the three repos means release tooling can treat them identically.

**How to apply:**

- `Fix search OOM on corpora above 800 MB` — good.
- `fixed a bug` — not specific, not imperative.
- `Fix search OOM on corpora above 800 MB by capping the candidate-range collection and sliding the mmap window over postings.bin.` — too long; move the body into the commit body after a blank line.

### Commit body explains the **why**, not the **what**

The diff shows what changed. The body should say why the change is worth making — incident reproduced, user feedback, measurement, etc.

**Why:** future readers rebuilding context from `git log` find "why" much harder to reconstruct than "what".

**How to apply:** if the body is a paraphrase of the diff, delete it.

---

## Branches

### One branch per conception item, named `<prefix>/<slug>`

Active work lives on a branch named after the conception item. Prefixes:

- `search/` for search-related work.
- `config/` for configuration work.
- `plugin/` for plugin-API work.
- `fix/` for incident branches.
- `release/` for release branches.
- `docs/` for docs-only work.

**Why:** grepping `git branch -a` by prefix gives an instant view of what is in flight in each area, and the slug links straight back to the conception folder.

**How to apply:**

- Conception item `2026-04-02-fuzzy-search-v2` → branch `search/fuzzy-v2`.
- Incident `2026-04-08-search-crash-large-logs` → could reasonably live on the same `search/fuzzy-v2` branch (a bug in that codepath), or on a separate `fix/search-large-log-oom` branch if the fix is landing independently.

---

## Pull requests

### PR title = conception item title

The PR title matches the conception item's `# Title` header. The body links back to `projects/YYYY-MM/YYYY-MM-DD-slug/README.md` on the main branch and summarises what actually shipped (since a PR often ships a subset of the item's total scope).

**Why:** one-to-one mapping between "item you were asked about" and "PR that landed it" makes auditing trivial.

**How to apply:** use `/pr` from inside the worktree — it already picks the item README and fills this in.

### Every PR body has a "Test plan" section

Even one-liner PRs. For docs-only PRs the test plan may be a single checkbox ("Preview renders correctly"), but the section must exist.

**Why:** forces a moment of "how do I know this works?" before clicking the button.

**How to apply:** the `/pr` skill emits a Test plan section automatically. If you hand-write a PR, copy the shape.

---

## Review

### Review your own PR first

Before asking for review, walk the diff in the GitHub UI as if it were somebody else's. Catch typos, stale comments, accidentally-committed `print()` statements, TODOs you meant to fix.

**Why:** round-trip latency on asynchronous review is the most expensive part of merging. Every comment a reviewer has to leave that you could have caught yourself buys a day.

**How to apply:** if you catch something in self-review, fix it in a fixup commit with a clear message — do not amend silently once the PR is open.
