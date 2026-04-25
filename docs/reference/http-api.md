---
title: HTTP + WebSocket API · condash reference
description: Every route the embedded axum server exposes — useful when scripting condash, debugging, or wiring a second tool on top of the same data.
---

# HTTP + WebSocket API

## At a glance

condash runs a local axum server bound to `127.0.0.1:<port>`. The main `condash` binary wraps it in a Tauri window; `condash-serve` runs the same server headless for browsers and automation. All routes are local-only — there is no auth layer, and condash never binds to a non-loopback address.

Groups:

| Area | Routes | Purpose |
|---|---|---|
| Dashboard shell | `/`, `/favicon.*`, `/fragment`, `/fragment/{history,knowledge,code,projects}` | Page HTML, favicons, per-node + per-pane fragments |
| Change polling | `/check-updates`, `/events` | Per-node fingerprints (legacy reloadNode); SSE stream that drives htmx tab refreshes |
| Notes | `/note`, `/note-raw`, `/note/*` | Read, edit, rename, create, upload |
| Assets | `/asset/{*path}` | Streaming bytes for PDFs, images, arbitrary files under the conception tree |
| Mutations | `/toggle`, `/add-step`, `/edit-step`, `/remove-step`, `/reorder-all`, `/set-priority` | README edits |
| Openers | `/open`, `/open-doc`, `/open-folder`, `/open-external` | Launch external processes |
| Meta | `/configuration`, `/config`, `/recent-screenshot` | Config r/w, summary, screenshot-paste lookup |
| Vendored assets | `/vendor/{*path}` | PDF.js + xterm.js + CodeMirror + Mermaid + htmx bundles |
| Terminal | `WS /ws/term` | Interactive PTY |

For mutation semantics (what each route writes), see [Mutation model](mutations.md).

## Dashboard shell

| Method | Path | Returns |
|---|---|---|
| GET | `/` | Full dashboard HTML. Re-parses the conception tree on every call. |
| GET | `/favicon.svg`, `/favicon.ico` | Bundled SVG app icon |
| GET | `/fragment?id=<id>` | HTML subtree for one card or one knowledge node (the legacy per-id surface; called from `reloadNode` after explicit mutations) |
| GET | `/fragment/history?q=<query>` | History pane content. Empty `q` → month-grouped tree; non-empty `q` → search-results list. Driven by htmx on `#history-content` |
| GET | `/fragment/knowledge` | Knowledge tree pane content. Refreshed on `sse:knowledge` |
| GET | `/fragment/code` | Git strip pane content. Refreshed on `sse:code`. Runner-viewer mounts inside carry `hx-preserve="true"` so xterm + WebSocket-attached terminals survive the morph swap |
| GET | `/fragment/projects` | Cards-grid pane content. Refreshed on `sse:projects`. Each card has `id="<slug>"` so Idiomorph keys swaps by it; client `htmx:beforeSwap`/`afterSwap` hooks re-apply expanded class + active-subtab visibility |

`/fragment` ids (legacy per-node):

| Shape | Returns |
|---|---|
| `projects/<priority>/<slug>` | One project card. |
| `knowledge/<path>.md` | One knowledge card. |
| `knowledge/<path>` (dir) | Knowledge directory subtree. |
| `knowledge` (root) | 404 — client falls back to full-page reload. |
| Anything else | 404. |

## Change polling

| Method | Path | Purpose |
|---|---|---|
| GET | `/check-updates` | Per-node fingerprint map. Now only used by `reloadNode` callers to refresh a single subtree's baseline after an explicit mutation; the htmx-driven panes don't poll |
| GET | `/events` | Server-sent events stream. Each frame is a named event (`event: projects` / `knowledge` / `code`) carrying `{tab, ts, file?}`; `hx-trigger="sse:<tab>"` on each pane re-fetches the matching `/fragment/<tab>` |

`/check-updates` response shape:

```json
{
  "fingerprint": "0123456789abcdef",
  "git_fingerprint": "fedcba9876543210",
  "nodes": {
    "projects": "…",
    "projects/now": "…",
    "projects/now/2026-04-18-helio-benchmark-harness": "…",
    "knowledge/topics/playwright-sandbox.md": "…"
  }
}
```

