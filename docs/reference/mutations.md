---
title: Mutation model · condash reference
description: The exhaustive list of every action the dashboard takes on your files — and everything it deliberately never touches.
---

# Mutation model

## At a glance

The dashboard's **write surface is small**. It touches three places only:

1. An item's `README.md` (step + status edits).
2. Files under an item's root, mostly the `notes/` subdirectory (create, rename, upload, overwrite).
3. The tree-level `<conception_path>/configuration.yml`.

It does **not** touch `.git/`, does not move or rename item directories, does not run shell commands other than the user-configured `open_with.*` / `pdf_viewer` / `terminal.launcher_command` chains.

Every mutation is exposed as a POST route defined in [`src-tauri/src/server.rs`](https://github.com/vcoeur/condash/blob/main/src-tauri/src/server.rs). If a route isn't listed here, condash doesn't write.

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

## Item creation

The header **New item** button opens a small modal asking only the fields needed to scaffold a schema-valid README. Everything else — Goal / Scope / Steps / body prose — stays in the user's editor.

| Action | HTTP | Trigger | Effect |
|---|---|---|---|
| Create item | `POST /api/items` | Header "+" button → modal | Writes `projects/<YYYY-MM>/<YYYY-MM-DD>-<slug>/README.md` + empty `notes/` with a minimal seeded body per-kind; `touch projects/.index-dirty`. |

Body (`application/json`):

```json
{
  "title": "Login 500s under concurrent load",
  "slug": "login-500s",
  "kind": "incident",
  "status": "now",
  "apps": "vcoeur.com",
  "environment": "PROD",
  "severity": "high",
  "languages": ""
}
```

Server-side rules (re-validated in [`condash-mutations::create_item`](https://github.com/vcoeur/condash/blob/main/crates/condash-mutations/src/lib.rs) — client input is never trusted):

- `title` required.
- `kind` ∈ `{project, incident, document}`.
- `status` ∈ the canonical enum `{now, soon, later, backlog, review, done}`.
- `slug` matches `^[a-z0-9]+(?:-[a-z0-9]+)*$`. Uppercase, spaces, underscores, double hyphens, leading/trailing hyphens → 400.
- `environment` (incidents only) ∈ `{PROD, STAGING, DEV}`; `severity` ∈ `{low, medium, high}`.
- `languages` (documents only) is free-text — saved verbatim as `**Languages**:`.
- Collision on `projects/<YYYY-MM>/<YYYY-MM-DD>-<slug>/` → **409** with `{ok: false, reason: "item with this slug already exists today"}`.

Dates are always **today** on the server. Changing the date means renaming the folder — out of scope for the dashboard.

## Notes and attachments

All paths live under an item's directory (`projects/YYYY-MM/YYYY-MM-DD-slug/...`). The `notes/` subdirectory is the conventional home, but `create_note` and `store_uploads` accept any subpath relative to the item root.

| Action | HTTP | Trigger | Effect |
|---|---|---|---|
| Read a note | `GET /note` | Click a file in the card | Renders Markdown/text/PDF/image — no write |
| Read raw | `GET /note-raw` | Enter edit mode | Returns plain bytes + mtime — no write |
| Overwrite a note | `POST /note` | Save in the note editor | Atomic rewrite via a `.tmp` + rename. mtime check refuses stale overwrites. |
| Rename a note | `POST /note/rename` | Edit the filename field | Atomic rename preserving the extension. Rejects collisions. |
| Create a note | `POST /note/create` | "New note" action | Writes an empty file under `<item>/[subdir]/<filename>` |
| Create subdir | `POST /note/mkdir` | "New folder" action | Recursive mkdir under the item root. 409 if the target exists. |
| Upload files | `POST /note/upload` | Drag-and-drop or picker | Streams each file to disk (50 MB cap per file). Auto-suffixes `(2)`, `(3)`… on name collisions. |

Filename validation regexes are narrow on purpose:

- Notes: `[\w.-]+` plus a single extension. No spaces, no parentheses.
- Uploads: `[\w. \-()]+\.[A-Za-z0-9]+` — permissive enough for camera exports and scanned PDFs.

See [`crates/condash-mutations/src/lib.rs`](https://github.com/vcoeur/condash/blob/main/crates/condash-mutations/src/lib.rs) for the exact regexes.

## Config edits

The tree-level `<conception_path>/configuration.yml` can be written from the gear modal.

| Action | HTTP | Trigger | Effect |
|---|---|---|---|
| Save config | `POST /configuration` | Gear modal "Save" | Atomically replaces `configuration.yml` with the raw YAML from the textarea. Parse errors return 400 before anything lands on disk. |

`settings.yaml` is not written by any route — edit it by hand; condash reads it on the next launch.

Most changes reload live by rebuilding `RenderCtx`. Structural changes (`workspace_path`, `worktrees_path`, `repositories` list) need a restart — the save dialog surfaces which.

See [Config files](config.md) for the full key schema and which file owns which key.

## Open-with / external-launch commands

The `/open*` family launches an external process. These **do not** write to the conception tree — they spawn a command with `{path}` substituted in — but they're listed here because the sandbox rules matter.

| Action | HTTP | Accepted path | Command run |
|---|---|---|---|
| Open in IDE / terminal | `POST /open` | Must resolve under `workspace_path` **or** `worktrees_path` | One of the `open_with.<slot>.commands` chain, tried in order |
| Open a document | `POST /open-doc` | Must resolve under `conception_path` | OS default (`xdg-open` / `open` / `startfile`), or the `pdf_viewer` chain for `.pdf` files |
| Open a folder | `POST /open-folder` | Must match `projects/YYYY-MM/YYYY-MM-DD-slug/` | OS default file manager |
| Open a URL | `POST /open-external` | `http://` or `https://` only | User's default browser |

Paths outside the configured sandbox are rejected **before the shell sees them**. The validation lives in [`src-tauri/src/paths.rs`](https://github.com/vcoeur/condash/blob/main/src-tauri/src/paths.rs); the URL check in [`src-tauri/src/runners.rs`](https://github.com/vcoeur/condash/blob/main/src-tauri/src/runners.rs).

The one exception is the embedded terminal (`WS /ws/term`): its `?cwd=` query parameter goes through the same `_validate_open_path` check, so a forked shell can only start inside `workspace_path` or `worktrees_path`.

## What the dashboard never writes

| Never | Why |
|---|---|
| Anything under `.git/` | Out of scope. Use your editor / CLI. |
| Anything outside `conception_path` | Path validation rejects escapes. |
| Item directory renames / moves | The flat-month layout means items stay put for life; slug / date changes need `git mv` in the user's shell. |
| `knowledge/` tree | Read-only from the dashboard. Edit in your editor. |
| Caches or indices | There are none — the tree is re-parsed on every request. |
| Lock files | Concurrent edits are detected via mtime check on `POST /note`; there's no advisory lock. |

## Skill-invoked edits

The [`/conception-items`](skill.md) management skill invokes plain file operations from a Claude Code session — it does not call the dashboard's HTTP routes. Its mutations are therefore out of scope of this page; treat them as "edits made in your editor, from the outside". The parser re-reads on the next page load either way.

## Concurrency

Every write is atomic at the OS level (`.tmp` file + `replace`). Concurrency between the dashboard and an external editor is handled by the mtime check on `POST /note`: if the on-disk mtime doesn't match the client's snapshot, the write is refused with `{ok: false, reason: "file changed on disk"}` and the UI surfaces a conflict banner. No merge — the user re-opens the note and redoes their edit.

The step-edit routes rely on line-number targets, so the same principle applies: if the file has been restructured since the card loaded, the validation ("is this line still a checkbox?") fails and the request is rejected.
