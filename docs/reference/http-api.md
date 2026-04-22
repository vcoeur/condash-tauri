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
| Dashboard shell | `/`, `/favicon.*`, `/fragment` | Page HTML, favicons, partial re-renders |
| Change polling | `/check-updates`, `/search-history` | Fingerprints + global search |
| Notes | `/note`, `/note-raw`, `/note/*` | Read, edit, rename, create, upload |
| Assets | `/download`, `/asset`, `/file` | Streaming bytes for PDFs, images, arbitrary files |
| Mutations | `/toggle`, `/add-step`, `/edit-step`, `/remove-step`, `/reorder-all`, `/set-priority` | README edits |
| Openers | `/open`, `/open-doc`, `/open-folder`, `/open-external` | Launch external processes |
| Meta / clipboard | `/config`, `/clipboard`, `/recent-screenshot` | Config r/w, Qt clipboard, screenshot-paste lookup |
| Vendored assets | `/vendor/pdfjs/…`, `/vendor/xterm/…` | pdf.js + xterm.js bundles |
| Terminal | `WS /ws/term` | Interactive PTY |

For mutation semantics (what each route writes), see [Mutation model](mutations.md).

## Dashboard shell

| Method | Path | Returns |
|---|---|---|
| GET | `/` | Full dashboard HTML. Re-parses the conception tree on every call. |
| GET | `/favicon.svg`, `/favicon.ico` | Bundled SVG app icon |
| GET | `/fragment?id=<id>` | HTML subtree for one card or one knowledge directory |

`/fragment` ids:

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
| GET | `/check-updates` | Cheap full-tree fingerprint — client polls every 5 s |
| GET | `/search-history?q=<query>` | Ranked search across README bodies, notes, filenames |

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

`/search-history` returns a list of per-item hits ranked by [`condash-state::search::search_items`](https://github.com/vcoeur/condash/blob/main/crates/condash-state/src/search.rs). Empty `q` returns `[]`.

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
| GET | `/download/{rel}` | PDF download with `Content-Disposition: inline`. Rejects non-PDF paths. |
| GET | `/asset/{rel}` | Image assets embedded in Markdown previews. 5-minute public cache. |
| GET | `/file/{rel}` | Any file under the conception tree — used by the in-modal PDF + image viewer. 60 s private cache. |

All three re-validate the path against conception-tree regexes on every call. 403 on escape.

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

## Meta, clipboard, config

| Method | Path | Purpose |
|---|---|---|
| GET | `/config` | Full runtime config as JSON (merged TOML + YAML) |
| POST | `/config` | Save the config. Returns `{ok, restart_required: [...], config}` |
| GET | `/clipboard` | System clipboard text. Tries Qt `QClipboard`, then `wl-paste` / `xclip` / `xsel`. |
| POST | `/clipboard` | Set the system clipboard. Body is the raw text. |
| GET | `/recent-screenshot` | `{path, dir, reason?}` — path of the newest image file in `terminal.screenshot_dir` |

`GET /config` returns a flat JSON matching the dashboard's gear-modal form. `yaml_source` / `preferences_yaml_source` show where the YAML fields currently come from (useful for debugging per-tree vs per-machine overrides).

`/clipboard` works in both native and browser mode: the Qt `QClipboard` path is taken when `native=true`; otherwise the subprocess fallbacks handle Wayland / X11.

`/recent-screenshot` powers the screenshot-paste shortcut. `reason` is one of `directory does not exist`, `configured path is not a directory`, `permission denied`, `no image files found`. The client pastes `path` into the active terminal tab without appending a newline.

## Vendored assets

| Method | Path | Purpose |
|---|---|---|
| GET | `/vendor/pdfjs/{rel}` | Mozilla PDF.js (worker, cmaps, fonts, wasm, iccs). 24-hour cache. |
| GET | `/vendor/xterm/{rel}` | xterm.js library + CSS + `addon-fit`. 24-hour cache. |

Both routes reject `..` and null bytes; files outside the bundled directory 403.

Why vendored: QtWebEngine ships with `PdfViewerEnabled=false`, so the in-modal viewer can't rely on the webview's built-in PDF renderer. And a CDN fetch for xterm.js breaks offline / air-gapped installs. See [internals](../explanation/internals.md#vendored-assets).

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

If you want to drive condash from a second tool, run `condash-serve` with a pinned `CONDASH_PORT` — it prints the bound URL on startup. Without `CONDASH_PORT` set, the port is picked from `11111–12111` at launch.
