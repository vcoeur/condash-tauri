# helio-web — conception-side knowledge

The dashboard companion to the `helio` CLI. A thin Vite + React front-end over a small FastAPI backend that shells out to `helio` for reads and reads the shared index directly for the suggestions endpoint.

→ Repo-internal facts (routes, components, build, deploy) live in [`../../../helio-web/CLAUDE.md`](../../../helio-web/CLAUDE.md) once the demo workspace is populated.

## Dev port

`helio-web` binds to `localhost:8100` in development — deliberately chosen to avoid the Vite default (5173) and the common Flask/FastAPI defaults (5000, 8000). The port is hard-coded in `docker-compose.dev.yml` and the launch script; no override needed in the usual case.

## CORS during local dev

Running the dashboard against a `helio` CLI on the same host works out of the box. Running it against a `helio` endpoint on a different host requires adding the origin to the backend's CORS allowlist (`CORS_ORIGINS` env var, comma-separated). Easy to miss during first-run because the error shows up as a silent fetch failure in the browser DevTools network tab, not as an HTTP error — the preflight `OPTIONS` fails and the real request never fires.

## Suggestions endpoint

`GET /api/search/suggest` reads the same index that `helio search` writes. During [[fuzzy-search-v2]], this endpoint is being ported to read the new trigram index directly instead of shelling out to `helio search --preview`. Once shipped:

- Index version mismatches between `helio` and `helio-web` will return HTTP 503 with a clear error body rather than silently returning wrong results.
- The endpoint must be restarted after an index rebuild — the mmap handle is held for the lifetime of the process.

## Driving from the sandbox

For Playwright-driven screenshots:

1. Start `helio-web` in dev mode: `make dev` from the repo root.
2. Wait for the `localhost:8100` banner.
3. Drive from Playwright per [`../topics/performance.md`](../topics/performance.md)'s general methodology — but for UI captures, the relevant viewport is 1280×900 to match the docs screenshot convention.

Tear down: `make dev-stop` or just Ctrl-C the dev server.
