# CLAUDE.md — condash

Standalone desktop dashboard for markdown-based conception projects, incidents, and documents. Renders a live view of a `conception`-style directory tree (`projects/YYYY-MM-DD-slug/README.md`, `incidents/…`, `documents/…`), tracks `## Steps` checklists, toggles item status, reorders steps, opens files in your IDE, and tidies done items into `YYYY-MM/` archive folders — all from one native window backed by the same Markdown files the user edits by hand.

The name is a contraction of *conception dashboard*. The package distributes on PyPI under `condash`; the command-line binary is also `condash`.

## Project type

- **Not deployed.** Per-laptop tool, distributed via PyPI (`pipx install condash`) or `uv tool install condash`.
- **Single-user, single-window.** One NiceGUI + FastAPI process per user, launched on demand. No daemon, no multi-tenant state. The process lives as long as the window is open.
- **No database.** The source of truth is the Markdown tree at `conception_path`. Condash parses it on every request and mutates files in place.

## Stack

- Python 3.11+, `uv`-managed
- Typer (CLI) + NiceGUI + FastAPI (routes on NiceGUI's embedded FastAPI instance) + pywebview[qt] (native window) + tomlkit (config round-trip preserving comments)
- No ORM, no async, no test suite yet

## Architecture

```
condash/
  cli.py       <- Typer app (default launches the window; subcommands: init, config show/edit, tidy, install-desktop, uninstall-desktop)
  config.py    <- TOML loader + writer (tomlkit round-trip) + CondashConfig dataclass + DEFAULT_CONFIG_TEMPLATE
  app.py       <- NiceGUI bootstrap + FastAPI route registration (`/`, `/toggle`, `/add-step`, `/tidy`, `/config`, …). Holds _RUNTIME_CFG so the in-app editor can mutate config without a restart.
  legacy.py    <- Ported verbatim from conception/tools/dashboard.py: Markdown parser, HTML renderer, mutation helpers, tidy pass. `init()` injects BASE_DIR / workspace / worktrees / repo structure from CondashConfig. `app.py` calls the helpers directly instead of routing through a BaseHTTPRequestHandler.
  desktop.py   <- XDG .desktop entry writer for `condash install-desktop` (Linux only)
  assets/      <- dashboard.html (served verbatim at /), favicon.svg, favicon.ico
```

Import direction: `cli` → `app` → `config` + `legacy`. `legacy.py` has no intra-package imports; it is a leaf module whose module-level globals are populated by `legacy.init(cfg)` before any renderer runs.

## Config

Config file lives at `~/.config/condash/config.toml` (or `$XDG_CONFIG_HOME/condash/config.toml`). Required key: `conception_path`. Everything else optional — see the `DEFAULT_CONFIG_TEMPLATE` string in `condash/config.py` for the full schema, and the top-of-file docstring for the canonical documentation.

- **First-run flow**: `condash init` writes the template (fully commented out); `condash config edit` opens it in `$VISUAL` / `$EDITOR`. If the user runs `condash` before editing the template, `ConfigIncompleteError` is raised and the CLI prints a pointer to `condash config edit`.
- **In-app editor**: the gear icon in the dashboard header posts to `/config`, which rewrites the TOML file atomically via tomlkit (comments and key order preserved) and hot-reloads `_RUNTIME_CFG`. Path / repository / `open_with` changes take effect on dashboard reload; `port` / `native` changes require a process restart and the modal tells the user so.
- **`[open_with.*]` slots**: three vendor-neutral launcher keys — `main_ide`, `secondary_ide`, `terminal` — each with a `label` and a `commands` fallback chain. Commands are `shlex`-parsed; `{path}` is substituted with the absolute path of the repo / worktree being opened. Commands are tried in order until one starts. Built-in defaults reproduce the pre-0.2 hardcoded IntelliJ / VS Code / terminal behaviour, so the user only needs to override the slots they actually want to customise.

## Sandbox rules for "open in IDE"

`legacy._open_in_ide` (and peers) accept a path only if it is inside `_WORKSPACE` or `_WORKTREES`. This is the single defence against `condash` being tricked into launching an arbitrary binary via a crafted URL parameter. When editing any "open with external tool" code path, preserve the sandbox check — never trust an absolute path that came in over HTTP.

## Dashboard HTML

`assets/dashboard.html` is served verbatim at `/`. It is a single-file SPA that polls `/check-updates` for a fingerprint and re-fetches on change. The HTML template's JS calls back into the FastAPI routes registered in `app.py`; `legacy.render_page(items)` produces the item-list HTML that the template embeds. Do not refactor `dashboard.html` into a JS framework — the single-file contract is deliberate (zero build step, ships in the wheel via `importlib.resources`).

## Commands

```bash
uv sync --all-extras            # install deps incl. dev
uv run condash --version        # smoke test the entry point
uv run condash                  # launch the native window using ~/.config/condash/config.toml
uv run ruff check src           # lint
uv run ruff format src          # format (no Makefile yet — invoke ruff directly)
uv run condash init             # write a default config template
uv run condash config show      # print the effective configuration
uv run condash tidy             # move done items into YYYY-MM/ archive dirs
```

There is **no `Makefile`** and **no `tests/` directory** yet — unlike quelle and knoten. When adding either, match their shape (`make dev-install / test / lint / format / tool-install` and `tests/test_cli_smoke.py` as the integration anchor) so the three vcoeur CLIs keep the same workflow shape.

## Workflow

1. After any code change: `uv run ruff format src && uv run ruff check src` — matches the `make format` step the other vcoeur CLIs have.
2. Manual smoke test: `uv run condash` against a throwaway `conception_path` (e.g. `/tmp/fake-conception/` with one project README) before committing changes that touch `app.py` or `legacy.py`.
3. When adding a new FastAPI route in `app.py`: add the matching fetch call in `assets/dashboard.html` and verify it in the browser dev-tools network tab — there is no automated coverage yet.
4. When porting more behaviour from `conception/tools/dashboard.py`: keep the helper in `legacy.py`, not in `app.py`. `legacy.py` is the "ported verbatim" layer; `app.py` is the NiceGUI/FastAPI wiring.
5. When touching `config.py`: round-trip at least one fixture through `tomlkit` manually to confirm comments and key order survive the rewrite — the in-app editor depends on this.

## Key code locations

- CLI entrypoint: `src/condash/cli.py` — Typer app with a root callback that launches the window and a `config` sub-app for `show / edit / path`.
- FastAPI routes: `src/condash/app.py::_register_routes` — all the endpoints `dashboard.html` talks to, registered on NiceGUI's embedded FastAPI instance.
- Markdown parser + renderer: `src/condash/legacy.py` — 1.3 kloc, ported from `conception/tools/dashboard.py`. Module-level globals (`BASE_DIR`, `_WORKSPACE`, `_WORKTREES`, `_REPO_STRUCTURE`) are populated by `legacy.init(cfg)`; **never read them before `init` runs**.
- Config dataclass + loader: `src/condash/config.py::CondashConfig` and `config.load`. `ConfigNotFoundError` vs `ConfigIncompleteError` are distinct so the CLI can suggest `init` vs `config edit`.
- Native window launcher: `src/condash/desktop.py` — writes `~/.local/share/applications/condash.desktop` and the SVG icon. Linux only.
- Assets shipped in the wheel: `src/condash/assets/` — referenced via `importlib.resources.files("condash") / "assets"`, never via `__file__`, so the app works when installed from a wheel.