`fingerprint` is the 16-hex MD5 of the whole-tree repr; a change at any level flips it. `nodes` is a flat map that lets the client decide **which** subtree changed and re-fetch just that — preventing full-page flicker on a single step toggle. See [internals](../explanation/internals.md#parser-and-fingerprints) for how the hashes are computed.

The History tab's full-text search route used to be `GET /search-history?q=<query>` returning JSON. It moved to the htmx-driven `GET /fragment/history?q=<query>` (HTML) when the History tab migrated; the JSON route is gone.

## Notes

All paths are relative to `conception_path`.

| Method | Path | Body / Query | Response |
|---|---|---|---|
| GET | `/note?path=<rel>` | – | HTML render of a Markdown / text / PDF / image note |
| GET | `/note-raw?path=<rel>` | – | `{path, content, mtime, kind}` for the edit view |
| POST | `/note` | `{path, content, expected_mtime?}` | `{ok, mtime}` or 409 `{ok: false, reason}` on mtime drift |
| POST | `/note/rename` | `{path, new_stem}` | `{ok, path, mtime}` |
| POST | `/note/create` | `{item_readme, filename, subdir?}` | `{ok, path, mtime}` |
| POST | `/note/mkdir` | `{item_readme, subpath}` | `{ok, rel_dir, subdir_key}` or 409 `{reason: "exists"}` |
| POST | `/note/upload` | `multipart/form-data` with `item_readme`, optional `subdir`, `file` parts | `{ok, stored: [...], rejected: [...]}` |

Upload size cap: **50 MB per file**. Collisions auto-suffix `(2)`, `(3)`…

See [mutations](mutations.md) for the filename regexes and sandbox rules.

## Asset streaming

| Method | Path | Purpose |
|---|---|---|
| GET | `/asset/{*path}` | Any file under the conception tree — PDFs, images embedded in Markdown previews, deliverables, anything linked from a note. 24-hour public cache. |

`path` is taken relative to `conception_path`. The handler canonicalises it, refuses to escape the tree, and 403s on a `..` / null-byte / sandbox-escape attempt; 404s if the file is missing. `Content-Type` is inferred from the file extension via [`mime_guess`](https://docs.rs/mime_guess).

## Mutations

All operate on an item's `README.md` by line number. See [mutations](mutations.md) for the effect on the file.

| Method | Path | Body |
|---|---|---|
| POST | `/toggle` | `{file, line}` — cycles `[ ]→[x]→[~]→[-]→[ ]` |
| POST | `/add-step` | `{file, text, section?}` |
| POST | `/edit-step` | `{file, line, text}` |
| POST | `/remove-step` | `{file, line}` |
| POST | `/reorder-all` | `{file, order: [line, line, …]}` |
| POST | `/set-priority` | `{file, priority}` — one of `now/soon/later/backlog/review/done` |

All return `{ok: true, …}` on success or `{error: "<message>"}` with 400 on validation failure.

## Openers

These launch external processes. **No filesystem writes** — but they do mean "condash runs a shell command", so the sandbox regexes matter.

| Method | Path | Body | What runs |
|---|---|---|---|
| POST | `/open` | `{path, tool}` | `cfg.open_with[tool].commands` chain. `path` must resolve under `workspace_path` or `worktrees_path`. |
| POST | `/open-doc` | `{path}` | `cfg.pdf_viewer` chain for `.pdf`, OS default for everything else. `path` under `conception_path`. |
| POST | `/open-folder` | `{path}` | OS default file manager. `path` must match `projects/YYYY-MM/YYYY-MM-DD-slug/`. |
| POST | `/open-external` | `{url}` | User's default browser. URL must be `http(s)://…`. |

## Meta + config

| Method | Path | Purpose |
|---|---|---|
| GET | `/configuration` | Raw `<conception_path>/configuration.yml` as `text/yaml`. Empty string if the file does not exist. |
| POST | `/configuration` | Replace `configuration.yml`. Body is the plain-text YAML (not JSON) the gear modal's textarea contains. The handler parses the body, rejects invalid YAML with 400 + parse error, and atomically writes via `.tmp` + rename. |
| GET | `/config` | Small JSON summary the frontend polls on load: `{conception_path, terminal}`. Used for the first-run setup banner and to pick up terminal-shortcut changes without a full reload. **Does not** return the full runtime config. |
| GET | `/recent-screenshot` | `{path, dir, reason?}` — path of the newest image file in `terminal.screenshot_dir`. |

### Clipboard

There is **no** HTTP clipboard endpoint. The dashboard reads and writes the system clipboard through [`tauri-plugin-clipboard-manager`](https://v2.tauri.app/plugin/clipboard-manager/) in the Tauri build, and falls back to the browser's native [`navigator.clipboard`](https://developer.mozilla.org/docs/Web/API/Clipboard_API) API when run under `condash-serve` in a browser.

### `/recent-screenshot`

Powers the screenshot-paste shortcut. `reason` is one of `directory does not exist`, `configured path is not a directory`, `permission denied`, `no image files found`. The client pastes `path` into the active terminal tab without appending a newline.

## Vendored assets

| Method | Path | Purpose |
|---|---|---|
| GET | `/vendor/{*path}` | Bundled third-party assets embedded in the binary. 24-hour public cache. |

The single route covers four vendored subtrees:

| Prefix | Contents |
|---|---|
| `/vendor/pdfjs/…` | Mozilla PDF.js (worker, cmaps, fonts, wasm, iccs). |
| `/vendor/xterm/…` | xterm.js library + CSS + `addon-fit`. |
| `/vendor/codemirror/…` | CodeMirror 6 editor bundle used by the note editor and the gear modal's YAML pane. |
| `/vendor/mermaid/…` | Mermaid's UMD bundle for rendering Mermaid code blocks inside the note preview modal. |
| `/vendor/htmx/…` | htmx core + the SSE + Idiomorph extensions. Drives the per-tab fragment refresh on `sse:<tab>` and identity-stable swap (cards, knowledge tree, runner mounts). |

`..` and null bytes are rejected; paths outside the bundled directory 403.

Why vendored: Tauri ships with the system's webview, and a CDN fetch for any of these bundles breaks offline / air-gapped installs. The binary stays self-contained by embedding all four libraries via `rust-embed`.

## Terminal WebSocket

| Method | Path | Purpose |
|---|---|---|
| WS | `/ws/term` | Interactive PTY session (Linux + macOS only) |

Query parameters:

| Param | Meaning |
|---|---|
| `session_id=<id>` | Reattach to an existing PTY session. If the id is unknown, the server sends `{type: "session-expired"}` and closes. |
| `cwd=<path>` | Start the new shell in this directory. Must resolve under `workspace_path` / `worktrees_path`. Silently ignored otherwise. |
| `launcher=1` | Exec `terminal.launcher_command` instead of a login shell. |

Frames, server → client:

| Type | Shape |
|---|---|
| Binary | Raw bytes from the PTY — append to the xterm buffer verbatim. |
| Text JSON `{type: "info", session_id, shell, cwd}` | First frame after attach. |
| Text JSON `{type: "exit"}` | Shell exited. The server closes the socket immediately after. |
| Text JSON `{type: "session-expired", session_id}` | Requested session is gone. Drop it from localStorage. |
| Text JSON `{type: "error", message}` | Unsupported platform (Windows) or other fatal refusal. |

Frames, client → server:

| Shape | Meaning |
|---|---|
| Binary | Raw input to the PTY. |
| Text JSON `{type: "resize", cols, rows}` | `TIOCSWINSZ` relay. |

The PTY survives the WebSocket: a page refresh detaches cleanly and the buffer (256 KiB ring) replays on the next attach. See [guide: using the embedded terminal](../guides/terminal.md) for the end-user surface.

## Auth, CORS, bind address

- Server binds to `127.0.0.1` only. Non-loopback addresses are never used.
- No auth layer. The sandbox is "only localhost traffic can reach the server".
- No CORS headers — the dashboard lives on the same origin.
- No multi-user mode; condash is single-user by design.

If you want to drive condash from a second tool, run `condash-serve` with a pinned `CONDASH_PORT` — it prints the bound URL on startup. Without `CONDASH_PORT` set, the server asks the OS for any free port (`bind(… 0)`), so the port varies across launches; read it from the `condash-serve: listening on …` stderr line.
