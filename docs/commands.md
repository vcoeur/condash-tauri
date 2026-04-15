---
title: Commands · condash
description: Full CLI reference for condash — dashboard, init, config, tidy, desktop entry.
---

# Commands

`condash` is primarily a desktop app: running `condash` with no arguments launches the native window. A handful of subcommands handle setup and maintenance.

## Launching the dashboard

```bash
condash                            # open the dashboard window
condash --version                  # print version and exit
condash --conception-path PATH     # one-shot override (does not touch the config file)
condash --config PATH              # use a different config file
```

`--conception-path` is a convenience override — useful for testing another markdown tree without rewriting the config, or for scripting. `--config` lets you keep multiple configs side by side.

## `condash init`

Writes a commented template to `~/.config/condash/config.toml`. Idempotent — refuses to overwrite an existing file unless explicitly asked.

```bash
condash init
```

The template has every option commented out. Only `conception_path` is strictly required before the dashboard will launch. See [Install → First launch](install.md#first-launch) for the full config reference.

## `condash config`

```bash
condash config show                # print the effective configuration (merged from file + defaults)
condash config edit                # open the config file in $VISUAL / $EDITOR
```

`config show` prints the resolved values — useful for debugging "why is condash using that path" without hand-parsing the TOML.

## `condash tidy`

Sweeps done items into `YYYY-MM/` archive folders so the active directories (`projects/`, `incidents/`, `documents/`) only show in-progress work.

```bash
condash tidy
```

Same behaviour as the tidy button in the dashboard footer. Looks for items with `**Status**: done`, picks the item's completion month from its `## Timeline`, and moves the folder to `projects/YYYY-MM/<slug>/` (or the equivalent under `incidents/` / `documents/`).

## Linux desktop entry

```bash
condash install-desktop            # register with the XDG application launcher
condash uninstall-desktop          # remove the user-local entry
```

`install-desktop` writes `~/.local/share/applications/condash.desktop` plus `~/.local/share/icons/hicolor/scalable/apps/condash.svg`. No `sudo`, no system-wide changes. The `.desktop` entry points at the absolute path of whichever `condash` binary you ran the command with, so it survives pipx / venv isolation.

See [Install → Linux](install.md#linux-register-condash-in-your-application-launcher) for the full story.
