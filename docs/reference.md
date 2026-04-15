---
title: Reference · condash
description: CLI surface, config keys, install options, parser internals, and the mutation model. How condash turns a directory of Markdown READMEs into a live dashboard.
---

# Reference

This page is the long-form reference for `condash`. Read the [Overview](index.md), [Conception convention](conception-convention.md), and [Getting started](getting-started.md) pages first if you have not — this page assumes you already know the shape of the thing.

## Install

### From PyPI

```bash
pipx install condash
# or: uv tool install condash
```

Both install `condash` into its own isolated venv and put it on your `$PATH`. The dashboard will not launch until you create and fill in a config file — see [First launch](#first-launch).

### System prerequisites

None on Linux, macOS, or Windows. `condash` ships its native-window backend as a Python dependency: `pywebview[qt]` pulls `PyQt6` + `PyQt6-WebEngine` + `QtPy` from PyPI, and those wheels bundle Qt itself. A vanilla `pipx install condash` is therefore self-contained.

- **Linux** — `pywebview` prefers GTK if `python3-gi` is installed system-wide, otherwise falls back to the bundled Qt backend with no extra setup.
- **macOS** — `pywebview` uses the native Cocoa WebKit backend by default; Qt is available as a fallback.
- **Windows** — `pywebview` uses the native Edge WebView2 backend by default; Qt is available as a fallback.

Install size is around 100 MB because of the bundled Qt wheels. If you'd rather skip the native window entirely, set `native = false` in your config and `condash` will serve the dashboard in your usual browser at `http://127.0.0.1:<port>`.

### First launch

```bash
condash init             # writes ~/.config/condash/config.toml
condash config edit      # opens the template in $VISUAL / $EDITOR
```

The template is fully commented out. The only mandatory field is `conception_path`. Everything else is optional — see [Config keys](#config-keys) below.

### Development from a source checkout

```bash
git clone https://github.com/vcoeur/condash.git
cd condash
uv sync --all-extras
uv run condash --version
uv run condash           # launches the native window, reading ~/.config/condash/config.toml
```

## CLI

`condash` is primarily a desktop app: running `condash` with no arguments launches the native window. A handful of subcommands handle setup and maintenance.

### `condash` (launch the dashboard)

```bash
condash                               # open the dashboard window
condash --version                     # print version and exit
condash --conception-path PATH        # one-shot override (does not touch the config file)
condash --config PATH                 # use a different config file
```

`--conception-path` is a convenience for testing another tree without rewriting the config — for example while developing a workflow against a scratch directory. `--config` lets you keep multiple configs side by side (work vs personal, for instance).

### `condash init`

Writes a commented template to `~/.config/condash/config.toml`. Refuses to overwrite an existing file.

```bash
condash init
```

Only `conception_path` is strictly required before the dashboard will launch. See [Config keys](#config-keys).

### `condash config`

```bash
condash config show                   # print the effective configuration (file + defaults)
condash config edit                   # open the config file in $VISUAL / $EDITOR
```

`config show` prints the resolved values — useful for debugging "why is condash using that path" without hand-parsing the TOML.

### `condash tidy`

Sweeps `done` items into `YYYY-MM/` archive folders so the active directories (`projects/`, `incidents/`, `documents/`) only show in-progress work.

```bash
condash tidy
```

Same behaviour as the tidy button in the dashboard footer. See [`tidy` semantics](#tidy-semantics) below.

### Desktop entry (Linux)

```bash
condash install-desktop               # register with the XDG application launcher
condash uninstall-desktop             # remove the user-local entry
```

`install-desktop` writes:

- `~/.local/share/applications/condash.desktop` — the launcher entry, pointing at the absolute path of whichever `condash` binary you ran the command with (survives `pipx` / `venv` isolation)
- `~/.local/share/icons/hicolor/scalable/apps/condash.svg` — the SVG app icon

No `sudo`, no system-wide changes. Remove with `condash uninstall-desktop`.

The native window also picks up the same icon at runtime via `pywebview`, so it appears in your taskbar and Alt-Tab switcher.

## Config keys

The config file lives at `~/.config/condash/config.toml` by default (or `$XDG_CONFIG_HOME/condash/config.toml` if that is set). Structure:

```toml
conception_path = "/path/to/conception"
workspace_path  = "/path/to/code/workspace"   # optional — enables the repo strip
worktrees_path  = "/path/to/git/worktrees"    # optional — additional open-in-IDE sandbox
port            = 0                           # 0 = OS picks a free port
native          = true                        # false = serve in a browser instead

[repositories]
primary   = ["repo-a", "repo-b"]
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

| Key | Required | Meaning |
|---|---|---|
| `conception_path` | yes | Absolute path to the root of the tree `condash` should render. Must contain `projects/`, `incidents/`, or `documents/` subdirectories (at least one). |
| `workspace_path` | no | Directory containing code repositories. Every direct subdirectory that contains a `.git/` shows up in the dashboard's repo strip. If unset, the repo strip is hidden entirely. |
| `worktrees_path` | no | Additional sandbox directory the "open in IDE" action treats as safe, alongside `workspace_path`. Useful if you keep extra git worktrees outside the main workspace tree. |
| `port` | no | TCP port for the embedded HTTP server. `0` (default) lets the OS pick a free port. Set a fixed value if you want to reach the dashboard from your browser at `http://127.0.0.1:<port>`. |
| `native` | no | `true` (default) opens a desktop window via `pywebview`. `false` skips the native window and lets you use any browser. |
| `[repositories]` | no | `primary` and `secondary` are bare directory names (not paths) matched against what is found under `workspace_path`. Anything left over lands in an "Others" card. Ignored when `workspace_path` is unset. |
| `[open_with.<slot>]` | no | Three vendor-neutral launcher slots (`main_ide`, `secondary_ide`, `terminal`) wired to per-repo action buttons. Each slot has a `label` (tooltip text) and a `commands` fallback chain. |

### `[open_with]` command syntax

Each `commands` entry is a single shell-style string parsed with `shlex`. The literal `{path}` is replaced with the absolute path of the repo being opened. Commands are tried in order until one starts successfully — if `idea {path}` is not on `$PATH`, the button falls through to `idea.sh {path}` automatically.

Built-in defaults for the three slots reproduce what `condash` did before the slots existed (IntelliJ, VS Code, terminal), so a minimal config without any `[open_with.*]` section still gets functional buttons — you only need to override the slots you want to customise.

### Editing the config from inside the app

Click the gear icon in the dashboard header (next to the light/dark toggle). A modal opens with form fields for every option above; saving writes the file atomically via `tomlkit` (preserving your comments) and reloads the dashboard.

- Path / repository / open-with changes apply on reload.
- Changes to `port` or `native` require a `condash` restart — the modal will tell you so.

## Parser internals

`condash` re-parses the `conception_path` tree on every page load. There is no background indexing, no watcher, no cache. This is intentional: the files are the source of truth, and the cost of walking a few hundred READMEs on every request is negligible compared to the complexity of maintaining an in-memory index.

### Discovery

For each of `projects/`, `incidents/`, `documents/`:

1. Find every `*/README.md` at the top level (active items).
2. Find every `*/*/README.md` where the middle path segment matches `YYYY-MM/` (archived items).
3. Skip directories and files that do not match these patterns.

The parser does not follow symlinks, does not recurse into `notes/` folders, and does not look at any file other than the item's own `README.md`.

### Metadata extraction

For each `README.md`:

- The **title** is the first line if it matches `# <text>`, otherwise the directory name.
- Each line matching `**<Key>**: <value>` becomes a field. The keys it pays attention to are `Date`, `Status`, `Apps`, `Branch`, `Environment`, `Severity`, `Languages`. Unknown keys are ignored.
- `Status` is normalised to lowercase and matched against the set `{now, soon, later, backlog, review, done}`. Unknown values fall back to `backlog`.
- `Apps` is split on commas and unquoted; backticks are stripped.
- The `## Steps` section is scanned for lines matching `- [<marker>] <text>`, with markers `' '`, `'~'`, `'x'`, `'X'`, `'-'` mapping to `open`, `progress`, `done`, `done`, `abandoned` respectively.
- The `## Deliverables` section is scanned for lines matching the pattern `- [<label>](<path>.pdf)[ — <description>]`. Every match becomes a download link in the item card.

### Rendering

Items are grouped by type (projects / incidents / documents) and then by status. The status order is `now → soon → later → backlog → review → done`. Inside each status group, items are sorted by `Date` descending (newest first).

Step progress is shown as `<done>/<total>` in the item header; in-progress steps are also counted so you can see `2/5 done · 1 in progress` at a glance.

## Mutation model

The dashboard can mutate files in exactly these cases, all via FastAPI routes that write through `Edit`-style in-place rewrites:

| Action | Trigger | File mutation |
|---|---|---|
| Toggle a step | Click the checkbox | Rewrite the single `- [<marker>] <text>` line in place |
| Add a step | Click "+" in the `## Steps` section | Insert a new `- [ ] <text>` line |
| Remove a step | Click the trash icon on a step | Delete the `- [<marker>] <text>` line |
| Edit a step | Click the pencil icon on a step | Rewrite the step text |
| Change status | Drop an item into a different kanban column | Rewrite the `**Status**: <value>` line |
| Tidy | Click tidy in the footer, or `condash tidy` | `os.rename` the item directory into `YYYY-MM/` |
| Edit config | Click the gear icon and save | Atomic write to `config.toml` via `tomlkit` |

The dashboard never writes to `notes/`, never touches files outside the active item's `README.md`, and never follows links. The surface is deliberately small — anything the dashboard cannot do, your editor can do.

### Sandbox rules

The "open in IDE" / "open terminal here" buttons accept a path argument only if it is inside `workspace_path` or `worktrees_path`. This is the single defence against `condash` being tricked into launching a command with an attacker-controlled argument through a crafted URL parameter. Paths outside those roots are rejected before the shell sees them.

## `tidy` semantics

`condash tidy` (and the tidy button in the dashboard footer) performs the following walk over `conception_path`:

1. For each of `projects/`, `incidents/`, `documents/`:
    - Find every **top-level** item (directory containing a `README.md`) whose parsed status is `done`.
    - For each, determine the archive month. The rule is: the **latest date** found in the item's `## Timeline` section if one exists, otherwise the README file's mtime. Format the month as `YYYY-MM`.
    - `os.rename` the item directory into `<type>/YYYY-MM/<slug>/`, creating the `YYYY-MM/` parent if it does not exist.
2. For each item **inside** a `YYYY-MM/` archive whose parsed status is not `done`:
    - `os.rename` it back up to the top level (`<type>/<slug>/`).

The move is atomic per-item: either the whole directory moves or nothing does. Tidy is idempotent — running it on a clean tree is a no-op.

!!! warning "Always commit before running tidy"
    `tidy` changes file paths. Any absolute link pointing at an item's old path will break. Commit or stash your tree before running it, so you can review the diff and fix links if needed.

## Claude Code skill (the CLI skill)

A minimal [`SKILL.md`](https://github.com/vcoeur/condash/blob/main/SKILL.md) ships at the root of the repo. It exposes the non-interactive CLI surface (`init`, `config show`, `config edit`, `tidy`, `install-desktop`) to Claude Code so an agent session can diagnose and maintain a `condash` setup. It does **not** launch the native window — that is an interactive desktop process and is out of scope for agent skills.

For managing **conception items** themselves (creating projects, closing incidents, adding notes), see the separate [management skill](skill.md) — a different skill that edits the Markdown files directly and has nothing to do with the `condash` CLI.

## Versioning

`condash` follows semver. The parser format is stable — a README that parses today will parse on every future version. New fields can be added (they are ignored on older versions) but existing fields cannot change meaning without a major version bump.

## License

MIT — see [LICENSE](https://github.com/vcoeur/condash/blob/main/LICENSE).
