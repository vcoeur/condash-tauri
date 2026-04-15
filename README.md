# condash

**Standalone desktop dashboard for markdown-based conception projects, incidents, and documents.**

`condash` is a single-user native-feeling application that renders a live dashboard of a directory tree of projects, incidents, and documents written as Markdown — originally the `conception` repo convention (`projects/YYYY-MM-DD-slug/README.md`, `incidents/…`, `documents/…`). It lets you browse them, track `## Steps` checklists, toggle item status, reorder steps, open files in your IDE, and tidy done items into monthly archive folders — all from one window backed by the same Markdown files you edit by hand.

## Install

```bash
pipx install condash
# or: uv tool install condash
```

Both install the CLI into its own isolated venv and put `condash` on your `$PATH`. The dashboard will not launch until you have created and filled in a config file — see [First launch](#first-launch).

### System prerequisites

None on Linux, macOS, or Windows. `condash` ships its native-window backend as a Python dependency: `pywebview[qt]` pulls `PyQt6` + `PyQt6-WebEngine` + `QtPy` from PyPI, and those wheels bundle Qt itself. A vanilla `pipx install condash` is therefore self-contained:

```bash
pipx install condash
```

- **Linux** — pywebview prefers GTK if `python3-gi` happens to be installed system-wide, but otherwise falls back to the bundled Qt backend with no extra setup.
- **macOS** — pywebview uses the native Cocoa WebKit backend by default; Qt is available as a fallback.
- **Windows** — pywebview uses the native Edge WebView2 backend by default; Qt is available as a fallback.

Install size is ~100 MB because of the bundled Qt wheels — that's the cost of "works everywhere with one command". If you'd rather skip the native window entirely, set `native = false` in your config (see [First launch](#first-launch)) and condash will serve the dashboard in your usual browser at `http://127.0.0.1:<port>`.

### Development from a source checkout

```bash
git clone https://github.com/vcoeur/condash.git
cd condash
uv sync --all-extras
uv run condash --version
uv run condash               # launches the native window, reading ~/.config/condash/config.toml
```

## First launch

`condash` does not ship with a working default config — it has no way to guess where your conception directory lives. Bootstrap one:

```bash
condash init           # writes a commented template at ~/.config/condash/config.toml
condash config edit    # opens the template in $VISUAL / $EDITOR
```

The template is fully commented out. Uncomment and edit the lines you need:

```toml
conception_path = "/path/to/conception"
workspace_path  = "/path/to/code/workspace"   # optional; enables the repo strip
worktrees_path  = "/path/to/git/worktrees"    # optional; "open in IDE" sandbox
port            = 0                           # 0 = OS picks a free port; set e.g. 3434 to pin one
native          = true                        # false = open in your browser instead of a desktop window

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

- `workspace_path` — directory containing your code repositories. Every direct subdirectory that contains a `.git/` is shown in the dashboard's repo strip. If unset, the entire repo strip is hidden.
- `worktrees_path` — second directory the "open in IDE" action treats as a safe sandbox alongside `workspace_path`. Useful if you keep extra git worktrees outside the main workspace tree.
- `port` — TCP port for the embedded HTTP server. `0` (default) lets the OS pick a free port. Set a fixed value if you want to reach the dashboard from your browser at `http://127.0.0.1:<port>`.
- `native` — `true` (default) opens a desktop window via pywebview. `false` skips the native window and lets you use any browser; useful if you don't have GTK/Qt Python bindings installed.
- `[repositories]` — `primary` and `secondary` are bare directory names (not paths) matched against what is found under `workspace_path`. Anything left over lands in an "Others" card. Both lists are ignored when `workspace_path` is unset.
- `[open_with.<slot>]` — three vendor-neutral launcher slots (`main_ide`, `secondary_ide`, `terminal`) wired to the per-repo action buttons. Each slot has a `label` (tooltip text) and a `commands` fallback chain. Each command is a single shell-style string parsed with `shlex`; the literal `{path}` is replaced with the absolute path of the repo being opened. Commands are tried in order until one starts. Built-in defaults reproduce the previous behaviour, so you only need to override the slots you actually want to customise.

Once `conception_path` is set, run `condash` to launch the dashboard.

### Editing the config from inside the app

Click the gear icon in the dashboard header (next to the light/dark toggle). A modal opens with form fields for every option above; saving writes the file atomically (preserving comments via `tomlkit`) and reloads the dashboard. Path / repository / open-with changes apply on reload; changes to `port` or `native` need a `condash` restart and the modal will tell you so.

## CLI

```
condash                         # open the dashboard window
condash --version               # print version and exit
condash --conception-path PATH  # one-shot override (does not touch config file)
condash --config PATH           # use a different config file

condash init                    # write a default config template
condash config show             # print the effective configuration
condash config edit             # open the config in $EDITOR
condash tidy                    # move done items into YYYY-MM/ archive dirs

condash install-desktop         # register condash with the XDG launcher (Linux)
condash uninstall-desktop       # remove the user-local desktop entry (Linux)
```

## Linux: register condash in your application launcher

`condash install-desktop` writes a user-local XDG desktop entry plus the bundled SVG icon, so condash appears in GNOME Activities, KDE Kickoff, Cinnamon menu, and other launchers that read `~/.local/share/applications`:

```bash
condash install-desktop
```

This installs:

- `~/.local/share/applications/condash.desktop` — the launcher entry, pointing at the absolute path of whichever `condash` binary you ran the command with (so it survives pipx / venv isolation)
- `~/.local/share/icons/hicolor/scalable/apps/condash.svg` — the SVG app icon

No `sudo` and no system-wide changes. To remove it later: `condash uninstall-desktop`.

The native window also picks up the same icon at runtime via pywebview, so it appears in your taskbar / Alt-Tab switcher.

## Claude Code skill

A minimal example [`SKILL.md`](SKILL.md) ships at the repo root — drop it into `~/.claude/skills/condash/` (or `<project>/.claude/skills/condash/`) to drive the non-interactive CLI surface from a Claude Code session: `condash init`, `condash config show / edit`, `condash tidy`, and `condash install-desktop`. Launching the native window from inside an agent is deliberately out of scope — run `condash` by hand for that.

## Status

Version 0.2.0 — adds an in-app config editor (gear icon next to the theme toggle) and three vendor-neutral `[open_with]` launcher slots that replace the previous hardcoded IntelliJ / VS Code / terminal buttons. Also fixes the v0.1.5 desktop-launcher crash where the window icon was forwarded via the wrong pywebview kwarg dict. Still Linux-first overall; macOS and Windows should work but are less tested.

## License

MIT — see [LICENSE](LICENSE).
