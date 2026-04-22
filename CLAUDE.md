# CLAUDE.md — condash

Standalone desktop dashboard for markdown-based conception items. Every item — project, incident, or document — lives at `projects/YYYY-MM/YYYY-MM-DD-slug/README.md` and carries a `**Kind**` field in its header. Condash renders a live view of that tree, tracks `## Steps` checklists, toggles item status, reorders steps, and opens files in your IDE — all from one native window backed by the same Markdown files the user edits by hand.

The name is a contraction of *conception dashboard*. The package distributes on PyPI under `condash`; the command-line binary is also `condash`.

## Project type

- **Not deployed.** Per-laptop tool, distributed via PyPI (`pipx install condash`) or `uv tool install condash`.
- **Single-user, single-window.** One NiceGUI + FastAPI process per user, launched on demand. No daemon, no multi-tenant state. The process lives as long as the window is open.
- **No database.** The source of truth is the Markdown tree at `conception_path`. Condash parses it on every request and mutates files in place.

## Stack

- Python 3.11+, `uv`-managed
- Typer (CLI) + NiceGUI + FastAPI (routes on NiceGUI's embedded FastAPI instance) + pywebview[qt] (native window) + tomlkit (config round-trip preserving comments)
- No ORM. `app.py` mixes sync (rendering + mutation helpers) and async (FastAPI routes + the WebSocket pty session) — sync helpers must not call `asyncio.run`; async handlers must not block on subprocess without `run_in_executor`.
- Fast in-process smoke suite under `tests/` (CLI + FastAPI `TestClient`); run via `make test`.
- Playwright browser-driven smoke suite under `tests/e2e/`; run via `make test-e2e` (uses system Chrome via `channel="chrome"`; override with `CONDASH_E2E_CHANNEL`). `make test-all` runs both.

## Architecture

```
condash/
  cli.py       <- Typer app (default launches the window; subcommands: init, install-desktop, uninstall-desktop, config show/path/edit)
  config.py    <- TOML loader + writer (tomlkit round-trip) + CondashConfig dataclass + DEFAULT_CONFIG_TEMPLATE
  context.py   <- RenderCtx dataclass + build_ctx(cfg) + favicon loader
  state.py     <- AppState dataclass: live cfg + ctx + event bus + observer + PTY registry + config self-write TTL stamps
  app.py       <- NiceGUI bootstrap, lifecycle hooks, run(cfg). Owns the module-level `state = AppState(...)` instance everything else closes over.
  routes/      <- HTTP + WebSocket route subpackage. Each module exposes `build_router(state) -> APIRouter`; `routes.register_all(app, state)` wires them all onto NiceGUI's FastAPI app. Files: static, updates, fragments, notes, items, files, steps, clipboard, openers, config_, runners, terminals.
  pty.py       <- Embedded-terminal PTY lifecycle: PtySession dataclass, spawn_session, pump_session, attach_ws, reap_all
  clipboard.py <- Cross-platform clipboard (QClipboard → wl/xclip/xsel) + the pywebview JS bridge
  paths.py     <- Path-traversal-safe validators for every user-supplied rel_path
  wikilinks.py <- `[[target]]` / `[[target|label]]` resolution + pre-pandoc rewrite
  parser.py    <- README parsing + knowledge-tree scanning + fingerprint check
  render.py    <- HTML rendering for cards, notes, knowledge tree, git strip, full page
  mutations.py <- File mutations: toggle checkbox, add/edit/remove step, rename/create note
  git_scan.py  <- `workspace_path` scan + git status/worktree/fingerprint for the repo strip
  openers.py   <- External launchers (IDE, PDF viewer, OS default, web browser)
  desktop.py   <- XDG .desktop entry writer for `condash install-desktop` (Linux only)
  assets/      <- dashboard.html (served verbatim at /), favicon.svg, favicon.ico
    vendor/pdfjs/  <- Mozilla PDF.js library (pdfjs-dist legacy build) used by the in-modal PDF viewer; bump via `make update-pdfjs`
```

Import direction: `cli` → `app` → `routes/*` → {`context`, `render`, `mutations`, `git_scan`, `openers`, `pty`, `clipboard`} → {`parser`, `wikilinks`, `paths`} → {`state`, `context`}. No module globals populated by `init`; runtime state lives on the single `app.state` AppState instance, every helper that needs config takes a `RenderCtx` parameter. `git_scan._git_cache` is a module-level cache (not config-derived).

## Config

Two files, two layers:

- **Per-user**: `${XDG_CONFIG_HOME:-~/.config}/condash/settings.yaml`. Flat, today a single key: `conception_path`. Points condash at the conception tree it should render. Written atomically (temp + rename), `0600` on unix. Loader: `src-tauri/src/user_config.rs`.
- **Per-tree**: `<conception_path>/configuration.yml`. Flat YAML merging the old `config/repositories.yml` + `config/preferences.yml` — carries `workspace_path`, `worktrees_path`, `repositories.{primary,secondary}`, `open_with`, `pdf_viewer`, `terminal`. Loader: `src-tauri/src/config.rs::build_ctx`.

Precedence when resolving the conception tree (`src-tauri/src/lib.rs::resolve_conception_path`): `CONDASH_CONCEPTION_PATH` env var → `settings.yaml` → (GUI only) native folder picker → hard error. No hard-coded `~/src/vcoeur/conception` fallback — the picker replaces that.

- **First-run flow** (GUI): if neither env nor settings.yaml supply a path, a native folder picker opens via `rfd`. Loose validation (directory exists + contains `configuration.yml` or `projects/`). On accept, the choice is persisted to `settings.yaml` before the dashboard loads. On cancel, the app exits cleanly.
- **Headless** (`condash-serve`): env var → settings.yaml → hard error. No prompt.
- **In-app editor**: the gear icon opens a plain-text YAML editor (`GET /configuration` returns the raw file; `POST /configuration` validates via `serde_yaml_ng::from_str::<ConfigurationYaml>` and atomically replaces the file). The current build does not hot-swap `RenderCtx` — the modal's success message tells the user to reopen condash for changes to take effect.
- **`[open_with.*]` slots**: three vendor-neutral launcher keys — `main_ide`, `secondary_ide`, `terminal` — each with a `label` and a `commands` fallback chain. `{path}` is substituted with the absolute path of the repo / worktree being opened. Commands are tried in order until one starts.
- **Per-repo `run:` + `force_stop:`**: a repo entry may carry a `run:` dev-runner template and an optional `force_stop:` shell command. `run:` is spawned via the tri-state Start/Stop/Switch button on each branch row — one session per repo, scoped to the checkout that started it. `force_stop:` drives the repo-level nuclear-stop button in the card header (one per repo, not per branch) and is invoked unconditionally — unlike `/api/runner/stop` it runs even when condash has no session for the repo, so it can free a port held by a server started from another terminal. Same shell-trust level as `run:`; both are routed through `sh -c`. Loader records them in `RenderCtx::repo_run_templates` / `repo_force_stop_templates` (same key space: parent by `name`, subrepo by `<parent>--<sub>`).
- **Split files** (`<conception_path>/config/repositories.yml` + `preferences.yml`): kept on disk for the retired Python build (`condash-python`). Condash no longer reads them. Edits via the modal land in `configuration.yml` and do not propagate to the split files — known drift hazard, accepted because condash-python is retired.

## Sandbox rules for "open in IDE"

`paths._validate_open_path(ctx, path_str)` accepts a path only if it resolves inside `ctx.workspace` or `ctx.worktrees`. This is the single defence against `condash` being tricked into launching an arbitrary binary via a crafted URL parameter. When editing any "open with external tool" code path, preserve the sandbox check — never trust an absolute path that came in over HTTP.

## Dashboard HTML

`assets/dashboard.html` is served verbatim at `/`. It is a single-file SPA that polls `/check-updates` for a fingerprint and re-fetches on change. The HTML template's JS calls back into the FastAPI routes registered in `app.py`; `render.render_page(ctx, items)` produces the item-list HTML that the template embeds. Do not refactor `dashboard.html` into a JS framework — the single-file contract is deliberate (zero build step, ships in the wheel via `importlib.resources`).

## PDF preview

PDFs in project notes render inside the modal via a custom viewer built on `pdfjs-dist` (library, not the prebuilt stock `web/viewer.html`). The library is vendored under `assets/vendor/pdfjs/` and served by the `/vendor/pdfjs/{rel_path:path}` route in `app.py`. `render.py::_render_note` emits `<div class="note-pdf-host" data-pdf-src="/file/…" data-pdf-filename="…">` for `.pdf` files; the ES module at the bottom of `dashboard.html` imports `/vendor/pdfjs/build/pdf.mjs`, exposes `window.__pdfjs`, and mounts toolbar + lazy-rendered canvases on each host. To bump the vendored version, edit `PDFJS_VERSION` in the Makefile and run `make update-pdfjs`.

We deliberately do **not** use `<iframe src="*.pdf">` with Chromium's built-in PDF viewer: QtWebEngine ships with `PdfViewerEnabled=false` and `pywebview` doesn't flip it, so the native-window modal would just show an "Open externally" card for PDFs.

## Commands

```bash
make dev-install                # uv sync --all-extras (install runtime + dev + e2e deps)
make test                       # fast in-process pytest suite (tests/, skips tests/e2e/)
make test-e2e                   # Playwright browser suite (tests/e2e/) against real condash subprocess
make test-all                   # both suites
make lint                       # uv run ruff check + format --check
make format                     # uv run ruff check --fix + format
make run                        # uv run condash (native window)
uv run condash --version        # smoke test the entry point
uv run condash init             # write a default config template
uv run condash config show      # print the effective configuration
uv run condash config path      # print the resolved config-file path
uv run condash config edit      # open the config file in $VISUAL / $EDITOR
uv run condash install-desktop  # register the XDG .desktop entry (Linux)
```

The CLI honours `CONDASH_LOG_LEVEL` (default `INFO`) for the root logger; set to `DEBUG` to surface the clipboard fallback chain and similar low-noise events.

## Workflow

1. After any code change: `make format && make lint && make test` — matches the `make format` / `make test` rhythm the other vcoeur CLIs have.
2. Manual smoke test: `make run` against a throwaway `conception_path` (e.g. `/tmp/fake-conception/` with one project README) before committing changes the automated smoke does not cover.
3. When adding a new FastAPI route in `app.py`: add the matching fetch call in `assets/dashboard.html` and consider extending `tests/test_app_smoke.py` if the route is reachable from a `TestClient`.
4. Every helper that needs config takes `ctx: RenderCtx` as its first argument. Pure helpers (regex gates, HTML escaping, parsers of in-memory data) stay ctx-free.
5. When touching `config.py`: round-trip at least one fixture through `tomlkit` manually to confirm comments and key order survive the rewrite — the in-app editor depends on this.

## Key code locations

- CLI entrypoint: `src/condash/cli.py` — Typer app with a root callback that launches the window and a `config` sub-app for `show / edit / path`.
- FastAPI routes: `src/condash/routes/*.py` — one file per concern, each exporting `build_router(state) -> APIRouter`. `app.py::_register_routes` calls `routes.register_all(_ng_app, state)` to wire them all on; the live RenderCtx is read via `state.get_ctx()`.
- Runtime state: `src/condash/state.py::AppState` (single per-process instance at `app.state`) + `src/condash/context.py::RenderCtx` + `build_ctx(cfg)`. Frozen RenderCtx carries `base_dir`, `workspace`, `worktrees`, `repo_structure`, `open_with`, `pdf_viewer`, `template`. Rebuilt on every `/config` POST.
- Path validators: `src/condash/paths.py::_safe_resolve` is the shared traversal guard; every route-facing validator composes regex gates on top of it.
- Parsers + renderers: `src/condash/parser.py` (README + knowledge tree), `src/condash/render.py` (HTML for cards / notes / knowledge / git strip / page).
- History search: `src/condash/search.py::search_items` — token-AND scan of each project's README body, note/text-file content and filenames. Exposed as `GET /search-history?q=…`; the History tab's input switches to a query-mode results list (`dashboard.html::filterHistory` / `_runHistorySearch`) with a jump-to-project button.
- File mutations: `src/condash/mutations.py` — toggle / add / edit / remove step, rename / create note, priority edit.
- Git scan + repo strip: `src/condash/git_scan.py` — workspace scan, per-repo status, worktree listing, fingerprint cache for the `/check-updates` long-poll.
- External launchers: `src/condash/openers.py` — open-in-IDE, PDF viewer chain, OS default opener, external URL routing.
- Wikilinks: `src/condash/wikilinks.py` — `[[target]]` resolver called from markdown preprocess before pandoc.
- Config dataclass + loader: `src/condash/config.py::CondashConfig` and `config.load`. `ConfigNotFoundError` vs `ConfigIncompleteError` are distinct so the CLI can suggest `init` vs `config edit`. The same module owns the editor's payload boundary (`config_to_payload` / `payload_to_config`) so every input shape — TOML, YAML, JSON — funnels through one validator (`config.parse_repo_entries`).
- Native window launcher: `src/condash/desktop.py` — writes `~/.local/share/applications/condash.desktop` and the SVG icon. Linux only.
- Assets shipped in the wheel: `src/condash/assets/` — referenced via `importlib.resources.files("condash") / "assets"`, never via `__file__`, so the app works when installed from a wheel.
