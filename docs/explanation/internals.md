---
title: Internals · condash
description: How the parser, fingerprints, config split, native-window embedding, and vendored assets actually work. For readers who want to know why, not just how.
---

# Internals

This page is for readers who want to understand the moving parts — because they're contributing, integrating with condash, debugging, or just curious. It assumes familiarity with the [CLI](../reference/cli.md), [config files](../reference/config.md), and [HTTP API](../reference/http-api.md).

The stack: **axum** serves HTTP; **Tauri** wraps it in a native window; **rust-embed** carries the dashboard assets at compile time; **minijinja** renders the HTML fragments. The Rust workspace is split into four library crates (`condash-parser`, `condash-state`, `condash-render`, `condash-mutations`) plus the `src-tauri` binary crate that wires them together.

## Parser and fingerprints

### Discovery

`collect_items` in [`crates/condash-parser/src/collect.rs`](https://github.com/vcoeur/condash/blob/main/crates/condash-parser/src/collect.rs) performs a single glob:

```
<base_dir>/projects/*/*/README.md
```

Every match is a candidate item. The parser does **not** recurse deeper, does **not** walk `notes/` subdirectories, does **not** follow symlinks, and does **not** read any file other than the item's own `README.md`.

This is intentional. The conception tree might hold thousands of notes, but it will never hold thousands of **items** — the parser walks the small skeleton (the month directories), not the full forest (every file inside every item).

### Metadata extraction

For each matched `README.md`, `parse_readme`:

1. Reads the file into memory as UTF-8.
2. Takes the first line as `title` (stripping any leading `#`).
3. Walks subsequent lines until the first `##` heading, extracting `**Key**: value` pairs as metadata.
4. Captures the first paragraph after the first `##` as the card summary (≤ 300 chars).
5. Parses every `- [<marker>] <text>` line grouped under its nearest `##` heading.
6. Scans the `## Deliverables` section for `- [label](path.pdf) — desc` lines.
7. Walks the item directory up to three levels deep, capturing files and subdirectories for the card's "Files" pane.

Every step is a single pass over the file's line list. For a ~100-line README, the whole parse costs a few hundred microseconds. Even with hundreds of items, rendering the dashboard is dominated by the HTTP round-trip, not the parsing.

### Why no cache

The tree is re-parsed **on every page load and every poll**. It would be easy to cache, and every in-memory cache would be wrong:

- **File mtime cache.** Wrong if a user rewrites a file atomically to the same content with a different mtime. Wrong if a git operation changes several files at once but leaves a stale cache of the others.
- **Inotify / FSEvents.** Flaky across Linux desktops, platform-specific, and doesn't cover "I pulled a branch".
- **Manual invalidation.** The dashboard would have to know about every possible external writer — editor, shell, AI agent, git.

A few hundred READMEs parsed on every request takes single-digit milliseconds on a laptop. That budget bought us zero cache code, zero invalidation bugs, and "edit in your editor, refresh, see the change" with no moving parts.

### Fingerprints — why the UI doesn't flicker

A naive polling loop would re-fetch the whole dashboard every five seconds. That's ugly (flicker), expensive (DOM thrash), and loses focus on input fields. So we don't.

Instead, `GET /check-updates` returns a flat map of **fingerprints** — MD5 hashes of structural tuples:

| Node id | Hash covers |
|---|---|
| `projects` | The set of `(priority, slug)` pairs across all items |
| `projects/<priority>` | The set of slugs in that status group |
| `projects/<priority>/<slug>` | That card's content (title, apps, summary, sections, deliverables, files) |
| `knowledge` | The set of direct child ids of the `knowledge/` root |
| `knowledge/<sub-path>` | The set of direct child ids of that directory |
| `knowledge/<sub-path>/<file>.md` | That file's title + description + path |

The dashboard polls this map every 5 s, diffs it against the last-seen version, and for each changed id fetches **only** the corresponding `/fragment?id=...`. A single step toggle dirties one card hash and bubbles up to dirty the enclosing group + tab — but the other cards stay byte-identical on both sides, so their DOM isn't touched.

The key design choice is what each hash **doesn't** include:

- `projects/<priority>` hash only covers the membership (slugs). Editing one card's title doesn't dirty the group.
- `projects/<priority>/<slug>` deliberately excludes the priority. Dragging a card across columns re-keys the id (new path), not re-hashes the card content — so the DOM can detach-and-reinsert, but the card's innerHTML survives.
- The whole-tab hash covers the `(priority, slug)` set so that card adds / removes / moves do bubble up. A card content edit doesn't — only its card hash changes, only its `/fragment` is refetched.

See [`crates/condash-parser/src/fingerprint.rs`](https://github.com/vcoeur/condash/blob/main/crates/condash-parser/src/fingerprint.rs) for the computation and [HTTP API](../reference/http-api.md#change-polling) for the route shape.

Hashes are MD5 truncated to 16 hex chars. MD5 is fine here — this is an equality check, not a security primitive, and the 64-bit output is plenty to avoid collisions on trees of a few thousand items.

## Config: env var plus tree-level YAML

condash reads configuration from two places:

- **The `CONDASH_CONCEPTION_PATH` environment variable.** Tells condash which tree to render. Defaults to `$HOME/src/vcoeur/conception`. That's the only piece of configuration that has to live outside the tree, because the tree itself doesn't know where it lives on disk.
- **Two YAML files inside the tree**, under `<conception_path>/config/`:
  - `repositories.yml` — workspace layout, repo grouping, `open_with` command chains. Team-shared; commit it.
  - `preferences.yml` — per-machine scoping for this tree (PDF viewer chain, terminal shortcuts). Gitignored.

Splitting between the two YAML files is a *what does this describe* question, not a *how do you edit it* question. `repositories.yml` describes the team's shape — workspace layout, repo structure, "open with IntelliJ" chains — and should be identical for every teammate. `preferences.yml` describes one developer's preferences on one tree on one machine; committing it would force the team onto your terminal shortcut.

### Example

`<conception>/config/repositories.yml`, committed:

```yaml
workspace_path: /home/alice/src
worktrees_path: /home/alice/src/worktrees
repositories:
  primary:
    - vcoeur.com
    - notes.vcoeur.com
    - alicepeintures.com
  secondary:
    - conception
    - condash
open_with:
  main_ide: { label: "Open in IntelliJ",   commands: ["idea {path}"] }
  terminal: { label: "Open in Ghostty",    commands: ["ghostty --working-directory={path}"] }
```

`<conception>/config/preferences.yml`, **not** committed (gitignored):

```yaml
terminal:
  shortcut: "Ctrl+Shift+`"
  screenshot_paste_shortcut: "Ctrl+Alt+V"
```

The result: teammates who clone the tree get the same `workspace_path` shape and `open_with` chains; my keyboard shortcut override stays local.

### On machine-local configuration

An earlier design had a third file — a per-machine TOML — for settings that don't belong in either YAML (ports, PDF viewer, the native-window toggle). The current build gets by without it: the conception path comes from the environment, everything tree-scoped lives in the two YAMLs, and the few remaining per-machine toggles are either compile-time defaults or reachable via env vars. A future release may bring the TOML back for users who want a persistent machine-local override surface that isn't a shell rc file; for now there is no such file and the loader doesn't look for one.

See [multi-machine setup](../guides/multi-machine.md) for how to structure a two-machine workflow.

## Native window vs browser mode

### Tauri as the window host

The main `condash` binary uses Tauri: a thin Rust shell that wraps an axum HTTP server and a native webview pointed at `http://127.0.0.1:<port>`. The webview is **the OS's own**, not a bundled Chromium:

- **Linux** — WebKitGTK. The `.deb` and `.AppImage` builds depend on `libwebkit2gtk-4.1`.
- **macOS** — WKWebView, shipped with the OS.
- **Windows** — Edge WebView2, present on Windows 11 and installable as a runtime on 10.

The trade-off: install size stays in the tens of megabytes (no Chromium to carry) and the window starts in a fraction of a second. The cost is that every platform's webview has quirks — PDF rendering and clipboard handling especially — which the dashboard's JavaScript has to work around.

### `condash-serve` for headless + automation

The `condash-serve` binary is the equivalent of the old "no-native" mode: it runs the same axum server on a port and prints the URL, with no webview involvement. Reasons to use it:

- **No `DISPLAY` / headless host.** No WebKit libs required.
- **Automation.** Playwright and browser DevTools drive a plain HTTP URL more cleanly than a Tauri-wrapped one.
- **Frontend iteration.** Pair it with `CONDASH_ASSET_DIR=frontend/` to serve the dashboard bundle straight from disk; rebuild with `make frontend` in another shell and hard-refresh.

### Why Tauri, not a dedicated Electron bundle

Electron would roughly triple install size and add an auto-updater of its own. Tauri uses whatever native webview the OS already ships, so the shipped binary is small and the browser update cycle isn't ours to own. Downside: every platform's webview has quirks we work around — but they're quirks we can isolate in the frontend, not in the Rust shell.

## The dashboard bundle

The dashboard's JavaScript and CSS live under `frontend/src/`:

- `frontend/src/js/` — `dashboard-main.js` carries the bulk of the behaviour (still a single module for now — see below), plus `markdown-preview.js` and `cm6-mount.js` for the two surfaces that need the CodeMirror + PDF.js bindings isolated. `entry.js` is the esbuild entrypoint.
- `frontend/src/css/` — one CSS module per concern (`themes.css`, `cards.css`, `modals.css`, `terminal.css`, `notes.css`).

**Build step** is `make frontend`. It invokes esbuild transiently via `npx --yes esbuild@<pinned>` — **no `node_modules/` is ever created**; the tool runs, writes its output, and exits. Output lands in `frontend/dist/bundle.{js,css}`.

**Embedding.** `frontend/dist/` is compiled into the Rust binary via `rust-embed` — see [`src-tauri/src/assets.rs`](https://github.com/vcoeur/condash/blob/main/src-tauri/src/assets.rs). The release binary carries the built bundle with it, so there's no runtime file-system lookup for the dashboard's own assets.

**Committed output.** The built `frontend/dist/bundle.{js,css}` files are **committed** to git, so `cargo build` works on a machine with no Node toolchain. `make frontend` is only needed when you edit a source file under `frontend/src/`.

**Serving.** `/assets/dist/{rel_path}` is a path-validated static route in [`src-tauri/src/server.rs`](https://github.com/vcoeur/condash/blob/main/src-tauri/src/server.rs). In development, set `CONDASH_ASSET_DIR=frontend/` to serve from disk instead of the embedded copy.

**Shell discipline.** `frontend/dashboard.html` is structural-only. No inline `<script>` or `<style>` blocks — everything goes through the bundle. A size guard in the test suite fails if the file grows past a conservative threshold, catching drift back to the old monolithic layout.

Why esbuild and not Vite: no dev server is needed (axum already serves the static bundle), the split didn't buy its cost back in HMR, and the smaller dep surface matters for a tool that's sometimes installed in sandboxed environments.

Why a single `dashboard-main.js` for now: the 247 declarations in the original inline script coexisted as implicit globals (`_persistTabState`, `_rebindDashHandlers`, `_cmViews`, …). Rewriting every cross-call to an explicit import/export was out of scope for the split. A full extraction plan — 11 region-modules in dependency order, with the three cross-module cycles to break — exists as a follow-up.

## Vendored third-party assets

External client-side dependencies are **vendored into the repo**, not fetched from a CDN. Four of them:

### PDF.js

In-modal PDF previews use Mozilla's PDF.js. The library lives under `frontend/vendor/pdfjs/` and is served by the `/vendor/pdfjs/{rel_path}` route.

Why not the webview's built-in PDF renderer: WebKitGTK and WKWebView don't expose a PDF viewer that the dashboard can theme; Edge WebView2 has one, but with no theming hooks.

The vendored PDF.js lets us:

- Match the dashboard's dark / light theme on the viewer toolbar.
- Skip the unused viewer assets (locale strings, thumbnail panel, annotation editor).
- Wire the viewer's rendering loop to the in-modal `Ctrl+F` search bar eventually.

### xterm.js

The embedded terminal uses xterm.js plus `xterm-addon-fit`, served from `/vendor/xterm/`. Same rationale but a different failure mode: **an uncached CDN fetch breaks offline installs.**

condash is often run in air-gapped or aggressively-sandboxed environments (corporate laptops with blocked egress, Claude Code sandboxes, development VMs without internet). A runtime CDN fetch turns "start condash" into "start condash and hope for network" — a terrible property for a local-first tool. Vendoring cost us a few hundred KB of bundle size and gave us a terminal that starts in ~50 ms, guaranteed.

### CodeMirror 6 and Mermaid

The note editor uses CodeMirror 6, served from `/vendor/codemirror/`. Diagram rendering inside Markdown uses Mermaid, served from `/vendor/mermaid/`. Both are vendored for the same reason as xterm: offline-first matters more than cache freshness.

Re-vendoring is driven by `make update-pdfjs`, `make update-xterm`, `make update-codemirror`, `make update-mermaid` — each pins a version in the Makefile and downloads a clean tarball into `frontend/vendor/<name>/`.

### Pointer

All four live under `frontend/vendor/<name>/` and are served behind path-validating `/vendor/<name>/{rel_path}` routes that reject `..` escapes and null bytes. Standard fare for serving bundled assets out of a static-embedded Rust binary.

## Wrapping up

None of this is novel. The interesting parts are what we **didn't** build: no cache, no watcher, no schema, no lock files, no auth, no sync. The dashboard is a thin axum + Tauri layer over a directory of Markdown files, and the design is almost entirely about keeping it that way as features accumulate.

If you want to contribute or poke deeper, the [source on GitHub](https://github.com/vcoeur/condash) is split across the Rust workspace. Good starting points:

- [`crates/condash-parser/src/collect.rs`](https://github.com/vcoeur/condash/blob/main/crates/condash-parser/src/collect.rs) — the tree walker.
- [`crates/condash-parser/src/fingerprint.rs`](https://github.com/vcoeur/condash/blob/main/crates/condash-parser/src/fingerprint.rs) — the change-polling hash computation.
- [`crates/condash-mutations/src/lib.rs`](https://github.com/vcoeur/condash/blob/main/crates/condash-mutations/src/lib.rs) — the write surface; compare against the [mutation model reference](../reference/mutations.md) for overlap.
- [`src-tauri/src/server.rs`](https://github.com/vcoeur/condash/blob/main/src-tauri/src/server.rs) — every HTTP route, plus the PTY session registry.
