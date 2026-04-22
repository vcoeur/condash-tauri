---
title: Why Markdown-first · condash
description: The case for a project tracker built on plain Markdown files in git, rather than a SaaS or a local database.
---

# Why Markdown-first

Every project tracker answers a few questions for you: what am I working on, what's its status, what did I decide and why, what's still open? There are plenty of good tools for this — Linear, GitHub Projects, Notion, Jira, Obsidian with a kanban plugin. `condash` exists because none of them give you all three of the following at the same time:

1. **The files are yours.** Editable in the editor you already use, diffable in git, grep-able from a shell, readable by every tool that has ever spoken Markdown.
2. **The dashboard is a view, not a second database.** Close the dashboard and the files don't go anywhere. Delete the dashboard and the files don't go anywhere.
3. **Writing is cheap.** No form to fill, no modal to open, no required fields, no schema migration. You type Markdown.

This page is the pitch. Read [tutorials/first-run](../tutorials/first-run.md) for how to actually install the thing.

## Your project tracker should be plain files in git

Project notes are some of the longest-lived artifacts you produce. They outlive sprints, redesigns, role changes, employer changes. A bug report from three years ago that cites a specific git commit is just as valuable now as it was when it was filed — if you can find it.

Locking them into a SaaS means:

- **You pay forever.** Not just money — a tax on every workflow that touches your notes. Want to grep for "session cookie" across every item you wrote in 2024? You're writing an API script.
- **You lose them when you stop paying.** Every "export" feature is worse than it sounds; structure gets lossy.
- **You cannot compose.** Your editor doesn't know about them. Your shell doesn't. `rg` doesn't. Your AI agent doesn't.

Plain Markdown in git is the opposite on every axis. It's portable, greppable, diffable, editor-agnostic, and free. The failure mode is "a folder on disk" — recoverable from any backup, readable by any human.

## Markdown for diffs, grep, and editors

A README under a project folder looks like this:

```markdown
# Migrate auth to session-cookie hybrid

**Date**: 2026-04-10
**Kind**: project
**Status**: now
**Apps**: `notes.vcoeur.com`, `vcoeur.com`
**Branch**: `feat/session-cookie-auth`

## Goal

Drop the JWT dependency without breaking existing sessions.

## Steps

- [x] Audit session-cookie usage
- [~] Implement hybrid read path
- [ ] Migration script for existing tokens
```

Every piece of it earns its keep:

- `# <title>` is the canonical human name. Markdown conventions; nothing special.
- `**Key**: value` headers are both visually weighted in a rendered preview and trivially parseable with a regex. No `~~~yaml` frontmatter fence — the header is part of the document.
- `## Steps` with standard GitHub-style checkboxes are editable in every Markdown tool on the planet, and the status markers (`[x]`, `[~]`, `[-]`) survive round-trips through anything that doesn't understand them — they're just characters inside a bullet.

And because it's a regular Markdown file:

- `git diff` shows you exactly what changed when you flipped a step or re-worded the goal.
- `rg 'session cookie'` finds it in 30 ms.
- Opening it in Obsidian, Typora, your editor of choice, or even `less` all give you something readable.

The dashboard is not the only way to view or edit this file. That's the whole point.

## The dashboard as a view layer

`condash` is a desktop app that reads the tree and renders a kanban, a history search, a PDF viewer, a repo strip, an embedded terminal. **It writes back for a handful of actions** (toggling steps, dragging cards between status columns, editing notes in-modal — see [mutation model](../reference/mutations.md)), but the write surface is deliberately small enough that you could reproduce any single action with `sed` if you wanted.

Concretely:

- No database. The tree is re-parsed on every request.
- No cache. Edit a README in your editor, refresh the window, see the change.
- No sync server. condash binds to `127.0.0.1`. If you want multi-machine, you `git pull`.
- No auth. Single-user, localhost-only.
- No signup. Download a release, launch `condash`.

