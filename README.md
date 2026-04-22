# condash

**Standalone desktop dashboard for a Markdown-first project-tracking tree — projects, incidents, and documents all live as plain `.md` files you already edit.**

`condash` walks a `projects/YYYY-MM/YYYY-MM-DD-<slug>/` tree under a single **conception root** and renders a live dashboard of every item: its status, steps, notes, deliverables, and linked code. There is no database, no sync server, no account. The Markdown files are the source of truth; condash is the view layer.

Full documentation, with tutorials and screenshots, lives at **[condash.vcoeur.com](https://condash.vcoeur.com/)**.

## Install

Download the installer for your platform from the [GitHub Releases page](https://github.com/vcoeur/condash/releases):

| Platform | Artifact |
|---|---|
| Linux    | `condash_<version>_amd64.AppImage` or `.deb` |
| macOS    | `condash_<version>_<arch>.dmg` |
| Windows  | `condash_<version>_x64_en-US.msi` |

The builds are **unsigned** on purpose — signing Windows + macOS binaries costs $180–400/year and condash is single-developer-scale. Each OS asks for confirmation once on first launch; see the [Install the desktop app guide](https://condash.vcoeur.com/guides/install-desktop/) for the per-platform gesture.

## Build from source

You need a [rustup](https://rustup.rs)-managed Rust toolchain (1.90+). On Linux you also need the usual Tauri system deps (WebKitGTK, libappindicator, librsvg); `cargo tauri build` prints the exact package list for your distro.

```bash
git clone https://github.com/vcoeur/condash.git
cd condash
make install-tauri-cli     # one-off: installs cargo-tauri into the rustup toolchain
make frontend              # bundle frontend/src/{js,css}/ -> frontend/dist/ via esbuild
make run-tauri             # open the dev window
make build-tauri           # produce the signed installer under src-tauri/target/release/bundle/
```

`make frontend` is only needed when the source under `frontend/src/` changes — the built `dist/bundle.{js,css}` files are committed so a fresh clone builds without a Node toolchain. The target invokes `esbuild` transiently through `npx --yes`, so no `node_modules/` is created.

For running the HTTP surface headless (useful for Playwright, curl, or hacking the server without the GUI deps):

```bash
make run-serve             # runs condash-serve against $HOME/src/vcoeur/conception
CONDASH_CONCEPTION_PATH=/other/tree make run-serve
```

## First launch

`condash` reads `CONDASH_CONCEPTION_PATH` to find your tree (default: `$HOME/src/vcoeur/conception`). On first launch, click the gear icon in the dashboard header and set the path in the **General** tab of the Configuration modal. The change takes effect on the next window launch.

All other configuration — the workspace of code repos, the "open in IDE" launchers, per-machine preferences — lives in two YAML files **inside the conception tree**:

- `<conception_path>/config/repositories.yml` — versioned with the tree, describes the workspace shape and "open with" commands.
- `<conception_path>/config/preferences.yml` — local machine overrides (PDF viewer, terminal shortcut).

Full schema: [Config files reference](https://condash.vcoeur.com/reference/config/).

## What it does

- **Renders a live dashboard** of every `projects/YYYY-MM/YYYY-MM-DD-<slug>/README.md`, grouped by status (`now` / `soon` / `later` / `backlog` / `review` / `done`). Drag cards between columns to rewrite the `**Status**:` line in place. Unknown status values surface a red `!?` badge so typos don't silently land in `backlog`.
- **Tracks steps and deliverables** parsed from the README body — `- [ ]`/`- [~]`/`- [x]`/`- [-]` checkboxes, `## Deliverables` PDF links. A click on a checkbox rewrites the line.
- **An embedded terminal** (vendored xterm.js) for ad-hoc commands, plus an **inline dev-server runner** that starts your `make dev` / `npm run dev` / `cargo watch` under a PTY and streams output into an xterm mounted right under the repo row.
- **A repo strip** (the Code tab) with per-repo dirty counts, worktree nesting, and per-repo inline runners. Each repo gets vendor-neutral `main_ide`, `secondary_ide`, and `terminal` launcher buttons wired to your own commands via a fallback chain.
- **A knowledge tree** (optional `knowledge/` sibling of `projects/`) rendered as a browsable tab — the right place for durable reference material that outlives any one project.
- **Wikilinks** (`[[slug]]`) between items, resolved by short-slug match across the whole tree.
- **A vendored PDF viewer** (Mozilla PDF.js, minified) for `## Deliverables` — no OS handler involved, theme-aware toolbar.
- **Fully offline**: every browser dependency (PDF.js, xterm.js, CodeMirror 6 with YAML + Markdown, Mermaid) is vendored under `frontend/vendor/` and embedded into the binary at build time. No runtime fetch to a CDN.
- **Fingerprinted auto-refresh** so edits made in your external editor surface in the dashboard within 5 seconds without flickering the page.

Under the hood: an [axum](https://github.com/tokio-rs/axum) HTTP server bound to a loopback port, wrapped by a [Tauri](https://tauri.app) window on the GUI side. Assets are embedded via [rust-embed](https://crates.io/crates/rust-embed); templates via [minijinja](https://crates.io/crates/minijinja).

## Repository layout

```
condash/
├── crates/
│   ├── condash-parser/      # README + knowledge-tree parser, fingerprint hashing
│   ├── condash-state/       # workspace cache, git scan, history-tab search
│   ├── condash-render/      # HTML rendering (minijinja) + templates/
│   └── condash-mutations/   # README write-side mutations (step toggles, status drags)
├── frontend/                # dashboard HTML/CSS/JS + vendored PDF.js, xterm.js, CodeMirror, Mermaid
├── src-tauri/               # Tauri host + axum server + the two binaries
├── examples/                # sample conception trees + example Claude Code skill
├── docs/                    # mkdocs site, published to condash.vcoeur.com
└── Makefile                 # make help for the full target list
```

## Links

- Documentation: **[condash.vcoeur.com](https://condash.vcoeur.com/)**
- Source: **[github.com/vcoeur/condash](https://github.com/vcoeur/condash)**
- Releases: **[github.com/vcoeur/condash/releases](https://github.com/vcoeur/condash/releases)**

## License

MIT — see [LICENSE](LICENSE).
