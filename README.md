# condash

**Standalone desktop dashboard for markdown-based conception projects, incidents, and documents.**

`condash` is a single-user native-feeling application that renders a live dashboard of a directory tree of projects, incidents, and documents written as Markdown — originally the `conception` repo convention (`projects/YYYY-MM-DD-slug/README.md`, `incidents/…`, `documents/…`). It lets you browse them, track `## Steps` checklists, toggle item status, reorder steps, open files in your IDE, and tidy done items into monthly archive folders — all from one window backed by the same Markdown files you edit by hand.

## Install

```bash
uv tool install condash        # preferred
# or
pipx install condash
```

### System prerequisite (Linux)

`condash` uses [pywebview](https://pywebview.flowrl.com/) to open a native window backed by the system's webview. On Ubuntu/Debian you need:

```bash
sudo apt install libwebkit2gtk-4.1-0   # or libwebkit2gtk-4.0-37 on older releases
```

`pip` cannot install this — it has to come from the distro package manager.

## First launch

```bash
condash
```

On first start, `condash` writes a default config to `~/.config/condash/config.toml` and asks (on stdin) for the path of your conception directory. Edit the file afterwards if you want to change the path or repositories list:

```toml
conception_path = "/home/alice/src/vcoeur/conception"

[repositories]
primary = ["vcoeur.com", "alicepeintures.com"]
secondary = ["conception", "ClaudeConfig"]
```

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