What you gain from the view layer is what a view layer is for: visual grouping, quick edits, cross-linking, and the class of features that aren't worth writing by hand (a kanban drag-drop, a history search with snippets, an embedded PDF viewer).

What you give up: everything multi-user, everything web-hosted, everything that requires a backend. If that's what you need, `condash` is the wrong tool — use something else, happily.

## Three scenarios where this shape is the right one

The Markdown-first approach is not universal. It is very good at a few things.

### Solo developer juggling several apps

You maintain three applications. Every feature request, bug report, and "I should do that one day" note needs a home. You don't want a Jira project per app; you definitely don't want a SaaS bill. You have a `conception/` directory in git. Every item goes there.

The dashboard groups items by status across all apps. A per-app filter chip narrows to just the one you're thinking about. The repo strip at the top shows which repos are dirty. The embedded terminal lets you run a build in the same window. When you finish something, you flip the status to `done` — the item stays in its `YYYY-MM/` folder forever, searchable.

### Engineering logbook

Every non-trivial piece of work gets a dated README. Scope, decisions, links to the PR, a `## Timeline` with the things that happened.

Six months later, you need to remember why the auth system looks like that. `rg` finds the README in the `conception/` tree in under a second. The commit history on that README tells you when the decisions were made. The PR link tells you what actually shipped.

This is cheap writing. A SaaS with a rich editor and a separate comments section is not — by the time you've filled in all the fields, you've spent ten minutes on housekeeping and zero on thinking.

### Shared-with-AI-agent workspace

A Claude Code session can read, write, and edit Markdown files natively. No API, no webhook, no permissions model — the agent just edits files, you review in `git diff`, the dashboard picks up the change on the next poll.

The shipped [`/conception-items` skill](../reference/skill.md) does exactly this. You say "create a project called add dark mode, Kind project, Status soon, Apps notes.vcoeur.com" and the agent writes `projects/2026-04/2026-04-18-add-dark-mode/README.md` with the right template. No integration layer. No OAuth. Just file I/O.

For multi-project setups with branch isolation, deliverable generation, cross-item linking via [wikilinks](../guides/wikilinks.md), and a shared [knowledge tree](../guides/knowledge-tree.md), the agent-friendly nature compounds: every tool the agent knows (Read, Write, Edit, Grep) works on the same files that render in the dashboard.

### Post-mortem tracker

Incidents with `**Severity**`, `**Environment**`, and a dated `## Timeline` of what happened. Related investigations in the same item's `notes/`. A PDF deliverable generated from the same directory for the formal write-up. Links to the related project that fixed the root cause, resolved by `[[fix-connection-pool-exhaustion]]`.

A year later the whole thing is still a directory full of Markdown. Nothing was locked into an incident-management SaaS; nothing needs migrating when the company switches tools.

## What condash doesn't solve

Listing these keeps everyone honest:

- **Multi-user collaboration.** Two developers editing the same README at the same time will clash on merge. Git handles it like any other conflict. If you need real-time multi-user, use something else.
- **Web publishing.** The dashboard is a local desktop app. There's no "share a link with a stakeholder". Generate a PDF ([deliverables](../guides/deliverables.md)) or publish a static site from the tree.
- **Time tracking, invoicing, dependency graphs.** Scope creep. Build a sibling tool, or use a real project-management SaaS for that part.
- **Mobile.** Markdown in git works on mobile; `condash` itself is desktop-only.

## Summary

- Markdown files in git beat a SaaS for the class of work that outlives quarters.
- The dashboard is a view — edit the files however you want.
- The write surface is small, auditable, and reversible by `sed`.
- Three good-fit scenarios: solo dev across apps, engineering logbook, AI-agent workspace, post-mortem tracker.
- Not a fit when you need multi-user, web-hosted, or a proper project-management product.

If that sounds right, start with [First run](../tutorials/first-run.md).
