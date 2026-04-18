# conception-demo

A throwaway conception tree used purely to generate screenshots for the condash documentation overhaul. Nothing here refers to real work — it describes an imaginary CLI project called **helio** and its two companions (`helio-web`, `helio-docs`).

The tree intentionally exercises every condash surface:

- Projects across two months (`2026-03`, `2026-04`) covering all six statuses: `now`, `soon`, `later`, `backlog`, `review`, `done`.
- All three item kinds: `project`, `incident`, `document`.
- Items with and without `**Branch**`, single-app and multi-app.
- Step lists combining `[ ]`, `[~]`, `[x]`, and `[-]` markers.
- Deliverable PDFs (placeholder files) surfaced in the Deliverables section.
- Wikilinks (`[[slug]]` / `[[slug|label]]`) cross-linking projects to incidents and documents.
- A `knowledge/` tree with `conventions.md`, per-topic files, and per-repo internal files.
- `config/repositories.yml` and `config/preferences.yml` shaped exactly like the real conception config.

## Pointing condash at this tree

```bash
condash --conception-path /path/to/condash/examples/conception-demo
```

Or launch condash and use the gear modal to set the conception path to this directory.

The `config/repositories.yml` here points `workspace_path` at `/tmp/conception-demo-workspace` so condash never touches real repos. If that directory does not exist, the workspace panel will render empty repo rows — which is fine for most screenshots. To exercise the repo strip, create the three empty directories first:

```bash
mkdir -p /tmp/conception-demo-workspace/{helio,helio-web,helio-docs}
git -C /tmp/conception-demo-workspace/helio init
git -C /tmp/conception-demo-workspace/helio-web init
git -C /tmp/conception-demo-workspace/helio-docs init
```

## Regenerating

This tree is hand-written. There is no automation and it is not expected to be kept in sync with the real conception repo. If condash's parser grows a new required field, update the fixtures here manually.
