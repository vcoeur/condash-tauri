# condash

**Standalone desktop dashboard for markdown-based conception projects, incidents, and documents.**

`condash` is a single-user native-feeling application that renders a live dashboard of a directory tree of projects, incidents, and documents written as Markdown — originally the `conception` repo convention (`projects/YYYY-MM-DD-slug/README.md`, `incidents/…`, `documents/…`). It lets you browse them, track `## Steps` checklists, toggle item status, reorder steps, open files in your IDE, and tidy done items into monthly archive folders — all from one window backed by the same Markdown files you edit by hand.

## Install

```bash
pipx install condash
# or: uv tool install condash
```

Both install the CLI into its own isolated venv and put `condash` on your `$PATH`. The dashboard will not launch until you have created and filled in a config file — see [First launch](#first-launch).

### System prerequisite (Linux)

`condash` uses [pywebview](https://pywebview.flowrl.com/) to open a native window backed by the system's webview. On Ubuntu/Debian you need:

```bash
sudo apt install libwebkit2gtk-4.1-0   # or libwebkit2gtk-4.0-37 on older releases
```

`pip` cannot install this — it has to come from the distro package manager.

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

[repositories]
primary = ["repo-a", "repo-b"]
secondary = ["repo-c", "repo-d"]
```

`conception_path` is required. `[repositories]` is optional — repos are looked up as sibling directories of `conception_path`. Once `conception_path` is set, run `condash` to launch the dashboard.

## CLI

```
condash                         # open the dashboard window
condash --version               # print version and exit
condash --tidy                  # move done items into YYYY-MM/ archive dirs and exit
condash --conception-path PATH  # one-shot override (does not touch config file)
condash --config PATH           # use a different config file
```

## Status

Version 0.1.0 — first standalone release. Ports the existing `conception/tools/dashboard.py` into a standalone PyPI package with configurable paths. Linux-first; other platforms untested.

## License

MIT — see [LICENSE](LICENSE).
