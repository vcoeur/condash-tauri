---
title: Environment variables · condash reference
description: The short list of environment variables condash reads.
---

# Environment variables

## At a glance

| Name | Purpose | Default | Accepted values |
|---|---|---|---|
| `CONDASH_LOG_LEVEL` | Logging verbosity | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `XDG_CONFIG_HOME` | Location of the config directory | `~/.config` | Any absolute path |
| `XDG_PICTURES_DIR` | Fallback for `terminal.screenshot_dir` | `~/Pictures` on Linux, `~/Desktop` on macOS | Any absolute path |
| `XDG_DATA_HOME` | Install target for `install-desktop` | `~/.local/share` | Any absolute path |
| `SHELL` | Fallback for `terminal.shell` | `/bin/bash` | Absolute path to an interactive shell |
| `VISUAL` / `EDITOR` | Editor invoked by `condash config edit` | platform default | Any command on `$PATH` |
| `TERM` | Set **inside** the PTY (not read from env) | `xterm-256color` | — |

## `CONDASH_LOG_LEVEL`

The only condash-specific variable. Case-insensitive; read once at startup in [`cli.py::main`](https://github.com/vcoeur/condash/blob/main/src/condash/cli.py).

```bash
CONDASH_LOG_LEVEL=DEBUG condash --no-native
```

Use `DEBUG` when:

- Shortcuts don't seem to fire — the parsed spec is logged.
- A PTY session dies unexpectedly — pump + reap events are logged.
- A clipboard operation fails — each fallback (Qt, `wl-paste`, `xclip`, `xsel`) logs its failure.

`WARNING` or above is usually enough for production; `INFO` is the default.

## XDG variables

condash honours the three `XDG_*` directory variables for users on non-default setups (e.g. flatpak sandboxes, opinionated dotfiles).

- `XDG_CONFIG_HOME` — base directory for `<XDG_CONFIG_HOME>/condash/config.toml`.
- `XDG_PICTURES_DIR` — used by [`config.py::default_screenshot_dir`](https://github.com/vcoeur/condash/blob/main/src/condash/config.py) when `terminal.screenshot_dir` is not configured.
- `XDG_DATA_HOME` — base directory for `<XDG_DATA_HOME>/applications/condash.desktop` and the icon, via [`desktop.py`](https://github.com/vcoeur/condash/blob/main/src/condash/desktop.py).

## Editor and shell

- `VISUAL`, then `EDITOR`, then the OS default (`xdg-open` on Linux, `open` on macOS, `notepad` on Windows) — in that order — picks the binary `condash config edit` launches.
- `SHELL` is the terminal pane's fallback when `terminal.shell` is unset. See [config files](config.md).

## Not read from the environment

- `CONCEPTION_PATH` — despite the [management skill](skill.md) reading it, condash itself does not. The CLI flag is `--conception-path`; the config key is `conception_path`.
- `PORT` / `CONDASH_PORT` — use `--port` or the `port` config key.
- `NO_COLOR`, `CLICOLOR`, `FORCE_COLOR` — unused. The dashboard's colour scheme is driven by the theme toggle, and the CLI output is plain text.
