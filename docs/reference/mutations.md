---
title: Mutation model · condash reference
description: The exhaustive list of every action the dashboard takes on your files — and everything it deliberately never touches.
---

# Mutation model

## At a glance

The dashboard's **write surface is small**. It touches three places only:

1. An item's `README.md` (step + status edits).
2. Files under an item's root, mostly the `notes/` subdirectory (create, rename, upload, overwrite).
3. The two configuration files — `~/.config/condash/config.toml` and the two YAML files inside the conception tree.

It does **not** touch `.git/`, does not move or rename item directories, does not run shell commands other than the user-configured `open_with.*` / `pdf_viewer` / `terminal.launcher_command` chains.

Every mutation is exposed as a POST route in `app.py`. If a route isn't listed here, condash doesn't write.

## README edits

All operate on the item's `README.md` in place. Paths are validated against the conception tree before any I/O — the `paths.py` helpers reject `..` traversal and symlinks that escape the root.

| Action | HTTP | Trigger | Effect on `README.md` |
|---|---|---|---|
| Toggle step | `POST /toggle` | Click a checkbox | Rewrites one `- [<marker>] <text>` line, cycling `[ ]`→`[x]`→`[~]`→`[-]`→`[ ]` |
| Add step | `POST /add-step` | Click "+" in a section | Inserts `- [ ] <text>` at the end of the `## Steps` section (or named `section`) |
| Edit step | `POST /edit-step` | Click the pencil on a step | Rewrites the `<text>` portion of the step line, preserving the marker |
| Remove step | `POST /remove-step` | Click the trash icon | Deletes the whole step line |
| Reorder steps | `POST /reorder-all` | Drag-drop reorder in the card | Rewrites affected step lines in their new order; non-step content is left untouched |
| Change status | `POST /set-priority` | Drag card between kanban columns | Rewrites the `**Status**: <value>` line. Inserts one if missing. |

The step-edit routes operate on single lines by line number; `reorder-all` takes a list of source line numbers and rewrites them into their sorted positions. All of them validate that every target line is a checkbox before touching the file — no-op if the file has drifted since the client loaded it.

## Notes and attachments

All paths live under an item's directory (`projects/YYYY-MM/YYYY-MM-DD-slug/...`). The `notes/` subdirectory is the conventional home, but `create_note` and `store_uploads` accept any subpath relative to the item root.

| Action | HTTP | Trigger | Effect |
|---|---|---|---|
| Read a note | `GET /note` | Click a file in the card | Renders Markdown/text/PDF/image — no write |
| Read raw | `GET /note-raw` | Enter edit mode | Returns plain bytes + mtime — no write |
| Overwrite a note | `POST /note` | Save in the note editor | Atomic rewrite via a `.tmp` + `replace`. mtime check refuses stale overwrites. |
| Rename a note | `POST /note/rename` | Edit the filename field | `Path.rename` preserving the extension. Rejects collisions. |
| Create a note | `POST /note/create` | "New note" action | Writes an empty file under `<item>/[subdir]/<filename>` |
| Create subdir | `POST /note/mkdir` | "New folder" action | `mkdir(parents=True)` under the item root. 409 if the target exists. |
| Upload files | `POST /note/upload` | Drag-and-drop or picker | Streams each file to disk (50 MB cap per file). Auto-suffixes `(2)`, `(3)`… on name collisions. |

Filename validation regexes are narrow on purpose:

- Notes: `[\w.-]+` plus a single extension. No spaces, no parentheses.
- Uploads: `[\w. \-()]+\.[A-Za-z0-9]+` — permissive enough for camera exports and scanned PDFs.

See [`mutations.py`](https://github.com/vcoeur/condash/blob/main/src/condash/mutations.py) for the exact regexes.

## Config edits

Two config files can be written from the gear modal. The TOML file is the per-machine store; the two YAML files live inside the conception tree.

| Action | HTTP | Trigger | Effect |
|---|---|---|---|
| Save config | `POST /config` | Gear modal "Save" | Writes `config.toml` via `tomlkit` (preserves comments) and the YAMLs via `PyYAML`. All writes are atomic (`.tmp` + `replace`). |

Changes to `port` and `native` require a restart — the response surfaces those as `restart_required: ["port", "native"]` so the dashboard can warn the user. Every other field reloads live by rebuilding `RenderCtx`.

See [Config files](config.md) for the full key schema and which file owns which key.

## Open-with / external-launch commands

The `/open*` family launches an external process. These **do not** write to the conception tree — they spawn a command with `{path}` substituted in — but they're listed here because the sandbox rules matter.

| Action | HTTP | Accepted path | Command run |
|---|---|---|---|
| Open in IDE / terminal | `POST /open` | Must resolve under `workspace_path` **or** `worktrees_path` | One of the `open_with.<slot>.commands` chain, tried in order |
| Open a document | `POST /open-doc` | Must resolve under `conception_path` | OS default (`xdg-open` / `open` / `startfile`), or the `pdf_viewer` chain for `.pdf` files |
| Open a folder | `POST /open-folder` | Must match `projects/YYYY-MM/YYYY-MM-DD-slug/` | OS default file manager |
| Open a URL | `POST /open-external` | `http://` or `https://` only | User's default browser |

Paths outside the configured sandbox are rejected **before the shell sees them**. The regexes live in [`paths.py`](https://github.com/vcoeur/condash/blob/main/src/condash/paths.py); the URL check in [`openers.py::_is_external_url`](https://github.com/vcoeur/condash/blob/main/src/condash/openers.py).

The one exception is the embedded terminal (`WS /ws/term`): its `?cwd=` query parameter goes through the same `_validate_open_path` check, so a forked shell can only start inside `workspace_path` or `worktrees_path`.

## What the dashboard never writes

| Never | Why |
|---|---|
| Anything under `.git/` | Out of scope. Use your editor / CLI. |
| Anything outside `conception_path` (except the TOML config) | Path validation rejects escapes. |
| Item directory renames / moves | The flat-month layout means items stay put for life. |
| New items (`projects/YYYY-MM/YYYY-MM-DD-slug/`) | Creation is an editor or `/conception-items` skill action — see [management skill](skill.md). |
| `knowledge/` tree | Read-only from the dashboard. Edit in your editor. |
| Caches or indices | There are none — the tree is re-parsed on every request. |
| Lock files | Concurrent edits are detected via mtime check on `POST /note`; there's no advisory lock. |

## Skill-invoked edits

The [`/conception-items`](skill.md) management skill invokes plain file operations from a Claude Code session — it does not call the dashboard's HTTP routes. Its mutations are therefore out of scope of this page; treat them as "edits made in your editor, from the outside". The parser re-reads on the next page load either way.

## Concurrency

Every write is atomic at the OS level (`.tmp` file + `replace`). Concurrency between the dashboard and an external editor is handled by the mtime check on `POST /note`: if the on-disk mtime doesn't match the client's snapshot, the write is refused with `{ok: false, reason: "file changed on disk"}` and the UI surfaces a conflict banner. No merge — the user re-opens the note and redoes their edit.

The step-edit routes rely on line-number targets, so the same principle applies: if the file has been restructured since the card loaded, the validation ("is this line still a checkbox?") fails and the request is rejected.
