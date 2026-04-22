---
title: Configure the conception path · condash guide
description: Point condash at the directory it should render — persistently, for one run, or from the gear modal.
---

# Configure the conception path

**When to read this.** You want condash to render a tree other than the one it's using now, or you want to know all the ways that path can be set.

The conception path is the only piece of configuration condash needs before it can start. Everything else has a sensible default.

## Option 1 — from the gear modal

Click the gear icon in the dashboard header. The **General** tab shows the current conception path in an editable field:

![Gear modal — General tab](../assets/screenshots/gear-modal-light.png#only-light)
![Gear modal — General tab](../assets/screenshots/gear-modal-dark.png#only-dark)

Typing a new path and clicking **Save** reloads the dashboard against the new tree. No restart needed.

This is the right setup for your main tree — the path you work in every day.

## Option 2 — via `CONDASH_CONCEPTION_PATH`

condash reads the path from the `CONDASH_CONCEPTION_PATH` environment variable. For a one-shot run against a scratch tree:

```bash
CONDASH_CONCEPTION_PATH=/tmp/experimental-tree condash
```

To make it persistent, export it from your shell's rc file:

```bash
# ~/.bashrc, ~/.zshrc, etc.
export CONDASH_CONCEPTION_PATH="$HOME/src/vcoeur/conception"
```

Useful for:

- Trying a fresh tree layout without disturbing your working config.
- Running two condash instances side-by-side (pin each with a different `CONDASH_PORT` on `condash-serve`) to compare trees.
- Scripts and demos where you want an explicit path in the recipe.

!!! note "Default path"
    If `CONDASH_CONCEPTION_PATH` is unset, condash falls back to `$HOME/src/vcoeur/conception`. Works out of the box if you keep your tree at that location; otherwise, set the variable.

## When to use a scratch tree

A scratch tree is any directory with a minimal `projects/YYYY-MM/` layout that you point condash at temporarily. Common reasons:

- **Learning** — the bundled `conception-demo` tree, fetched in [First run](../tutorials/first-run.md).
- **Onboarding a teammate** — fork a small sample tree, have them point condash at it, walk them through creating their first item, then point them at the team tree.
- **Snapshot of a bug** — reduce a broken tree to a minimal reproducer, commit it, and file the issue with a `CONDASH_CONCEPTION_PATH=...` command in the repro steps.

The cheapest way to make one:

```bash
mkdir -p /tmp/scratch-tree/projects/2026-04
CONDASH_CONCEPTION_PATH=/tmp/scratch-tree condash
```

The Projects tab will be empty but the dashboard will render. Add README files under `projects/2026-04/` and refresh.

## Multiple machines pointed at the same tree

If you sync the conception tree between machines via git, each machine needs its own `CONDASH_CONCEPTION_PATH` — the absolute path typically differs (different users, different mount points).

The tree itself carries the team-shared config (`config/repositories.yml`) and each machine's local tweaks (`config/preferences.yml`). See [Multi-machine setup](multi-machine.md) for the full split.
