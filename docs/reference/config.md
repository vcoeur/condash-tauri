---
title: Config files · condash reference
description: The two YAML files condash reads — one at the conception tree root, one in your XDG config — and every key in each.
---

# Config files

## At a glance

condash reads **two** YAML files. They split responsibilities by scope:

| File | Location | Scope | Owns |
|------|----------|-------|------|
| `configuration.yml` | `<conception_path>/configuration.yml` | Per-tree, versioned in git | `workspace_path`, `worktrees_path`, `repositories` (incl. `run:` / `force_stop:`) |
| `settings.yaml` | `${XDG_CONFIG_HOME:-~/.config}/condash/settings.yaml` | Per-user, per-machine | `conception_path`, `terminal`, `pdf_viewer`, `open_with` |

The tree-level file is versioned: commit it and every teammate who pulls picks up the same workspace layout and repo wiring. The per-user file lives on the machine condash runs on — it tells condash which tree to render, and carries the preferences that naturally differ per machine (which shell, which PDF viewer, which IDE command to shell out to).

### Precedence on overlap

For backwards compatibility, `configuration.yml` still accepts `terminal`, `pdf_viewer`, and `open_with` keys. When the same key appears in both files, **`settings.yaml` wins**, merged field by field:

- `terminal.<field>` — each field set in `settings.yaml` replaces the tree's value; missing fields fall through.
- `pdf_viewer` — a non-empty list in `settings.yaml` replaces the tree's; empty / missing falls through.
- `open_with.<slot>` — merged per slot. A user `commands` list replaces the tree's commands; a user `label` replaces the tree's label. A slot only set in the tree survives.

Concretely: move any machine-specific preference from `configuration.yml` into `settings.yaml` on each machine; leave tree-wide preferences in `configuration.yml` and every teammate gets them automatically.

## `configuration.yml` (per-tree, versioned)

Lives at `<conception_path>/configuration.yml`. Commit it. Every key is optional — a minimal valid file is an empty document `{}`, in which case condash uses defaults everywhere.

```yaml
workspace_path: /home/you/src
worktrees_path: /home/you/src/worktrees

repositories:
  primary:
    - condash
    - name: helio
      submodules:
        - { name: apps/web, run: make dev }
        - { name: apps/api, run: make dev }
    - name: notes.vcoeur.com
      run: make dev
      force_stop: fuser -k 8200/tcp 5200/tcp
  secondary:
    - conception

open_with:
  main_ide:
    label: Open in main IDE
    commands:
      - idea {path}
      - idea.sh {path}
  secondary_ide:
    label: Open in secondary IDE
    commands:
      - code {path}
      - codium {path}
  terminal:
    label: Open terminal here
    commands:
      - ghostty --working-directory={path}
      - gnome-terminal --working-directory {path}

pdf_viewer:
  - xdg-open {path}
  - evince {path}

terminal:
  shell: /bin/zsh
  shortcut: Ctrl+T
  screenshot_dir: /home/you/Pictures/Screenshots
  screenshot_paste_shortcut: Ctrl+Shift+V
  launcher_command: claude
  move_tab_left_shortcut: Ctrl+Left
  move_tab_right_shortcut: Ctrl+Right
```

Paths may use `~` (expanded to `$HOME`) or absolute paths. The in-app gear modal is a plain-text YAML editor and writes the file verbatim on save, so your hand-edited comments round-trip.

### Workspace keys

| Key | Meaning |
|-----|---------|
| `workspace_path` | Directory condash scans for git repositories. Every direct subdirectory containing a `.git/` shows up in the **Code** tab. If unset, the tab is hidden. |
| `worktrees_path` | Additional sandbox for the "open in IDE" buttons. Paths outside `workspace_path` and `worktrees_path` are rejected before the shell sees them. |

### `repositories`

Two buckets, `primary` and `secondary`, each a list of repo entries. Entries may take one of four shapes:

```yaml
repositories:
  primary:
    - condash                               # bare name
    - { name: helio }                       # same thing, inline map
    - name: helio
      submodules: [apps/web, apps/api]      # expandable row with sub-rows
    - name: notes.vcoeur.com
      run: make dev                         # inline dev-server runner
      force_stop: fuser -k 8200/tcp         # nuclear-stop helper
```

| Shape | Effect |
|---|---|
| Bare name | Directory name (not a path) matched against the scan of `workspace_path`. |
| `{name: repo}` | Same as bare — the inline-map form coexists because a repo may want sibling keys. |
| `{name: repo, submodules: [sub/a, sub/b]}` | Renders the repo as an expandable row. Each listed submodule gets its own dirty count and "open with" buttons. Useful for monorepos where subtrees are edited independently. |
| `{name: repo, run: "<cmd>"}` | Wires an [inline dev-server runner](inline-runner.md) into that row. `run:` is independent of `submodules:` — a parent's `run:` is **not** inherited by its submodules; add `run:` per submodule if they each have their own dev server. |
| `{name: repo, run: "<cmd>", force_stop: "<cmd>"}` | Same as above plus a repo-level **force-stop** button. The button runs `force_stop` as a shell command, without going through condash's own process tracking — use it to free a port held by a server condash didn't start (stale process from a previous run, a server launched from another terminal, etc.). Typical values: `fuser -k 8300/tcp`, `pkill -f 'manage.py runserver'`, `lsof -ti :8300 \| xargs -r kill -9`. Same shell trust level as `run:` — you're running these commands on your own machine, so a malicious tree is a malicious shell. |

