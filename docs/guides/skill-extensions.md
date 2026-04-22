---
title: Extend the management skill · condash guide
description: Three realistic extension patterns for the shipped `/conception-items` skill — branch isolation on create, deliverable generation on close, notes indexing on add-note.
---

# Extend the management skill

**When to read this.** You installed the shipped `/conception-items` skill, used it for a week, and hit "I wish this also did X". This page shows three concrete patterns that cover the 90% of what teams actually add on top.

The shipped skill is minimal on purpose. Every extension here is a ten-minute change to a single `SKILL.md` file — there's no plugin API, no hook registration; you're editing a Markdown prompt file and relying on Claude Code to read your updated instructions.

For the full skill reference — every action, every argument, every prompt variable — see [the management skill reference](../reference/skill.md).

## Where the skill lives

```bash
# Globally available
~/.claude/skills/conception-items/SKILL.md

# Or project-local, auto-loaded only inside a specific repo
<your-project>/.claude/skills/conception-items/SKILL.md
```

Extensions are edits to whichever copy you want to modify. Keep the global copy baseline-minimal and put team-specific extensions in the project-local copy — that way fork per tree, not per machine.

## Pattern 1 — Branch isolation on create

**Problem.** Your projects-that-touch-code need to work in a git worktree, not the main checkout, so concurrent items don't step on each other. The shipped skill creates the README and stops; you want it to also scaffold the worktree.

**Extension.** Add a `Branch` header field to the template, and a post-create hook that sets up the worktree:

```markdown
## Extended create action

After writing the new README, if `Apps` mentions a known code app (`helio`,
`helio-web`, `helio-docs`), append a `**Branch**:` header field with a
proposed branch name (`feature/<item-slug>`).

Then, if the user confirms, run:

    cd ~/src/<app>
    git fetch origin
    git worktree add ~/src/worktrees/<branch> -b <branch> origin/main

And report the worktree path so the user knows where to cd into.

Never run this without explicit confirmation — worktree creation has side
effects outside the conception tree.
```

Key points:

- Keep the worktree creation gated behind confirmation. The skill can write files freely; it should not run git commands silently.
- Put the app-list mapping in a small table at the top of `SKILL.md` so it's editable without hunting through prose.
- Leave the shipped create behaviour as the fallback when `Apps` doesn't match any known app.

## Pattern 2 — Deliverable generation on close

**Problem.** When a `document` kind item closes, you want its deliverable PDF regenerated from the latest notes without anyone remembering to run the pandoc command.

**Extension.** Extend the `close` action:

```markdown
## Extended close action

Before setting **Status**: done, if the item has **Kind**: document:

1. Look for `notes/<primary>.md` (the README points at it via a wikilink
   in the Deliverables section, or it's whichever note has the longest body).
2. Regenerate the PDF:

       bash ~/.claude/scripts/md_to_pdf.sh notes/<primary>.md deliverables/<item-slug>.pdf

3. Verify the file exists and is non-empty.
4. Update the timeline with "- <date> — Regenerated deliverable on close."

Then set **Status**: done as usual.

If the regeneration fails, report the error and stop — do not mark the
item as done with a stale PDF.
```

Key points:

- Fail loudly. A stale deliverable in a `done` item is worse than an item stuck in `review` — the former looks authoritative, the latter is obviously in progress.
- Only do this for `document` kind items. `project` and `incident` items rarely have a single canonical deliverable, so the heuristic would pick the wrong file.
- See [Deliverables and PDFs](deliverables.md) for the filename convention this assumes.

## Pattern 3 — Notes index on add-note

**Problem.** Items accumulate notes. Without an index, the only way to discover what's in the notes folder is the Files panel in the expanded card. You want the README to maintain a `## Notes` section with one line per note, auto-updated.

**Extension.** Add or extend the `add-note` action:

```markdown
## Extended add-note action

After creating `<item>/notes/<name>.md`:

1. Open the item's README.
2. Locate the `## Notes` section. If absent, append one at the end of the
   file (before ## Timeline if it exists, otherwise at end).
3. Append a bullet:
       - [<name>.md](notes/<name>.md) — <first paragraph of the note, trimmed to 80 chars>
4. If the note already has a bullet, update its description instead of
   appending a duplicate.

Keep bullets in alphabetical order by filename.
```

Key points:

- Use the first paragraph of the note as the description, not the filename — the filename is already visible as the link text.
- Order matters: alphabetical keeps diffs small when notes are added out of sequence.
- Don't touch `## Notes` bullets written by hand for other files. Only touch the bullet for the file you just created.

## Why not ship these by default?

Every extension on this page assumes something about the team's workflow:

- Pattern 1 assumes a `~/src/worktrees/` convention and a specific list of apps.
- Pattern 2 assumes `md_to_pdf.sh` is available and that `document` items have a single canonical note.
- Pattern 3 assumes the README has a `## Notes` section and that notes have a first-paragraph summary.

None of these are universal. The shipped skill stays at the intersection of what every conception tree needs (create / list / update / close); team-specific conventions are one fork away.

## Adapting without forking

If you'd rather not maintain a forked `SKILL.md`, an alternative is to write a separate `/my-team-items` skill that wraps `/conception-items` — runs your extra logic, then delegates to the shipped skill for the base actions. This keeps upstream updates painless at the cost of one extra indirection layer.

Either approach works. Pick the one that fits your update cadence.

## Reference

- [Management skill reference](../reference/skill.md) — exhaustive list of actions, arguments, and prompt variables.
- [Your first project](../tutorials/first-project.md) — the skill in use from a tutorial perspective.
