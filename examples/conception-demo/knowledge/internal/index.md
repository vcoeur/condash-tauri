# Internal Systems

One file per helio repo. Each captures conception-side knowledge that does not belong inside the repo's own `CLAUDE.md` — sandbox-testing recipes, rename history, cross-repo gotchas.

## What lives here

- If a fact belongs to the repo itself and will be read by anyone working on that repo directly → the repo's own `CLAUDE.md`.
- If a fact only makes sense from the conception session → per-repo file here.

## Current files

- [`helio.md`](helio.md) — *the CLI itself; release artefact pipeline, PyO3 build quirks, how to drive `helio search` against synthetic corpora in the sandbox.* `[helio, cli, rust, pyo3, benchmarking]`
- [`helio-web.md`](helio-web.md) — *the dashboard companion; how it talks to the CLI, dev-port (8100), known CORS gotcha during local development.* `[helio-web, dashboard, api, cors, dev-port]`

No `helio-docs.md` yet — the docs site is straightforward MkDocs and has nothing conception-side to record beyond the release checklist already in [`../topics/releases.md`](../topics/releases.md) and the [[docs-site-404s]] incident.