Anything under `workspace_path` not named in either bucket lands in a third `OTHERS` card.

### `open_with`

Three vendor-neutral launcher slots used by the "Open with …" buttons on every repo row and note file:

| Slot | Typical use |
|------|-------------|
| `main_ide` | Full IDE — IntelliJ IDEA, PyCharm, RustRover, WebStorm. |
| `secondary_ide` | Lighter editor — VS Code, VSCodium, Zed. |
| `terminal` | Spawn a terminal already `cd`-ed into the target. |

Each slot takes a `label` (tooltip text) and a `commands` list.

```yaml
open_with:
  main_ide:
    label: Open in main IDE
    commands:
      - idea {path}
      - idea.sh {path}
      - intellij-idea-ultimate {path}
```

Commands are tried in order until one starts successfully. `{path}` is substituted with the absolute path of the repo, worktree, or directory being opened. If no command in the chain is on `$PATH`, the button reports failure via a toast.

Built-in defaults reproduce common IntelliJ / VS Code / terminal behaviour, so a `configuration.yml` with no `open_with` section still gives functional buttons. Override only the slots you want to customise.

### `pdf_viewer`

Bare list of shell-style commands for opening PDFs from deliverable links. `{path}` is replaced with the absolute path of the PDF. Tried in order.

```yaml
pdf_viewer:
  - xdg-open {path}
  - evince {path}
```

Empty list or missing key → falls back to the OS default (`xdg-open` on Linux, `open` on macOS).

### `terminal`

Embedded-terminal preferences. All keys are optional; an empty string means "fall back to the built-in default".

| Key | Default | Meaning |
|-----|---------|---------|
| `shell` | `$SHELL` → `/bin/bash` | Absolute path to an interactive shell. |
| `shortcut` | `` Ctrl+` `` | Toggle the terminal pane. Modifiers: `Ctrl`, `Shift`, `Alt`, `Meta`. Key names follow the HTML `KeyboardEvent.key` convention. |
| `screenshot_dir` | `~/Pictures/Screenshots` on Linux, `~/Desktop` on macOS | Directory scanned for "most recent screenshot" by the paste shortcut. |
| `screenshot_paste_shortcut` | `Ctrl+Shift+V` | Inserts the absolute path of the newest image in `screenshot_dir` into the active terminal. No `Enter` — you confirm. |
| `launcher_command` | `claude` | Shell-style command spawned by the secondary `+` button in each terminal side. Empty hides the button. |
| `move_tab_left_shortcut` | `Ctrl+Left` | Move the active tab to the left pane. |
| `move_tab_right_shortcut` | `Ctrl+Right` | Move the active tab to the right pane. |

## `settings.yaml` (per-user, per-machine)

Lives at `${XDG_CONFIG_HOME:-~/.config}/condash/settings.yaml`. Not versioned. Every key is optional — a fresh install starts with the file empty (or absent) and fills it on first launch.

```yaml
conception_path: /home/you/src/vcoeur/conception

terminal:
  shell: /bin/zsh
  shortcut: Ctrl+T
  launcher_command: claude
  screenshot_dir: /home/you/Pictures/Screenshots

pdf_viewer:
  - xdg-open {path}
  - evince {path}

open_with:
  main_ide:
    label: Open in main IDE
    commands:
      - idea {path}
      - idea.sh {path}
  secondary_ide:
    commands:
      - code {path}
```

| Key | Meaning |
|-----|---------|
| `conception_path` | Absolute path to the conception tree condash should render. |
| `terminal.*` | Same keys as the tree-level `terminal` block above; any field set here overrides the tree value. Missing fields fall through. |
| `pdf_viewer` | Fallback chain for opening PDFs. Non-empty list here replaces the tree's chain; empty or missing falls through. |
| `open_with.<slot>.label`, `.commands` | Merged per slot. The user's `commands` replaces the tree's; the user's `label` replaces the tree's. Tree-only slots survive untouched. |

Resolution order for the conception path, checked in sequence:

1. The `CONDASH_CONCEPTION_PATH` environment variable (see [env reference](env.md)).
2. `conception_path` in this file.
3. A first-run GUI prompt (Tauri build only). The prompt writes the chosen path back into this file so the next launch picks it up automatically.
4. Hard error — condash refuses to start.

The file is created on demand: the first-run folder picker writes it; you can also create it by hand.

## Editing from the dashboard

Click the gear icon in the header. A modal opens with a plain-text YAML editor showing the contents of `configuration.yml` — the tree-level file. Save is atomic (temp file → rename), so a crash during save never corrupts the file. Most changes take effect immediately; a few (see below) need a restart and the save dialog tells you which.

Editing `settings.yaml` is hand-edit only today — no UI surface. Use your editor of choice; condash re-reads it on the next launch.

Saves preserve your comments because the modal writes the raw text you edited — it does not round-trip the file through a parser.

Changes that **do** need a restart:

- `workspace_path` or `worktrees_path` change — the filesystem scanner is built once at launch.
- `repositories` list change — the per-repo fingerprint graph is built once at launch.

Changes that reload live without a restart:

- Everything under `open_with`, `pdf_viewer`, `terminal`.
- `run:` / `force_stop:` on an existing repo entry.

## See also

- [Environment variables](env.md) — `CONDASH_CONCEPTION_PATH`, `CONDASH_ASSET_DIR`, `CONDASH_PORT`.
- [Inline dev-server runner](inline-runner.md) — the `run:` field in `configuration.yml`.
- [Terminal shortcuts](shortcuts.md) — what each `terminal.*` shortcut does in the UI.
