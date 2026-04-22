# condash

**Standalone desktop dashboard for a Markdown-first project-tracking tree — projects, incidents, and documents all live as plain `.md` files you already edit.**

`condash` walks a `projects/YYYY-MM/YYYY-MM-DD-<slug>/` tree under a single **conception root** and renders a live dashboard of every item: its status, steps, notes, deliverables, and linked code. There is no database, no sync server, no account. The Markdown files are the source of truth; condash is the view layer.

Full documentation, with tutorials and screenshots, lives at **[condash.vcoeur.com](https://condash.vcoeur.com/)**.

## Install

```bash
pipx install condash
# or: uv tool install condash
```

Both install the CLI into its own isolated virtualenv and put `condash` on your `$PATH`. Install size is roughly 100 MB because of the bundled Qt wheels — that's the cost of "works everywhere with one command".

### System prerequisites

None on Linux, macOS, or Windows. `pywebview[qt]` pulls `PyQt6` + `PyQt6-WebEngine` from PyPI and those wheels bundle Qt itself:

- **Linux** — prefers GTK/WebKit if `python3-gi` is installed system-wide, falls back to the bundled Qt backend otherwise.
- **macOS** — uses the native Cocoa WebKit backend.
- **Windows** — uses the native Edge WebView2 backend.

To skip the native window entirely, set `native = false` in your config and open the dashboard in your browser at `http://127.0.0.1:<port>` — see [Configure the conception path](https://condash.vcoeur.com/guides/configure-conception-path/).

### Development from a source checkout

```bash
git clone https://github.com/vcoeur/condash.git
cd condash
uv sync --all-extras
make frontend               # bundle assets/src/{js,css}/ → assets/dist/ (esbuild via npx)
uv run condash --version
uv run condash
```

`make frontend` is only needed when the source under `src/condash/assets/src/` changes — the built `dist/bundle.{js,css}` files are committed so `pip install condash` from sdist works without a Node toolchain. It invokes `esbuild` transiently through `npx --yes`, so no `node_modules/` is created.

## First launch

`condash` doesn't ship a working default config — it has no way to guess where your conception tree lives. Bootstrap one:

```bash
condash init           # writes a commented template at ~/.config/condash/config.toml
condash config edit    # opens it in $VISUAL / $EDITOR
```

The only required key is `conception_path`:

```toml
conception_path = "/path/to/conception"
port            = 0      # 0 = OS picks a free port
native          = true   # false = open in your browser
```

Everything else — the workspace of code repos, the "open in IDE" launchers, per-machine preferences — lives in two YAML files **inside the conception tree** (`<conception_path>/config/repositories.yml` and `<conception_path>/config/preferences.yml`), so teammates who pull the tree get the same layout automatically. The gear icon in the dashboard header opens an in-app editor for all three files.

Full schema: [Config files reference](https://condash.vcoeur.com/reference/config/).

## What it does

- **Renders a live dashboard** of every `projects/YYYY-MM/YYYY-MM-DD-<slug>/README.md`, grouped by status (`now` / `soon` / `later` / `backlog` / `review` / `done`). Drag cards between columns to rewrite the `**Status**:` line in place. Unknown status values surface a red `!?` badge so typos don't silently land in `backlog`.
- **Tracks steps and deliverables** parsed from the README body — `- [ ]`/`- [~]`/`- [x]`/`- [-]` checkboxes, `## Deliverables` PDF links. A click on a checkbox rewrites the line.
- **An embedded terminal** (vendored xterm.js) for ad-hoc commands, plus an **inline dev-server runner** (since v0.13.0) that starts your `make dev` / `npm run dev` / `cargo watch` under a PTY and streams output into a xterm mounted right under the repo row.
- **A repo strip** (the Code tab) with per-repo dirty counts, worktree nesting, and per-repo inline runners. Each repo gets vendor-neutral `main_ide`, `secondary_ide`, and `terminal` launcher buttons wired to your own commands via a fallback chain.
- **A knowledge tree** (optional `knowledge/` sibling of `projects/`) rendered as a browsable tab — the right place for durable reference material that outlives any one project.
- **Wikilinks** (`[[slug]]`) between items, resolved by short-slug match across the whole tree.
- **A vendored PDF viewer** (Mozilla PDF.js, minified) for `## Deliverables` — no OS handler involved, theme-aware toolbar.
- **Fully offline**: every browser dependency (PDF.js, xterm.js, CodeMirror 6 with YAML + Markdown, Mermaid) is vendored under `src/condash/assets/vendor/` and served from `/vendor/…`. Minified-where-possible; no runtime fetch to a CDN.
- **Fingerprinted auto-refresh** so edits made in your external editor surface in the dashboard within 5 seconds without flickering the page.

All of it is thin — condash is a FastAPI + NiceGUI layer over a directory of Markdown files, and the design is mostly about keeping it that way as features accumulate.

## CLI

```
condash                         # open the dashboard window
condash --version               # print version and exit
condash --conception-path PATH  # one-shot override (does not touch config file)
condash --config PATH           # use a different config file
condash --port N                # one-shot port override
condash --no-native             # open in your browser instead of a desktop window

condash init                    # write a commented config template if missing
condash config show             # print the effective (merged) configuration
condash config path             # print the resolved config file path
condash config edit             # open the config in $VISUAL / $EDITOR

condash install-desktop         # register condash with the XDG launcher (Linux)
condash uninstall-desktop       # remove the user-local desktop entry (Linux)
```

Full reference: [CLI](https://condash.vcoeur.com/reference/cli/).

## Linux: register condash in your application launcher

```bash
condash install-desktop
```

Writes a user-local XDG desktop entry + the bundled SVG icon, so condash appears in GNOME Activities, KDE Kickoff, Cinnamon, and other launchers:

- `~/.local/share/applications/condash.desktop` — launcher entry, pointing at the absolute path of whichever `condash` binary you ran the command with
- `~/.local/share/icons/hicolor/scalable/apps/condash.svg` — the app icon

No `sudo`, no system-wide changes. Remove later with `condash uninstall-desktop`. The native window also picks up the same icon at runtime, so it appears in your taskbar / Alt-Tab switcher.

## Claude Code skill

A minimal example [`SKILL.md`](SKILL.md) ships at the repo root — drop it into `~/.claude/skills/condash/` (or `<project>/.claude/skills/condash/`) to drive the non-interactive CLI surface from a Claude Code session: `condash init`, `condash config show / path / edit`, `condash install-desktop`. Launching the native window from inside an agent is deliberately out of scope — run `condash` by hand for that.

## Status

Version **0.14.1**. Linux-first but tested on all three desktop platforms. The docs site at [condash.vcoeur.com](https://condash.vcoeur.com/) tracks current behaviour; the [`CHANGELOG`](https://github.com/vcoeur/condash/commits/main) on GitHub has the release-by-release history.

## Links

- Documentation: **[condash.vcoeur.com](https://condash.vcoeur.com/)**
- Source: **[github.com/vcoeur/condash](https://github.com/vcoeur/condash)**
- PyPI: **[pypi.org/project/condash](https://pypi.org/project/condash/)**

## License

MIT — see [LICENSE](LICENSE).
