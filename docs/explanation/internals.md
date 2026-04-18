---
title: Internals · condash
description: How the parser, fingerprints, config split, native-window embedding, and vendored assets actually work. For readers who want to know why, not just how.
---

# Internals

This page is for readers who want to understand the moving parts — because they're contributing, integrating with condash, debugging, or just curious. It assumes familiarity with the [CLI](../reference/cli.md), [config files](../reference/config.md), and [HTTP API](../reference/http-api.md).

## Parser and fingerprints

### Discovery

`collect_items()` in [`parser.py`](https://github.com/vcoeur/condash/blob/main/src/condash/parser.py) performs a single glob:

```python
ctx.base_dir / "projects" glob "*/*/README.md"
```

Every match is a candidate item. The parser does **not** recurse deeper, does **not** walk `notes/` subdirectories, does **not** follow symlinks, and does **not** read any file other than the item's own `README.md`.

This is intentional. The conception tree might hold thousands of notes, but it will never hold thousands of **items** — the parser walks the small skeleton (the month directories), not the full forest (every file inside every item).

### Metadata extraction

For each matched `README.md`, `parse_readme()`:

1. Reads the file into memory (`read_text(encoding="utf-8")`).
2. Takes the first line as `title` (stripping any leading `#`).
3. Walks subsequent lines until the first `##` heading, extracting `**Key**: value` pairs as metadata.
4. Captures the first paragraph after the first `##` as the card summary (≤ 300 chars).
5. Calls `_parse_sections()` which collects every `- [<marker>] <text>` line grouped under its nearest `##` heading.
6. Calls `_parse_deliverables()` which scans the `## Deliverables` section for `- [label](path.pdf) — desc` lines.
7. Calls `_list_item_tree()` which walks the item directory up to three levels deep, capturing files and subdirectories for the card's "Files" pane.

Every step is a single pass over the file's line list. For a ~100-line README, the whole parse costs a few hundred microseconds. Even with hundreds of items, rendering the dashboard is dominated by the HTTP round-trip, not the parsing.

### Why no cache

The tree is re-parsed **on every page load and every poll**. It would be easy to cache, and every in-memory cache would be wrong:

- **File mtime cache.** Wrong if a user rewrites a file atomically to the same content with a different mtime. Wrong if a git operation changes several files at once but leaves a stale cache of the others.
- **Inotify / FSEvents.** Flaky across Linux desktops, platform-specific, and doesn't cover "I pulled a branch".
- **Manual invalidation.** The dashboard would have to know about every possible external writer — editor, shell, AI agent, git.

A few hundred READMEs parsed on every request takes less than 50 ms on a laptop. That budget bought us zero cache code, zero invalidation bugs, and "edit in your editor, refresh, see the change" with no moving parts.

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

See [`compute_project_node_fingerprints`](https://github.com/vcoeur/condash/blob/main/src/condash/parser.py) for the computation and [HTTP API](../reference/http-api.md#change-polling) for the route shape.

Hashes are MD5 truncated to 16 hex chars. MD5 is fine here — this is an equality check, not a security primitive, and the 64-bit output is plenty to avoid collisions on trees of a few thousand items.

## TOML vs YAML config split

condash reads **three** config files, owned by two different scopes. See [config files](../reference/config.md) for the full schema; this section is about the *why*.

### Per-machine vs per-tree

Some settings belong to the machine:

- Which conception tree this condash points at (`conception_path`).
- Which port to bind to (`port`).
- Whether to open a native window (`native`).
- Which PDF viewer to prefer (`pdf_viewer`).
- Which shell and keyboard shortcuts to use inside the embedded terminal (`[terminal]`).

These change per host and must not be committed into the conception repo — one developer on Wayland + ghostty wants a different `[terminal]` block than another on X11 + gnome-terminal. That's `~/.config/condash/config.toml`: TOML, per-machine, never committed.

Other settings belong to the tree:

- Where the workspace of repos is (`workspace_path`).
- Where the worktrees directory is (`worktrees_path`).
- Which repos are "primary" vs "secondary", and which carry submodules.
- Which IDE + terminal commands should the "open with" buttons invoke (`open_with`).

These describe the *team's* shape — or the single developer's shape across machines. They should be committed so teammates who pull the tree get the same layout. That's `<conception_path>/config/repositories.yml`: YAML, versioned with the conception repo.

A third file, `<conception_path>/config/preferences.yml`, sits in between: same keys as the TOML (`pdf_viewer`, `[terminal]`) but scoped to the tree rather than the machine. Not committed — it lets a developer use different terminal shortcuts depending on which conception tree they're working in, without polluting the team-shared repo.

### Why three files, not one

It would be simpler to have one file. Two attempts at "one file" failed:

- **One TOML only.** Teammates can't share `workspace_path` / `open_with` — it's per-machine by location. We tried it; every new laptop setup turned into a `workspace_path` copy-paste from chat.
- **One YAML in the tree.** Can't hold `conception_path` (the tree doesn't know where it lives on disk) and can't hold per-machine terminal shortcuts.

So we split on **what it describes**, not on **how it's edited**. The TOML is machine-local, never shared. `repositories.yml` is tree-shared. `preferences.yml` is tree-local, not shared.

### Merge order

At load time in [`config.py::load`](https://github.com/vcoeur/condash/blob/main/src/condash/config.py):

1. Parse `~/.config/condash/config.toml` → get a `CondashConfig` with all fields.
2. If `conception_path` resolves and `<conception_path>/config/repositories.yml` exists, overlay its fields (`workspace_path`, `worktrees_path`, `repositories`, `open_with`). This **replaces** whatever was in TOML for those keys.
3. If `<conception_path>/config/preferences.yml` exists, overlay `pdf_viewer` and `[terminal]`. This too replaces the TOML values.

The `_log_deprecated_toml_keys` helper emits a one-time INFO line when it sees YAML-managed keys still in the TOML — those are migration residue. The next save from the gear modal strips them.

### Example

`~/.config/condash/config.toml` on my laptop:

```toml
conception_path = "/home/alice/src/vcoeur/conception"
port = 0
native = true
```

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

The result: teammates who clone the tree get the same `workspace_path` shape and `open_with` chains; my keyboard shortcut override stays local; my conception path stays per-machine.

See [multi-machine setup](../guides/multi-machine.md) for how to structure a two-machine workflow.

## Native window vs browser mode

### How native mode works

By default (`native = true`) condash starts an HTTP server bound to a free local port **and** opens a `pywebview` desktop window pointed at `http://127.0.0.1:<port>`. The window is a real OS-native WebView:

- **Linux** — `pywebview` prefers GTK/WebKit if `python3-gi` is installed system-wide, falling back to Qt (`PyQt6` + `PyQt6-WebEngine`) which is a hard runtime dependency. We force `_ng_app.native.start_args["gui"] = "qt"` in [`app.py::run`](https://github.com/vcoeur/condash/blob/main/src/condash/app.py) so that on systems without GTK bindings we go straight to Qt instead of printing a GTK traceback.
- **macOS** — Cocoa/WebKit via `pyobjc`.
- **Windows** — Edge WebView2 via `pywebview[cef]` (or the system WebView2 runtime).

The trade-off: the Qt wheels are bulky (~80 MB install), but the bundled QtWebEngine means a `pipx install condash` works without any system WebKit + GTK plumbing — a huge win on fresh Linux machines.

### When to prefer `--no-native`

Browser mode (`--no-native` / `native = false`) skips `pywebview` entirely. The HTTP server starts and prints the URL; you open it in your normal browser.

Reasons:

- **No DISPLAY / headless host.** Pywebview's Qt backend will try to open a GUI and fail silently, leaving the window absent but the server running. `--no-native` surfaces this: no window, no confusion.
- **Testing / automation.** Driving the dashboard via Playwright or Chromium DevTools is easier against a plain HTTP URL than a pywebview-wrapped one.
- **Qt linking problems.** If PyQt6 fails to import for any reason (mismatched system libraries, container constraints), the CLI still works.

On Linux without `DISPLAY`, the native window fails silently and the HTTP server keeps running — use `--no-native` to avoid the misleading "window didn't open" experience.

### Why pywebview, not a dedicated Electron-style bundle

Electron would triple install size and add an update-manager problem. pywebview uses whatever native webview the OS already ships, so the Python dependency stack stays the binary. Downside: every platform's webview has quirks (see PDF.js below), but they're quirks we can work around in a few hundred lines of Python.

## Vendored assets

The dashboard's non-trivial client-side dependencies are **vendored into the package**, not fetched from a CDN. Two of them:

### PDF.js

In-modal PDF previews use Mozilla's PDF.js. The library lives under `src/condash/assets/vendor/pdfjs/` and is served by the `/vendor/pdfjs/{rel_path:path}` route in [`app.py`](https://github.com/vcoeur/condash/blob/main/src/condash/app.py).

Why not the webview's built-in PDF renderer: QtWebEngine ships with `PdfViewerEnabled=false` by default, and even turning it on gives you a fixed viewer UI we can't theme. Chromium / Edge have native PDF viewers but again, no theming hooks.

The vendored PDF.js lets us:

- Match the dashboard's dark / light theme on the viewer toolbar.
- Skip the 10 MB of unused viewer assets (locale strings, thumbnail panel, annotation editor).
- Wire the viewer's rendering loop to the in-modal `Ctrl+F` search bar eventually.

### xterm.js

The embedded terminal uses xterm.js plus `xterm-addon-fit`, served from `/vendor/xterm/`. Same rationale but a different failure mode: **an uncached CDN fetch breaks offline installs.**

condash is often run in air-gapped or aggressively-sandboxed environments (corporate laptops with blocked egress, Claude Code sandboxes, development VMs without internet). A runtime CDN fetch turns "start condash" into "start condash and hope for network" — a terrible property for a local-first tool. Vendoring cost us ~400 KB of package size and gave us a terminal that starts in ~50 ms, guaranteed.

### Pointer

- `src/condash/assets/vendor/pdfjs/` — Mozilla PDF.js bundle + cmaps, standard fonts, wasm, iccs.
- `src/condash/assets/vendor/xterm/` — xterm.js + CSS + fit addon.

Both served behind path-validating `/vendor/<name>/{rel_path:path}` routes that reject `..` escapes and null bytes. Standard fare for serving bundled assets out of a Python package.

## Wrapping up

None of this is novel. The interesting parts are what we **didn't** build: no cache, no watcher, no schema, no lock files, no auth, no sync. The dashboard is a thin FastAPI + NiceGUI layer over a directory of Markdown files, and the design is almost entirely about keeping it that way as features accumulate.

If you want to contribute or poke deeper, the [source on GitHub](https://github.com/vcoeur/condash) is ~5.9k lines of Python. The modules most worth reading first:

- [`parser.py`](https://github.com/vcoeur/condash/blob/main/src/condash/parser.py) — the tree walker and the fingerprint computation.
- [`config.py`](https://github.com/vcoeur/condash/blob/main/src/condash/config.py) — the three-file split and its loader / saver pair.
- [`app.py`](https://github.com/vcoeur/condash/blob/main/src/condash/app.py) — every HTTP route + the PTY session registry.
- [`mutations.py`](https://github.com/vcoeur/condash/blob/main/src/condash/mutations.py) — the write surface; compare against the [mutation model reference](../reference/mutations.md) for overlap.
