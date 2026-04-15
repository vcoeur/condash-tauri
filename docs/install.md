---
title: Install · condash
description: How to install condash, create a config, and register it with your desktop launcher.
---

# Install

## From PyPI

```bash
pipx install condash
# or: uv tool install condash
```

Both install `condash` into its own isolated venv and put it on your `$PATH`. The dashboard will not launch until you have created and filled in a config file — see [First launch](#first-launch).

## System prerequisites

None on Linux, macOS, or Windows. `condash` ships its native-window backend as a Python dependency: `pywebview[qt]` pulls `PyQt6` + `PyQt6-WebEngine` + `QtPy` from PyPI, and those wheels bundle Qt itself. A vanilla `pipx install condash` is therefore self-contained.

- **Linux** — pywebview prefers GTK if `python3-gi` happens to be installed system-wide, but otherwise falls back to the bundled Qt backend with no extra setup.
- **macOS** — pywebview uses the native Cocoa WebKit backend by default; Qt is available as a fallback.
- **Windows** — pywebview uses the native Edge WebView2 backend by default; Qt is available as a fallback.

Install size is ~100 MB because of the bundled Qt wheels. If you'd rather skip the native window entirely, set `native = false` in your config and condash will serve the dashboard in your usual browser at `http://127.0.0.1:<port>`.

## First launch

`condash` does not ship with a working default config — it has no way to guess where your markdown tree lives. Bootstrap one:

```bash
condash init                       # writes ~/.config/condash/config.toml
condash config edit                # opens it in $VISUAL / $EDITOR
```

The template is fully commented out. Uncomment and edit the lines you need:

```toml
conception_path = "/path/to/conception"
workspace_path  = "/path/to/code/workspace"   # optional; enables the repo strip
worktrees_path  = "/path/to/git/worktrees"    # optional; "open in IDE" sandbox
port            = 0                           # 0 = OS picks a free port; set e.g. 3434 to pin
native          = true                        # false = browser window instead of desktop

[repositories]
primary = ["repo-a", "repo-b"]
secondary = ["repo-c", "repo-d"]

[open_with.main_ide]
label    = "Open in main IDE"
commands = ["idea {path}", "idea.sh {path}"]

[open_with.secondary_ide]
label    = "Open in secondary IDE"
commands = ["code {path}", "codium {path}"]

[open_with.terminal]
label    = "Open terminal here"
commands = ["ghostty --working-directory={path}", "gnome-terminal --working-directory {path}"]
```

`conception_path` is required. Everything else is optional:

- `workspace_path` — directory containing your code repositories. Every direct subdirectory that contains a `.git/` shows up in the dashboard's repo strip. If unset, the entire repo strip is hidden.
- `worktrees_path` — second directory the "open in IDE" action treats as a safe sandbox alongside `workspace_path`. Useful if you keep extra git worktrees outside the main workspace tree.
- `port` — TCP port for the embedded HTTP server. `0` (default) lets the OS pick a free port. Set a fixed value if you want to reach the dashboard from your browser at `http://127.0.0.1:<port>`.
- `native` — `true` (default) opens a desktop window via pywebview. `false` skips the native window.
- `[repositories]` — `primary` and `secondary` are bare directory names (not paths) matched against what is found under `workspace_path`. Anything left over lands in an "Others" card.
- `[open_with.<slot>]` — three vendor-neutral launcher slots (`main_ide`, `secondary_ide`, `terminal`). Each has a `label` (tooltip) and a `commands` fallback chain. Commands are single shell-style strings parsed with `shlex`; the literal `{path}` is replaced with the absolute repo path. Tried in order until one starts.

Once `conception_path` is set, run `condash` to launch.

## Editing the config from inside the app

Click the gear icon in the dashboard header (next to the light/dark toggle). A modal opens with form fields for every option above; saving writes the file atomically (preserving comments via `tomlkit`) and reloads the dashboard. Path / repositories / open-with changes apply on reload; changes to `port` or `native` require a `condash` restart, and the modal will tell you so.

## Linux: register condash in your application launcher

`condash install-desktop` writes a user-local XDG desktop entry plus the bundled SVG icon, so condash appears in GNOME Activities, KDE Kickoff, Cinnamon menu, and other launchers that read `~/.local/share/applications`:

```bash
condash install-desktop
```

This installs:

- `~/.local/share/applications/condash.desktop` — the launcher entry, pointing at the absolute path of whichever `condash` binary you ran the command with (survives pipx / venv isolation)
- `~/.local/share/icons/hicolor/scalable/apps/condash.svg` — the SVG app icon

No `sudo` and no system-wide changes. Remove with `condash uninstall-desktop`.

The native window also picks up the same icon at runtime via pywebview, so it appears in your taskbar and Alt-Tab switcher.

## Development from a source checkout

```bash
git clone https://github.com/vcoeur/condash.git
cd condash
uv sync --all-extras
uv run condash --version
uv run condash                     # launches the native window, reading ~/.config/condash/config.toml
```
