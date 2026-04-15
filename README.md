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

By default, `condash` uses [pywebview](https://pywebview.flowrl.com/) to open a native window backed by the system's webview. On Ubuntu/Debian, that requires both the GTK webview library and Python's GTK bindings:

```bash
sudo apt install \
    libwebkit2gtk-4.1-0 \
    gir1.2-webkit2-4.1 \
    python3-gi \
    python3-gi-cairo
# on older releases: libwebkit2gtk-4.0-37 + gir1.2-webkit2-4.0
```

`pip` cannot install these — they have to come from the distro package manager. The Python `gi` module in particular is shipped as a system package and is **not** available on PyPI.

Because pipx creates an isolated venv that does not see system site-packages by default, install condash with the `--system-site-packages` flag so it can find `gi`:

```bash
pipx install --system-site-packages condash
```

If `gi` is missing or you'd rather skip the native window entirely, set `native = false` in your config (see [First launch](#first-launch)) — condash will then serve the dashboard in your usual browser instead.

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
workspace_path  = "/path/to/code/workspace"   # optional; enables the repo strip
worktrees_path  = "/path/to/git/worktrees"    # optional; "open in IDE" sandbox
port            = 0                           # 0 = OS picks a free port; set e.g. 3434 to pin one
native          = true                        # false = open in your browser instead of a desktop window

[repositories]
primary = ["repo-a", "repo-b"]
secondary = ["repo-c", "repo-d"]
```

`conception_path` is required. Everything else is optional:

- `workspace_path` — directory containing your code repositories. Every direct subdirectory that contains a `.git/` is shown in the dashboard's repo strip. If unset, the entire repo strip is hidden.
- `worktrees_path` — second directory the "open in IDE" action treats as a safe sandbox alongside `workspace_path`. Useful if you keep extra git worktrees outside the main workspace tree.
- `port` — TCP port for the embedded HTTP server. `0` (default) lets the OS pick a free port. Set a fixed value if you want to reach the dashboard from your browser at `http://127.0.0.1:<port>`.
- `native` — `true` (default) opens a desktop window via pywebview. `false` skips the native window and lets you use any browser; useful if you don't have GTK/Qt Python bindings installed.
- `[repositories]` — `primary` and `secondary` are bare directory names (not paths) matched against what is found under `workspace_path`. Anything left over lands in an "Others" card. Both lists are ignored when `workspace_path` is unset.

Once `conception_path` is set, run `condash` to launch the dashboard.

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
