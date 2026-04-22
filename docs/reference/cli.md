---
title: CLI · condash reference
description: The two condash binaries and how to configure them.
---

# CLI

condash ships two binaries. Neither takes subcommands or flags — everything that used to live behind a flag is now either an environment variable or a tab in the in-app gear modal.

## At a glance

| Binary | What it does |
|---|---|
| `condash` | Open the Tauri desktop window against the current conception tree |
| `condash-serve` | Run the HTTP server headless — no webview, no GUI deps |

## `condash`

The main binary. Packaged into the per-OS installer on the [releases page](https://github.com/vcoeur/condash/releases); also produced by `make build-tauri` from source.

```bash
condash
```

That's it — no arguments. The binary boots an embedded axum HTTP server on a free loopback port, then opens a Tauri window pointing at it. On Linux the window uses WebKitGTK; on macOS, WKWebView; on Windows, WebView2.

Closing the window exits the process. Relaunch whenever you want to come back — state lives in the Markdown files, not in the app.

## `condash-serve`

A developer-oriented binary that runs the same HTTP server without opening a window. Produced by `cargo build -p condash --bin condash-serve`, or `make run-serve` when iterating.

```bash
condash-serve
```

Prints the bound URL (e.g. `http://127.0.0.1:11111`) and keeps running until you `Ctrl+C`. Open the URL in your normal browser.

Reasons to use `condash-serve`:

- **Headless host.** No `DISPLAY`, no webview libs, still want the dashboard.
- **Automation.** Playwright / Chromium DevTools drive a plain HTTP URL more cleanly than a Tauri-wrapped one.
- **Frontend iteration.** Combine with `CONDASH_ASSET_DIR=frontend/` to serve the source bundle from disk instead of the embedded copy, then rebuild with `make frontend` in another shell and hard-refresh the browser.

## Configuration

Neither binary reads flags. The two places configuration lives:

1. **Environment variables** — three of them, all prefixed `CONDASH_`:

   | Variable | Meaning |
   |---|---|
   | `CONDASH_CONCEPTION_PATH` | Absolute path to the conception tree to render. Defaults to `$HOME/src/vcoeur/conception`. |
   | `CONDASH_ASSET_DIR` | Override the embedded dashboard bundle with a live directory on disk. Dev-only. |
   | `CONDASH_PORT` | Pin the listen port of `condash-serve`. Defaults to a free port in `11111–12111`. |

   See [Environment variables](env.md) for the full list.

2. **The gear modal in the dashboard.** Click the gear icon in the top right of the window. Three tabs — **General**, **Repositories**, **Preferences** — cover the tree-level YAML config (`<conception_path>/config/repositories.yml`, `<conception_path>/config/preferences.yml`). Saves are atomic and reload live.

## What's not in the CLI

- **Creating items** — the dashboard doesn't create items, and neither does the CLI. Use your editor, or the [management skill](skill.md).
- **Listing or searching items** — use the **History** tab in the dashboard, or `grep` over the tree.
- **A server mode for multiple users** — condash is single-user. If you want multi-user, something else is the right tool.
