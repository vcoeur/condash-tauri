---
title: CLI · condash reference
description: The two condash binaries and how to configure them.
---

# CLI

condash ships two binaries. Neither takes subcommands or flags — everything that used to live behind a flag is now either an environment variable or a line in `settings.yaml` / `configuration.yml`.

## At a glance

| Binary | What it does |
|---|---|
| `condash` | Open the Tauri desktop window against the current conception tree |
| `condash-serve` | Run the HTTP server headless — no webview, no GUI deps |

## `condash`

The main binary. Packaged into the per-OS installer on the [releases page](https://github.com/vcoeur/condash/releases); also produced by `make build` from source.

```bash
condash
```

That's it — no arguments. The binary boots an embedded axum HTTP server on a free loopback port, then opens a Tauri window pointing at it. On Linux the window uses WebKitGTK; on macOS, WKWebView; on Windows, WebView2.

Closing the window exits the process. Relaunch whenever you want to come back — state lives in the Markdown files, not in the app.

## `condash-serve`

A developer-oriented binary that runs the same HTTP server without opening a window. Produced by `cargo build -p condash --bin condash-serve`, or `make serve` when iterating.

```bash
condash-serve
```

Prints the bound URL (e.g. `http://127.0.0.1:43217`) and keeps running until you `Ctrl+C`. Open the URL in your normal browser. Without `CONDASH_PORT`, the OS assigns any free port — the URL varies across launches.

Reasons to use `condash-serve`:

- **Headless host.** No `DISPLAY`, no webview libs, still want the dashboard.
- **Automation.** Playwright / Chromium DevTools drive a plain HTTP URL more cleanly than a Tauri-wrapped one.
- **Frontend iteration.** Combine with `CONDASH_ASSET_DIR=frontend/` to serve the source bundle from disk instead of the embedded copy, then rebuild with `make frontend` in another shell and hard-refresh the browser.

## Configuration

Neither binary reads flags. Configuration lives in three layers (see [Config files](config.md) for the full schema):

1. **Environment variables** — three of them, all prefixed `CONDASH_`:

   | Variable | Meaning |
   |---|---|
   | `CONDASH_CONCEPTION_PATH` | Absolute path to the conception tree to render. Overrides `conception_path` in `settings.yaml`. |
   | `CONDASH_ASSET_DIR` | Override the embedded dashboard bundle with a live directory on disk. Dev-only. |
   | `CONDASH_PORT` | Pin the listen port of `condash-serve`. Unset → any free port. |

   See [Environment variables](env.md) for the full list.

2. **`settings.yaml`** at `${XDG_CONFIG_HOME:-~/.config}/condash/settings.yaml` — per-user, per-machine. Holds `conception_path` plus the three blocks that naturally differ per machine: `terminal`, `pdf_viewer`, `open_with`.
3. **`configuration.yml`** at `<conception_path>/configuration.yml` — per-tree, versioned in git. Holds `workspace_path`, `worktrees_path`, `repositories` (incl. `run:` / `force_stop:`). Edit it by hand or through the gear icon in the dashboard header (plain-text YAML editor).

## What's not in the CLI

- **Creating items** — the dashboard doesn't create items, and neither does the CLI. Use your editor, or the [management skill](skill.md).
- **Listing or searching items** — use the **History** tab in the dashboard, or `grep` over the tree.
- **A server mode for multiple users** — condash is single-user. If you want multi-user, something else is the right tool.
