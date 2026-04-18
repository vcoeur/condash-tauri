---
title: CLI · condash reference
description: Every subcommand and flag the condash CLI accepts.
---

# CLI

## At a glance

| Command | What it does |
|---------|-------------|
| `condash` | Launch the dashboard (default) |
| `condash init` | Write the template config file |
| `condash config show` | Print the effective (resolved) config |
| `condash config path` | Print the config file path |
| `condash config edit` | Open the config in `$VISUAL` / `$EDITOR` |
| `condash install-desktop` | Register an XDG launcher entry (Linux) |
| `condash uninstall-desktop` | Remove the launcher entry |

## `condash` (launch the dashboard)

```bash
condash [--version]
        [--conception-path PATH]
        [--config PATH]
        [--port PORT]
        [--native | --no-native]
```

With no subcommand, `condash` launches the native window against the effective config. On Linux without `DISPLAY`, the window fails silently and the HTTP server keeps running — use `--no-native` to avoid the misleading "window didn't open" experience in that case.

| Flag | Meaning |
|------|---------|
| `--version` | Print version and exit. |
| `--conception-path PATH` | One-shot override of `conception_path`. Does not touch the config file. |
| `--config PATH` | Use a different config file instead of the default `$XDG_CONFIG_HOME/condash/config.toml`. |
| `--port PORT` | One-shot override of `port`. `0` lets the OS pick a free port. |
| `--native` | Force the native window on for this launch (overrides `native = false` in config). |
| `--no-native` | Force browser mode for this launch (overrides `native = true` in config). Useful in headless environments or when the Qt/GTK backend isn't available. |

All `--*` flags are **one-shot** — they take effect for that process and never write to the config file. Useful for testing against a scratch tree or running a second condash instance side by side (pass `--port` and a different `--config`).

### Exit codes

| Code | Meaning |
|------|---------|
| `0`  | Clean shutdown |
| `1`  | Config error (missing required field, unparseable TOML/YAML, invalid value) |
| `2`  | `condash init` refused to overwrite an existing config |

## `condash init`

Writes a commented template config to `$XDG_CONFIG_HOME/condash/config.toml` (or `~/.config/condash/config.toml` if `$XDG_CONFIG_HOME` isn't set). Refuses to overwrite an existing file — delete it first, or use `condash config edit` to modify in place.

The template is fully commented; `conception_path` is the only field you must uncomment before the dashboard will start. Every other key has a reasonable default (see [Config files](config.md)).

## `condash config`

Three subcommands that all operate on the resolved config.

```bash
condash config show [--json]
condash config path [--json]
condash config edit
```

| Subcommand | Output |
|------------|--------|
| `show` | Human-readable dump of the effective config (file + defaults merged). Add `--json` for machine-parseable output. |
| `path` | Absolute path to the config file being used. `--json` wraps it in `{"path": "..."}`. |
| `edit` | Open the config file in `$VISUAL`, or `$EDITOR`, or `nano` as a fallback. Exits after the editor quits. |

Use `show` when you're debugging "why is condash using that path" without hand-parsing the TOML + YAML.

## `condash install-desktop`

**Linux only.** Registers `condash` with the XDG application launcher so it appears in your OS launcher / menu / Activities view like any other GUI app.

```bash
condash install-desktop
```

Writes two files:

- `~/.local/share/applications/condash.desktop` — launcher entry, pointing at the absolute path of whichever `condash` binary ran the command (survives `pipx` / `venv` isolation).
- `~/.local/share/icons/hicolor/scalable/apps/condash.svg` — the SVG app icon.

No `sudo`, no system-wide changes. The native window also picks up the same icon at runtime via `pywebview`, so it appears correctly in your taskbar and Alt-Tab switcher.

## `condash uninstall-desktop`

```bash
condash uninstall-desktop
```

Removes both files that `install-desktop` wrote. Idempotent.

## What's not in the CLI

- **Creating items** — the dashboard doesn't create items, and neither does the CLI. Use your editor, or the [management skill](skill.md).
- **Listing or searching items** — use the **History** tab in the dashboard, or `grep` over the tree.
- **A server mode** — condash is single-user. If you want multi-user, something else is the right tool.
