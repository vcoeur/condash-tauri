---
title: Environment variables · condash reference
description: The short list of environment variables condash reads.
---

# Environment variables

## At a glance

| Name | Purpose | Default | Accepted values |
|---|---|---|---|
| `CONDASH_CONCEPTION_PATH` | Path to the conception tree condash renders | unset — falls through to `settings.yaml`, then to the first-launch folder picker | Any absolute path to a directory containing `projects/` |
| `CONDASH_ASSET_DIR` | Override the embedded dashboard bundle with a live directory on disk | unset (use the `rust-embed` bundle compiled into the binary) | Path to a directory with the same layout as `frontend/` |
| `CONDASH_PORT` | Pin the listen port of `condash-serve` | unset — OS assigns any free port | `1024–65535` |
| `SHELL` | Fallback for `terminal.shell` | `/bin/bash` | Absolute path to an interactive shell |

## `CONDASH_CONCEPTION_PATH`

Optional pointer at the tree to render. condash's resolution order is: env var → `settings.yaml` → first-launch folder picker → hard error. In normal use, the first-launch picker writes the chosen path into `settings.yaml`, so this env var is only useful for overrides.

One-shot override for a single run:

```bash
CONDASH_CONCEPTION_PATH=/tmp/scratch-tree condash
```

Or persist a different path by editing `${XDG_CONFIG_HOME:-~/.config}/condash/settings.yaml` directly — `conception_path: /home/you/other-tree`.

## `CONDASH_ASSET_DIR`

Development-only. When set, the embedded dashboard bundle (compiled into the binary via `rust-embed`) is bypassed and files are served from the directory you point at instead. Handy when iterating on CSS or JS without rebuilding the Rust binary on every change:

```bash
CONDASH_ASSET_DIR=frontend/ condash-serve
# in another shell: edit frontend/src/..., then `make frontend`, then hard-refresh
```

See [`src-tauri/src/assets.rs`](https://github.com/vcoeur/condash/blob/main/src-tauri/src/assets.rs) for the path resolution.

## `CONDASH_PORT`

Read by `condash-serve` only (the Tauri `condash` binary always picks a free port automatically — the window doesn't care what port the embedded server uses). When unset, `condash-serve` asks the OS for any free port; read it from the `condash-serve: listening on …` stderr line.

```bash
CONDASH_PORT=11500 condash-serve
```

Useful for Playwright fixtures that need a stable URL, and for running two `condash-serve` instances side by side against different trees.

## `SHELL`

Standard POSIX shell variable. Used as the fallback command when `terminal.shell` is not configured in `configuration.yml` or `settings.yaml`. The embedded terminal spawns a PTY running this shell.

## Not read from the environment

- `CONCEPTION_PATH` — despite the [management skill](skill.md) reading it, condash itself looks for `CONDASH_CONCEPTION_PATH`, not `CONCEPTION_PATH`.
- `PORT` — only the namespaced `CONDASH_PORT` is honoured, to avoid clashing with other tools on the same host.
- `NO_COLOR`, `CLICOLOR`, `FORCE_COLOR` — unused. The dashboard's colour scheme is driven by the theme toggle.
- `VISUAL`, `EDITOR` — condash doesn't spawn an editor itself. Edit `configuration.yml` or `settings.yaml` with whichever editor you like; the gear modal edits the tree-level file for you otherwise.
