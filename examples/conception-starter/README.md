# Starter conception tree

This is a minimum working `conception/` tree for [`condash`](https://condash.vcoeur.com/). Copy it to a working location (for example `~/conception/`), point `condash` at it, and you have a functioning dashboard with three example items.

```
~/conception/
├── README.md                              ← this file (optional — condash ignores it)
├── projects/
│   └── 2026-04-15-first-project/
│       └── README.md
├── incidents/
│   └── 2026-04-15-first-incident/
│       └── README.md
└── documents/
    └── 2026-04-15-first-document/
        └── README.md
```

Three item types — projects, incidents, documents — each with one seed item in a distinct status.

## Install and use

```bash
# 1. Copy this starter to where you want your real tree.
mkdir -p ~/conception
cp -r /path/to/condash/examples/conception-starter/* ~/conception/

# 2. Point condash at it.
condash init
condash config edit                  # set conception_path = "/home/<you>/conception"

# 3. Launch.
condash
```

The three example items appear in the dashboard in different kanban columns (`now`, `now`, `review`). Click any item to expand it; try toggling a step with a click.

## Next

- Edit the three example READMEs to match your real work, or delete them and replace with your own. Everything the dashboard knows is re-parsed from the files on every refresh.
- Read the [Conception convention](https://condash.vcoeur.com/conception-convention/) for the full README header, `## Steps`, `## Timeline`, and `## Deliverables` specification.
- Install the [management skill](https://condash.vcoeur.com/skill/) so Claude Code can create, update, and close items for you.
