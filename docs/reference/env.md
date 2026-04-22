---
title: Environment variables · condash reference
description: The short list of environment variables condash reads.
---

# Environment variables

## At a glance

| Name | Purpose | Default | Accepted values |
|---|---|---|---|
| `CONDASH_CONCEPTION_PATH` | Path to the conception tree condash renders | `$HOME/src/vcoeur/conception` | Any absolute path to a directory containing `projects/` |
| `CONDASH_ASSET_DIR` | Override the embedded dashboard bundle with a live directory on disk | unset (use the `rust-embed` bundle compiled into the binary) | Path to a directory with the same layout as `frontend/` |
| `CONDASH_PORT` | Pin the listen port of `condash-serve` | pick a free port in `11111–12111` | `1024–65535` |
| `SHELL` | Fallback for `terminal.shell` | `/bin/bash` | Absolute path to an interactive shell |

## `CONDASH_CONCEPTION_PATH`

The only variable condash absolutely needs. If unset, the loader falls back to `$HOME/src/vcoeur/conception` — works out of the box when you keep your tree at that location, otherwise set this explicitly in your shell's rc file.

```bash
export CONDASH_CONCEPTION_PATH="$HOME/src/vcoeur/conception"
```

One-shot overrides for a single run:

```bash
CONDASH_CONCEPTION_PATH=/tmp/scratch-tree condash
```

Or set the path via the gear modal's **General** tab — the modal stores it in the tree's `preferences.yml` (not the environment) so it survives shell sessions.

## `CONDASH_ASSET_DIR`

Development-only. When set, the embedded dashboard bundle (compiled into the binary via `rust-embed`) is bypassed and files are served from the directory you point at instead. Handy when iterating on CSS or JS without rebuilding the Rust binary on every change:

```bash
CONDASH_ASSET_DIR=frontend/ condash-serve
# in another shell: edit frontend/src/..., then `make frontend`, then hard-refresh
```

See [`src-tauri/src/assets.rs`](https://github.com/vcoeur/condash/blob/main/src-tauri/src/assets.rs) for the path resolution.

## `CONDASH_PORT`

Read by `condash-serve` only (the Tauri `condash` binary always picks a free port automatically — the window doesn't care what port the embedded server uses).

```bash
CONDASH_PORT=11500 condash-serve
```

Useful for Playwright fixtures that need a stable URL, and for running two `condash-serve` instances side by side against different trees.

## `SHELL`

Standard POSIX shell variable. Used as the fallback command when `terminal.shell` is not configured in `preferences.yml`. The embedded terminal spawns a PTY running this shell.

## Not read from the environment

- `CONCEPTION_PATH` — despite the [management skill](skill.md) reading it, condash itself looks for `CONDASH_CONCEPTION_PATH`, not `CONCEPTION_PATH`.
- `PORT` — only the namespaced `CONDASH_PORT` is honoured, to avoid clashing with other tools on the same host.
- `NO_COLOR`, `CLICOLOR`, `FORCE_COLOR` — unused. The dashboard's colour scheme is driven by the theme toggle.
- `VISUAL`, `EDITOR` — condash doesn't spawn an editor itself. Edit `preferences.yml` with whichever editor you like; the gear modal writes it for you otherwise.
