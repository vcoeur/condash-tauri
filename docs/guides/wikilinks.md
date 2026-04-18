---
title: Link items with wikilinks · condash guide
description: Cross-link items with `[[slug]]` syntax, resolve by short name or by dated directory, and target knowledge files too.
---

# Link items with wikilinks

**When to read this.** You want one item's README or note to point at another item, without copy-pasting a path that breaks the moment the item moves.

condash resolves `[[slug]]`-style wikilinks (Obsidian-style) inside README bodies and inside notes. The resolver is deliberately narrow: it works on item slugs, not on arbitrary paths, so the link survives a move between months.

## Syntax

Two shapes:

```markdown
See [[fuzzy-search-v2]] for the related work.

We're extracting benchmarks into [[helio-benchmark-harness|the shared harness]].
```

- `[[target]]` — the rendered label is the target itself.
- `[[target|label]]` — the rendered label is whatever follows the pipe.

Target is case-sensitive and trimmed. Whitespace inside the target is not collapsed; `[[helio benchmark]]` looks for a directory containing "helio benchmark", not "helio-benchmark".

## Resolution rules

For `[[target]]`, condash walks `projects/*/` and, for each `YYYY-MM/` month directory, looks at every item directory inside. A directory matches if either:

- Its full name equals the target (e.g. `[[2026-04-02-fuzzy-search-v2]]`), or
- Its name has the `YYYY-MM-DD-` prefix stripped off and equals the target (e.g. `[[fuzzy-search-v2]]` matches `2026-04-02-fuzzy-search-v2`).

If multiple items match the short form — you created two items with the same slug in different months — condash picks the **most recent**, sorted by the date prefix. This is usually what you want: the active item is more likely to be the target than last year's predecessor.

The second short form (without the date prefix) is what you'll use 99% of the time. The dated form is there for the rare case where you need to disambiguate explicitly.

## Linking into the knowledge tree

Wikilinks also resolve into the `knowledge/` tree. Targets of the form `[[knowledge/topics/playwright-sandbox]]` resolve to `knowledge/topics/playwright-sandbox.md` (the `.md` suffix is optional).

Short forms work there too: `[[playwright-sandbox]]` resolves to `knowledge/topics/playwright-sandbox.md` if no item has that slug, because the resolver falls through to scanning `knowledge/topics/`, `knowledge/internal/`, and `knowledge/external/` in that order.

## Legacy prefix forms

Before the unified `projects/` layout, items lived under `incidents/` and `documents/` too. The resolver still accepts:

- `[[project/<slug>]]`, `[[projects/<slug>]]`
- `[[incident/<slug>]]`, `[[incidents/<slug>]]`
- `[[document/<slug>]]`, `[[documents/<slug>]]`

All three route through the same `projects/` tree. Keep them around if you're migrating notes from an older tree; prefer bare `[[slug]]` for anything new.

## Where wikilinks work

- **README bodies** — anywhere in the free-text sections (Goal, Scope, Timeline, …) and inside step text.
- **Note bodies** — every `.md` file under `<item>/notes/`.
- **Knowledge-tree files** — any `.md` under `knowledge/`.

Wikilinks do **not** work inside YAML/TOML config, inside filenames, or inside the `**Key**: value` header block of a README. They're a body-only feature.

## What a missing link looks like

If the resolver can't find a target, the link still renders — but without a URL, and with a tooltip that tells you what was looked up:

```markdown
See [[benchmark-harness-v3]] for the v3 design.
```

Renders as a greyed-out span with `title="Wikilink target not found: benchmark-harness-v3"`. Hover to confirm you're looking at a typo vs. a real missing item.

## A worked example

The demo tree has several cross-linked items. From `fuzzy-search-v2`'s `notes/design.md`:

```markdown
> See also: [[helio-benchmark-harness]] — the shared harness we're extracting
> the parser benchmarks into.
```

This link resolves to `projects/2026-04/2026-04-18-helio-benchmark-harness/README.md`. In the dashboard, clicking the link opens that item's card directly — no URL to copy, no path to update if the item moves to a different month.

The other direction, from `helio-benchmark-harness`'s README:

```markdown
- [ ] Document the harness in [[fuzzy-search-v2|the fuzzy-search item]] so
      that item's benchmarking notes stop living in a standalone file.
```

Two wikilinks, both short-form, both resolve. The pipe-label variant keeps the step readable while the link still points at the canonical target.

## Interaction with Markdown syntax

Wikilinks are a preprocessing step that runs before pandoc sees the body — each `[[…]]` match is rewritten to a raw-HTML `<a class="wikilink">` anchor, which pandoc's GFM reader passes through untouched. Consequences:

- You can freely mix `[regular markdown](links)` and `[[wikilinks]]` on the same line.
- You can't escape `[[` inside a wikilink target — if you need literal `[[` somewhere, wrap it in a code span (`` `[[not a link]]` ``).
- Wikilinks inside fenced code blocks are left as literal text.

## Next

- Cross-linking is most useful in notes; see [Your first project](../tutorials/first-project.md) for the full notes-editing surface.
- To link out to specific reference material instead of other items, see [The knowledge tree](knowledge-tree.md).
