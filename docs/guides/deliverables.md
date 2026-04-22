---
title: Deliverables and PDFs · condash guide
description: The `## Deliverables` section syntax, filename conventions, PDF generation, the in-app PDF viewer, and how to override it.
---

# Deliverables and PDFs

**When to read this.** Your item produces a tangible output — a report, a design doc, an incident post-mortem — and you want it to show up on the card with a download link and an embedded viewer.

Deliverables are a first-class concept: a `## Deliverables` section in a README lists one or more PDF files, and condash renders a download badge on the card plus a viewer in the expanded card.

## The `## Deliverables` section

Add to your README:

```markdown
## Deliverables

- [Plugin API proposal — current draft](deliverables/plugin-api-proposal.pdf) — Distributed to the team for review, 2026-04-15.
- [Appendix A: risks](deliverables/plugin-api-proposal-appendix-a.pdf)
```

Per line:

```markdown
- [<label>](<path>.pdf) — <optional description>
```

- **Label** — text shown on the card and in the viewer header.
- **Path** — relative to the item's directory. Must end in `.pdf`.
- **Description** (optional, after ` — `) — a one-line note shown under the label.

Multiple deliverables per item are fine; each gets its own card row.

## Filename convention

Place PDFs under `<item>/deliverables/`. The directory exists for exactly this: to separate generated outputs from editable notes. condash scans the filesystem lazily, so the directory only needs to exist when at least one deliverable is linked.

Slug the filename to match the item: `<item-slug>.pdf` for the primary deliverable, `<item-slug>-<suffix>.pdf` for secondary ones. This keeps them discoverable in bare `ls` listings without peeking inside each item.

## What the card looks like

![An item card with a Deliverables section and a PDF download link](../assets/screenshots/item-document-with-pdf-light.png#only-light)
![An item card with a Deliverables section and a PDF download link](../assets/screenshots/item-document-with-pdf-dark.png#only-dark)

- A **PDF badge** on the collapsed card tells you "this item has a deliverable".
- Expanded, the **Deliverables** section lists every entry with its label and description.
- Clicking a label opens the file in an embedded PDF viewer modal.
- A **Download** icon next to the label saves the PDF to your OS.

The embedded viewer uses pdf.js, vendored under `frontend/vendor/pdfjs/`. No external dependency; the viewer works offline.

## Generating the PDF

condash doesn't generate PDFs — you do, from whatever source lives alongside the item. The common shape:

- Write the body as Markdown under `<item>/notes/<name>.md`.
- Convert with `~/.claude/scripts/md_to_pdf.sh` (pandoc + xelatex + mermaid-filter):

```bash
cd <conception_path>/projects/2026-04/2026-04-08-plugin-api-proposal
bash ~/.claude/scripts/md_to_pdf.sh notes/draft.md deliverables/plugin-api-proposal.pdf
```

The script handles heading-level shifts, section numbering, Mermaid diagrams, and French accents. See the global `CLAUDE.md` in your home directory for the full recipe.

Refresh the dashboard; the PDF badge lights up and the viewer picks up the file. No extra registration step.

## Overriding the viewer

If you'd rather open PDFs in your OS-native viewer (Evince, Okular, Preview, Sumatra, …), configure the `pdf_viewer` fallback chain in `preferences.yml`:

```yaml
pdf_viewer:
  - xdg-open {path}
  - evince {path}
```

Rules:

- The value is a **bare list** of `"<command> {path}"` strings. Not `pdf_viewer.commands = [...]` — that shape was considered and rejected; condash errors on startup if it sees a nested object.
- Commands are tried in order; the first one whose binary resolves on `$PATH` wins.
- `{path}` is the absolute path of the PDF.
- With `pdf_viewer` set, clicking the label still opens the embedded viewer, but the viewer's **Open externally** button uses your chain. If you set `pdf_viewer` to an empty list (or omit it), the button falls back to `xdg-open` / OS default.

To remove the embedded viewer entirely and go straight to the external chain: not currently supported — the embedded viewer is the default and you go external on a per-click basis.

## Deliverable lifecycle

Items that ship a deliverable go through a pattern:

1. **Early** — `## Deliverables` section exists but is empty or links to a stub PDF that says "draft pending".
2. **Review** — regenerate the PDF from the latest Markdown; status moves to `review`; share the PDF with reviewers.
3. **Final** — one last regeneration after review comments land; status moves to `done`.

If the deliverable is a living document (a standards doc, a runbook), skip the `done` status — leave the item in `review` and keep regenerating when needed. The status model is yours to interpret.

Do **not** check multiple versioned PDFs into the deliverables directory (`…-v1.pdf`, `…-v2.pdf`). Keep one canonical filename and rely on git for history. The card renders every `.pdf` file listed in the section, not every file on disk.

## Next

- [Search your history](search.md) — note that PDF **content** is not indexed, only the filename. Keep the source Markdown in `notes/` if you want the text searchable.
