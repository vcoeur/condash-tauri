---
name: conception-items
description: Create, list, update, and close projects / incidents / documents in a condash-style conception tree by editing Markdown files directly. Use when the user wants to add a new item, change an item's status, flip a step's checkbox, append a timeline entry, or close an item. Does NOT run `condash tidy` — archiving is the user's call.
argument-hint: "<natural language request, e.g. 'create a project called ship dark mode' or 'close the billing incident'>"
allowed-tools: Read, Write, Edit, Grep, Glob, Bash(date:*), Bash(ls:*)
---

Minimal file-only skill for managing a [condash](https://condash.vcoeur.com/) conception tree. Every operation is a plain read or write under `$CONCEPTION_PATH`. No API, no CLI — the skill edits Markdown files and `condash` picks up the changes on the next page load.

**This is a minimal example skill.** It is deliberately small. Fork it and add your own rules (custom templates, branch isolation, notes indexing, deliverable scaffolding) as needed.

## Use at your own risk

MIT-licensed, provided as-is with no warranty. This skill writes and edits files under your conception tree. Keep the tree under version control so every mutation is reviewable in `git diff`, and review the diff after every session.

## Where is the tree?

The skill locates the tree from the `CONCEPTION_PATH` environment variable:

```bash
export CONCEPTION_PATH=~/conception
```

If `CONCEPTION_PATH` is unset, ask the user for the path before doing anything else. Do not guess, and do not default to the current working directory.

## Request

> $ARGUMENTS

## Supported operations

Parse the request into one of these four operations and execute only that one. If the request is ambiguous (for example, "update the billing thing"), ask the user which operation they meant before touching any file.

### 1. Create a new item

Required inputs from the request:

- **Type** — `project`, `incident`, or `document`. If the user does not say, ask.
- **Title** — a short human-readable name. Derive the slug from it: lowercase, spaces → dashes, strip non-alphanumerics except dashes.
- **Apps** — backtick-delimited list. Ask if missing.
- **Status** — default to `now` for project/incident, `review` for document, unless the user says otherwise.

Optional inputs:

- **Goal** — one-sentence goal for projects; symptom for incidents; objective for documents.
- **Steps** — a bulleted list; render each as `- [ ] <text>`.

Write to `$CONCEPTION_PATH/<type>s/YYYY-MM-DD-<slug>/README.md` where `YYYY-MM-DD` is today. Use the following template (adapted per type):

```markdown
# <Title>

**Date**: YYYY-MM-DD
**Status**: <status>
**Apps**: `<app1>`, `<app2>`

## <Goal|Symptom|Objective>

<One-sentence description from the request.>

## Steps

- [ ] <first step>
- [ ] <second step>

## Timeline

- YYYY-MM-DD — <Type> created

## Notes

_None yet._
```

Report back the created path and the chosen slug. Do not run `condash tidy` or launch the dashboard.

### 2. List items

Scan `$CONCEPTION_PATH/{projects,incidents,documents}/**/README.md` with `Grep` for `**Status**:` lines and extract the metadata. Apply filters from the request:

- **By type** — "list projects" / "list incidents" / "list documents" / "list everything".
- **By status** — "list active" (anything != done) / "list done" / "list now" / etc.
- **By app** — "list anything for vcoeur.com".
- **By keyword** — match against titles.

Print a compact summary grouped by status:

```
now:
  2026-04-15-add-dark-mode-toggle (vcoeur.com)
  2026-04-10-billing-export (vcoeur.com)
soon:
  2026-04-12-audit-session-cookies (notes.vcoeur.com)
```

One line per item. No bodies, no step counts — just enough for the user to pick one and ask a follow-up.

### 3. Update an item

Resolve the target item by slug, title, or "the X project" / "the Y incident". If more than one match, list them and ask the user which one. Common update operations:

| Request | Mutation |
|---|---|
| "mark '<step text>' as in progress" | `- [ ] <text>` → `- [~] <text>` |
| "mark '<step text>' done" | `- [ ] <text>` or `- [~] <text>` → `- [x] <text>` |
| "add a step '<text>'" | Append `- [ ] <text>` to `## Steps` |
| "add a timeline entry '<text>'" | Append `- YYYY-MM-DD — <text>` to `## Timeline` |
| "change status to <status>" | Rewrite the `**Status**: <old>` line |
| "append a note '<text>'" | Append a paragraph to the `## Notes` section (creating it if absent) |

Use `Edit` for the minimum possible rewrite — do not rewrite whole sections when a single-line change will do.

### 4. Close an item

1. Resolve the target item (same as update).
2. Rewrite `**Status**: <old>` → `**Status**: done`.
3. Append to `## Timeline`: `- YYYY-MM-DD — Closed`.
4. Report back: `Closed <path>. Run \`condash tidy\` to archive it into YYYY-MM/.`

**Do not** run `condash tidy` yourself. Archiving changes file paths and the user should trigger it from the dashboard footer or from a shell after reviewing the close.

## Slug rules

When deriving a slug from a title:

1. Lowercase.
2. Replace non-alphanumerics with `-`.
3. Collapse consecutive `-` into one.
4. Trim leading/trailing `-`.
5. Truncate to 50 characters, breaking at the last `-` before the limit.

Examples:

- "Add dark mode toggle" → `add-dark-mode-toggle`
- "Migrate auth to session-cookie hybrid" → `migrate-auth-to-session-cookie-hybrid`
- "Fix `POST /api/users/:id` 500 error" → `fix-post-api-users-id-500-error`

## What this skill does NOT do

- **Run `condash tidy`.** Archiving is a filesystem rename with non-trivial blast radius; leave it to the user.
- **Launch the dashboard.** `condash` without a subcommand opens an interactive desktop window that is not useful under an agent.
- **Create notes files.** Individual `notes/<name>.md` files are the user's business. When you add an entry to `## Notes`, just reference the path; do not create the file unless asked.
- **Follow branch isolation.** If an item has a `**Branch**` field, the code for that item lives under a git worktree. This skill does not inspect or mutate anything under that worktree. If the user asks for a code change, remind them about the branch.
- **Parse `## Deliverables`.** Deliverables are produced by separate generation skills; this one stops at item lifecycle.

## Adapting the skill

Things you might want to add when you fork this:

- **Custom templates per app or per team.** Replace the body builder with a lookup by `Apps` field.
- **Automatic stubs.** When creating an incident for a specific environment, seed extra sections (`## Impact`, `## Workaround`).
- **Notes indexing.** A verb that creates `notes/<slug>.md` and adds it to the `## Notes` section of the parent README.
- **Branch + worktree setup.** A verb that, on project creation with a `Branch` field, runs `git worktree add` under a known worktrees directory.
- **Cross-repo refs.** Validate that every app mentioned in `**Apps**:` corresponds to a real directory under `workspace_path`.

Each of these is a ten-minute extension on top of the base skill. Fork it and keep going.

## Installation

Drop this `SKILL.md` into one of:

- `~/.claude/skills/conception-items/SKILL.md` — available in every Claude Code session.
- `<your-project>/.claude/skills/conception-items/SKILL.md` — project-local.

See [Claude Code's skill documentation](https://docs.claude.com/en/docs/claude-code/skills) for details.

Set `CONCEPTION_PATH` in your shell rc file so the skill always knows which tree to manage.

$ARGUMENTS
