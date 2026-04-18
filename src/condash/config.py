"""Configuration loader for condash.

Config file lives at ``~/.config/condash/config.toml`` (or ``$XDG_CONFIG_HOME``
if set). Schema:

    conception_path = "/path/to/conception"
    workspace_path  = "/path/to/code/workspace"   # optional; enables repo strip
    worktrees_path  = "/path/to/git/worktrees"    # optional; "open in IDE" sandbox
    port            = 0                           # 0 = pick a free port in 11111-12111
    native          = true                        # false = serve in browser

    [repositories]
    primary = ["repo-a", "repo-b"]
    secondary = ["repo-c", "repo-d"]

Each entry under ``primary`` / ``secondary`` is either a bare directory name
or an inline table ``{name = "...", submodules = ["sub/one", "sub/two"]}``.
Submodule entries are plain subdirectories of the repo (not real git
submodules) and render as expandable sub-rows in the repo strip with their
own dirty counts and "open in IDE" buttons — useful for monorepos where
different subtrees are edited independently.

    [open_with.main_ide]
    label    = "Open in main IDE"
    commands = ["idea {path}", "idea.sh {path}"]

    [open_with.secondary_ide]
    label    = "Open in secondary IDE"
    commands = ["code {path}", "codium {path}"]

    [open_with.terminal]
    label    = "Open terminal here"
    commands = ["ghostty --working-directory={path}", "gnome-terminal --working-directory {path}"]

``workspace_path`` is the directory condash scans for git repositories to
display in the dashboard's repo strip. ``primary`` / ``secondary`` are bare
directory names (matched against what the scan finds), not paths. If
``workspace_path`` is unset, no scan happens and the repo strip is hidden
entirely — including the catch-all "Others" group.

``worktrees_path`` is a second directory the "open in IDE" action treats as
a safe sandbox in addition to ``workspace_path``. Useful if you keep your
git worktrees outside the main workspace tree. Optional.

``[open_with.*]`` defines the three vendor-neutral launcher slots wired to
the per-repo action buttons. Each slot has a ``label`` (tooltip text) and a
``commands`` fallback chain. Each command is a single shell-style string
parsed with ``shlex``; the literal ``{path}`` in any argument is replaced
with the absolute path of the repo / worktree being opened. Commands are
tried in order until one starts successfully.

First-run flow: if the file is missing, ``condash init`` (or
``condash config edit``) writes a commented template that the user must edit
before condash can launch the dashboard. The template is shipped as
``DEFAULT_CONFIG_TEMPLATE`` below — example values only, never real paths.
"""

from __future__ import annotations

import logging
import os
import shlex
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

REPOSITORIES_YAML_REL = "config/repositories.yml"
PREFERENCES_YAML_REL = "config/preferences.yml"

REPOSITORIES_YAML_HEADER = """\
# Versioned workspace config for this conception tree.
#
# Source of truth for what condash used to carry in `[repositories]` and
# `[open_with]`. Read by:
#   - condash (dashboard repo strip + "open with" buttons + workspace scan)
#   - /pr skill (to know which repos exist; the PR base branch is inferred
#     from `origin/HEAD` on the main checkout, not stored here)
#
# Paths may contain `~` (expanded to $HOME).
# Commands follow condash's `{path}` convention: the literal `{path}` is
# replaced with the absolute path of the repo or worktree being opened.
#
# condash rewrites this file when the Repositories tab of the Configuration
# modal is saved. Comments outside this header are discarded on that
# round-trip — hand-edit freely, but do not rely on inline comments being
# preserved.
#
# Repo entries accept:
#   - a bare directory name (e.g. "condash"), or
#   - "<org>/<repo>" for depth-2 workspace layouts (when workspace_path is
#     a parent of org folders rather than of repos directly), or
#   - a mapping `{name: ..., submodules: [...]}` to attach subrepository
#     rows rendered as expandable sub-rows in the repo strip.
"""

PREFERENCES_YAML_HEADER = """\
# Versioned user preferences for this conception tree.
#
# Picks up the TOML keys condash used to carry in the top-level scalar
# `pdf_viewer` list and the `[terminal]` table. Read by condash.
#
# Paths may contain `~` (expanded to $HOME).
# Commands follow condash's `{path}` convention where applicable.
#
# condash rewrites this file when the Preferences tab of the Configuration
# modal is saved. Comments outside this header are discarded on that
# round-trip.
"""

DEFAULT_CONFIG_TEMPLATE = """\
# condash configuration
#
# Uncomment and edit the values below before launching `condash`.

# conception_path: absolute path to the directory holding your conception items
# (must contain a `projects/` tree). Required.
# conception_path = "/path/to/conception"

# workspace_path: absolute path to a directory containing your code
# repositories. condash scans every direct subdirectory that contains a
# `.git/` and shows it in the dashboard's repo strip. Optional — if unset,
# the repo strip is hidden entirely.
# workspace_path = "/path/to/code/workspace"

# worktrees_path: absolute path to a directory holding extra git worktrees.
# The "open in IDE" action treats it as a safe sandbox alongside
# `workspace_path`. Useful if your worktrees live outside the main workspace
# tree (e.g. ~/src/worktrees/). Optional.
# worktrees_path = "/path/to/git/worktrees"

# port: TCP port the embedded HTTP server binds to. 0 (default) picks a
# free port in the range 11111-12111, chosen to avoid the 8000/8080 dev
# server cluster. Set a fixed port if you want to reach the dashboard
# from your browser at http://127.0.0.1:<port>.
# port = 0

# native: true (default) opens a native desktop window via pywebview.
# Set to false to serve the dashboard in your usual browser instead —
# useful if you don't have GTK/Qt Python bindings installed.
# native = true

# pdf_viewer: fallback chain of shell-style commands to open *.pdf files from
# note-body links and ## Deliverables. Each entry is a single string parsed
# with `shlex`; the literal `{path}` is replaced with the absolute path of
# the PDF. Commands are tried in order until one starts successfully. If
# unset or empty, PDFs fall back to the OS default (xdg-open / open /
# startfile) — same behaviour as images and other non-PDF files.
# pdf_viewer = ["evince {path}", "okular {path}"]

# [repositories]
# primary:   bare directory names (not paths) matched against what is found
#            under `workspace_path`; shown in the top card of the repo strip.
# secondary: same as primary, shown in the second card.
# Anything else found under `workspace_path` lands in an "Others" card.
# Both lists are ignored when `workspace_path` is unset.
#
# Each entry is either a bare string or an inline table
# `{name = "...", submodules = ["sub/one", "sub/two"]}`. Submodule entries
# are plain subdirectories of the repo (not real git submodules) that render
# as expandable sub-rows with their own dirty counts and action buttons —
# handy for monorepos.
# primary = ["repo-a", { name = "repo-b", submodules = ["apps/web", "apps/api"] }]
# secondary = ["repo-c", "repo-d"]

# [terminal]
# Settings for the embedded bottom-pane terminal.
#   - shell:    absolute path to an interactive shell. Unset → use $SHELL,
#               falling back to /bin/bash. Example: "/usr/bin/zsh"
#   - shortcut: single keyboard combo to toggle the pane. Defaults to
#               Ctrl+`. Supported modifiers: Ctrl, Shift, Alt, Meta.
#               Key names follow the HTML KeyboardEvent.key convention
#               (single chars like "T", "`", or names like "Enter",
#               "Escape"). Examples: "Ctrl+`", "Ctrl+Shift+T", "Alt+T".
#   - screenshot_dir: absolute path to the directory holding screenshots.
#                     Unset → $XDG_PICTURES_DIR/Screenshots, else
#                     ~/Pictures/Screenshots (Linux) or ~/Desktop (macOS).
#   - screenshot_paste_shortcut: keyboard combo that pastes the absolute
#                                path of the most recent image file in
#                                screenshot_dir into the active terminal
#                                tab (no Enter — user confirms). Same
#                                format as `shortcut`. Default Ctrl+Shift+V.
#   - launcher_command: shell-style command spawned by the secondary "+"
#                       button next to each side's new-tab button. Parsed
#                       with `shlex`; when the process exits, the tab
#                       closes. Empty string hides the launcher button.
#                       Default "claude".
#   - move_tab_left_shortcut / move_tab_right_shortcut: keyboard combos
#                       that move the active terminal tab to the left or
#                       right pane. Defaults Ctrl+Left / Ctrl+Right.
# shell                     = "/bin/zsh"
# shortcut                  = "Ctrl+`"
# screenshot_dir            = "/home/me/Pictures/Screenshots"
# screenshot_paste_shortcut = "Ctrl+Shift+V"
# launcher_command          = "claude"
# move_tab_left_shortcut    = "Ctrl+Left"
# move_tab_right_shortcut   = "Ctrl+Right"

# [open_with.<slot>]
# Three vendor-neutral launcher slots: `main_ide`, `secondary_ide`, `terminal`.
# Each slot defines:
#   - label:    tooltip text shown on hover
#   - commands: ordered list of shell-style command strings. The literal
#               `{path}` is replaced with the absolute path of the repo or
#               worktree being opened. Commands are tried in order until one
#               starts successfully.
# Built-in defaults reproduce the previous behaviour. Override only the
# slots you want to customise — each slot falls back to the defaults if the
# section is missing.
#
# [open_with.main_ide]
# label    = "Open in main IDE"
# commands = ["idea {path}", "idea.sh {path}"]
#
# [open_with.secondary_ide]
# label    = "Open in secondary IDE"
# commands = ["code {path}", "codium {path}"]
#
# [open_with.terminal]
# label    = "Open terminal here"
# commands = [
#     "ghostty --working-directory={path}",
#     "gnome-terminal --working-directory {path}",
#     "konsole --workdir {path}",
# ]
"""


OPEN_WITH_SLOT_KEYS: tuple[str, ...] = ("main_ide", "secondary_ide", "terminal")

DEFAULT_OPEN_WITH: dict[str, dict] = {
    "main_ide": {
        "label": "Open in main IDE",
        "commands": [
            "idea {path}",
            "idea.sh {path}",
            "intellij-idea-ultimate {path}",
            "intellij-idea-community {path}",
            "idea-ultimate {path}",
            "idea-community {path}",
        ],
    },
    "secondary_ide": {
        "label": "Open in secondary IDE",
        "commands": [
            "code {path}",
            "codium {path}",
        ],
    },
    "terminal": {
        "label": "Open terminal here",
        "commands": [
            "ghostty --working-directory={path}",
            "gnome-terminal --working-directory {path}",
            "konsole --workdir {path}",
            "xfce4-terminal --working-directory={path}",
            "x-terminal-emulator --working-directory {path}",
            "xterm -e bash -c 'cd \"{path}\" && exec bash'",
        ],
    },
}


@dataclass
class OpenWithSlot:
    """A single 'open with' button slot — vendor-neutral by design."""

    label: str
    commands: list[str] = field(default_factory=list)

    def resolve(self, path: str) -> list[list[str]]:
        """Return the command fallback chain with ``{path}`` substituted.

        Each command is shell-parsed via ``shlex`` so the user can write
        ``--working-directory={path}`` or ``--profile work {path}`` naturally.
        """
        out: list[list[str]] = []
        for raw in self.commands:
            if not raw.strip():
                continue
            try:
                argv = shlex.split(raw)
            except ValueError:
                continue
            argv = [arg.replace("{path}", path) for arg in argv]
            if argv:
                out.append(argv)
        return out


DEFAULT_TERMINAL_SHORTCUT = "Ctrl+`"
DEFAULT_SCREENSHOT_PASTE_SHORTCUT = "Ctrl+Shift+V"
DEFAULT_LAUNCHER_COMMAND = "claude"
DEFAULT_MOVE_TAB_LEFT_SHORTCUT = "Ctrl+Left"
DEFAULT_MOVE_TAB_RIGHT_SHORTCUT = "Ctrl+Right"
SCREENSHOT_IMAGE_EXTENSIONS: tuple[str, ...] = (".png", ".jpg", ".jpeg", ".webp")


def default_screenshot_dir() -> Path:
    """Best-guess default location for OS screenshots.

    Honours ``$XDG_PICTURES_DIR`` (a standard XDG user-dirs key) when set;
    otherwise falls back to ``~/Pictures/Screenshots`` on Linux and
    ``~/Desktop`` on macOS (Apple's default capture location).
    """
    xdg_pictures = os.environ.get("XDG_PICTURES_DIR")
    if xdg_pictures:
        return Path(xdg_pictures).expanduser() / "Screenshots"
    if os.uname().sysname == "Darwin":
        return Path.home() / "Desktop"
    return Path.home() / "Pictures" / "Screenshots"


@dataclass
class TerminalConfig:
    """Settings for the embedded bottom-pane terminal.

    ``shell`` is an absolute path to an interactive shell; empty / unset
    means "use ``$SHELL``, falling back to /bin/bash". ``shortcut`` is a
    single keyboard combo parsed by the frontend (see the README for the
    accepted format — `Ctrl+<key>`, `Ctrl+Shift+T`, etc.).

    ``screenshot_dir`` is an absolute path searched for the most recent
    image file when the screenshot-paste shortcut fires; ``None`` means
    use :func:`default_screenshot_dir`. ``screenshot_paste_shortcut`` is
    the keybinding that triggers that paste.
    """

    shell: str | None = None
    shortcut: str = DEFAULT_TERMINAL_SHORTCUT
    screenshot_dir: str | None = None
    screenshot_paste_shortcut: str = DEFAULT_SCREENSHOT_PASTE_SHORTCUT
    launcher_command: str = DEFAULT_LAUNCHER_COMMAND
    move_tab_left_shortcut: str = DEFAULT_MOVE_TAB_LEFT_SHORTCUT
    move_tab_right_shortcut: str = DEFAULT_MOVE_TAB_RIGHT_SHORTCUT

    def resolved_screenshot_dir(self) -> Path:
        """Return the effective screenshot directory (configured or default)."""
        if self.screenshot_dir:
            return Path(self.screenshot_dir).expanduser()
        return default_screenshot_dir()


@dataclass
class CondashConfig:
    """Runtime configuration for a condash session.

    Fields split by backing store:

    - **TOML** (``~/.config/condash/config.toml``): ``conception_path``,
      ``port``, ``native``, ``pdf_viewer``, ``terminal``. Per-machine runtime
      settings that don't belong in the shared conception tree.
    - **YAML** (``<conception_path>/config/repositories.yml``): ``workspace_path``,
      ``worktrees_path``, ``repositories_primary`` / ``_secondary`` (with
      submodules), ``open_with``. Versioned alongside the conception repo so
      every machine sees the same workspace layout.

    ``yaml_source`` records where the YAML-managed fields were loaded from
    on the current run: the YAML path when the file existed at load time,
    the TOML path when the values were migrated in from the legacy TOML
    sections, or ``None`` when conception_path is unset.
    """

    conception_path: Path | None = None
    workspace_path: Path | None = None
    worktrees_path: Path | None = None
    repositories_primary: list[str] = field(default_factory=list)
    repositories_secondary: list[str] = field(default_factory=list)
    repo_submodules: dict[str, list[str]] = field(default_factory=dict)
    terminal: TerminalConfig = field(default_factory=TerminalConfig)
    port: int = 0
    native: bool = True
    open_with: dict[str, OpenWithSlot] = field(default_factory=dict)
    pdf_viewer: list[str] = field(default_factory=list)
    yaml_source: Path | None = None
    preferences_source: Path | None = None


def config_path() -> Path:
    """Return the resolved path to the condash config file."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / "condash" / "config.toml"


def _render_repo_list(names: list[str], repo_submodules: dict[str, list[str]]) -> list:
    """Serialise a repo-name list back to TOML, emitting inline tables for repos that
    carry submodule paths and bare strings otherwise. Ordering of ``names`` is preserved.
    """
    import tomlkit

    out: list = []
    for name in names:
        subs = repo_submodules.get(name) or []
        if subs:
            entry = tomlkit.inline_table()
            entry["name"] = name
            entry["submodules"] = list(subs)
            out.append(entry)
        else:
            out.append(name)
    return out


def save(cfg: CondashConfig, path: Path | None = None) -> Path:
    """Atomically write ``cfg`` to ``path``, preserving comments where possible.

    If the target file already exists, its existing content is parsed with
    ``tomlkit`` and the typed values from ``cfg`` are merged into it in place.
    That way user comments, blank lines, and key ordering are retained around
    the edits made by the in-app editor or ``CondashConfig`` round-trips.

    If the target does not exist, a fresh document is built from scratch.

    **YAML split** — the YAML-managed fields (``workspace_path`` /
    ``worktrees_path`` / ``[repositories]`` / ``[open_with]``) are written
    to ``<conception_path>/config/repositories.yml`` via
    :func:`save_repositories_yaml` and stripped from the TOML document. When
    ``conception_path`` is unset the YAML cannot be written, so those keys
    stay in TOML as a degraded fallback until a conception path is set.
    """
    import tomlkit
    from tomlkit import comment, document, nl, table

    target = path or config_path()
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists():
        try:
            doc = tomlkit.parse(target.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, tomlkit.exceptions.TOMLKitError) as exc:
            log.warning("could not reparse %s (%s); rewriting from scratch", target, exc)
            doc = document()
    else:
        doc = document()
        doc.add(comment("condash configuration"))
        doc.add(nl())

    # Top-level scalars — the TOML carries only the three boot keys
    # (conception_path, port, native) when a conception_path is set.
    if cfg.conception_path is not None:
        doc["conception_path"] = str(cfg.conception_path)
    elif "conception_path" in doc:
        del doc["conception_path"]
    doc["port"] = int(cfg.port)
    doc["native"] = bool(cfg.native)

    # YAML-managed fields live under <conception_path>/config/. When a
    # conception_path is set, write the YAMLs and strip the matching keys
    # from the TOML so there's one source of truth on disk. Degraded mode
    # (no conception_path) keeps everything in TOML.
    yaml_target = save_repositories_yaml(cfg)
    prefs_target = save_preferences_yaml(cfg)

    if yaml_target is not None:
        for key in ("workspace_path", "worktrees_path", "repositories", "open_with"):
            if key in doc:
                del doc[key]
    else:
        if cfg.workspace_path is not None:
            doc["workspace_path"] = str(cfg.workspace_path)
        elif "workspace_path" in doc:
            del doc["workspace_path"]
        if cfg.worktrees_path is not None:
            doc["worktrees_path"] = str(cfg.worktrees_path)
        elif "worktrees_path" in doc:
            del doc["worktrees_path"]
        repos = doc.get("repositories")
        if not hasattr(repos, "value"):
            repos = table()
            doc["repositories"] = repos
        repos["primary"] = _render_repo_list(cfg.repositories_primary, cfg.repo_submodules)
        repos["secondary"] = _render_repo_list(cfg.repositories_secondary, cfg.repo_submodules)
        open_with_table = doc.get("open_with")
        if not hasattr(open_with_table, "value"):
            open_with_table = table()
            doc["open_with"] = open_with_table
        for slot_key in OPEN_WITH_SLOT_KEYS:
            slot = cfg.open_with.get(slot_key)
            if slot is None:
                continue
            slot_table = open_with_table.get(slot_key)
            if not hasattr(slot_table, "value"):
                slot_table = table()
                open_with_table[slot_key] = slot_table
            slot_table["label"] = slot.label
            slot_table["commands"] = list(slot.commands)

    if prefs_target is not None:
        for key in ("pdf_viewer", "terminal"):
            if key in doc:
                del doc[key]
    else:
        if cfg.pdf_viewer:
            doc["pdf_viewer"] = list(cfg.pdf_viewer)
        elif "pdf_viewer" in doc:
            del doc["pdf_viewer"]
        term_table = doc.get("terminal")
        if not hasattr(term_table, "value"):
            term_table = table()
            doc["terminal"] = term_table
        if cfg.terminal.shell:
            term_table["shell"] = cfg.terminal.shell
        elif "shell" in term_table:
            del term_table["shell"]
        term_table["shortcut"] = cfg.terminal.shortcut or DEFAULT_TERMINAL_SHORTCUT
        if cfg.terminal.screenshot_dir:
            term_table["screenshot_dir"] = cfg.terminal.screenshot_dir
        elif "screenshot_dir" in term_table:
            del term_table["screenshot_dir"]
        term_table["screenshot_paste_shortcut"] = (
            cfg.terminal.screenshot_paste_shortcut or DEFAULT_SCREENSHOT_PASTE_SHORTCUT
        )
        term_table["launcher_command"] = (
            cfg.terminal.launcher_command if cfg.terminal.launcher_command is not None else ""
        )
        term_table["move_tab_left_shortcut"] = (
            cfg.terminal.move_tab_left_shortcut or DEFAULT_MOVE_TAB_LEFT_SHORTCUT
        )
        term_table["move_tab_right_shortcut"] = (
            cfg.terminal.move_tab_right_shortcut or DEFAULT_MOVE_TAB_RIGHT_SHORTCUT
        )

    rendered = tomlkit.dumps(doc)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(rendered, encoding="utf-8")
    tmp.replace(target)
    return target


class ConfigNotFoundError(FileNotFoundError):
    """Raised when the config file does not exist on disk."""


class ConfigIncompleteError(ValueError):
    """Raised when the config file exists but is missing required values."""


def write_default_template(target: Path) -> None:
    """Write the commented default template to ``target``."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(DEFAULT_CONFIG_TEMPLATE, encoding="utf-8")
    tmp.replace(target)


def _parse_repo_list(raw: object, source: Path, key: str) -> tuple[list[str], dict[str, list[str]]]:
    """Split a ``primary`` / ``secondary`` list into (names, submodules map).

    Each entry is either a bare string (name only) or an inline table with
    ``{name = "...", submodules = [...]}`` — ``name`` is required,
    ``submodules`` optional. Name may be bare (``"condash"``, for a flat
    workspace) or slashed (``"myorg/repo-x"``, for a depth-2 workspace
    where ``workspace_path`` is a parent of org folders). Submodule paths
    are plain subdirectories relative to the repo root, not real git
    submodules.

    The PR base branch is **not** carried here — ``/pr`` resolves it from
    ``origin/HEAD`` on the main checkout at call time.
    """
    if raw is None:
        return [], {}
    if not isinstance(raw, list):
        raise ConfigIncompleteError(f"{source}: 'repositories.{key}' must be a list")
    names: list[str] = []
    subs: dict[str, list[str]] = {}
    for i, entry in enumerate(raw):
        if isinstance(entry, str):
            name = entry.strip()
            if not name:
                continue
            names.append(name)
        elif isinstance(entry, dict):
            name_raw = entry.get("name")
            if not isinstance(name_raw, str) or not name_raw.strip():
                raise ConfigIncompleteError(
                    f"{source}: 'repositories.{key}[{i}].name' must be a non-empty string"
                )
            name = name_raw.strip()
            sub_raw = entry.get("submodules") or []
            if not isinstance(sub_raw, list) or not all(isinstance(s, str) for s in sub_raw):
                raise ConfigIncompleteError(
                    f"{source}: 'repositories.{key}[{i}].submodules' must be a list of strings"
                )
            names.append(name)
            cleaned = [s.strip() for s in sub_raw if s.strip()]
            if cleaned:
                subs[name] = cleaned
        else:
            raise ConfigIncompleteError(
                f"{source}: 'repositories.{key}[{i}]' must be a string or a "
                f"table with 'name' and optional 'submodules'"
            )
    return names, subs


def _parse(data: dict, source: Path) -> CondashConfig:
    conception_raw = data.get("conception_path")
    conception_path: Path | None
    if conception_raw:
        conception_path = Path(str(conception_raw)).expanduser()
    else:
        # Treat missing/empty conception_path as "not yet configured" — the
        # dashboard launches anyway and prompts the user to set it via the
        # in-app config editor.
        conception_path = None

    workspace_raw = data.get("workspace_path")
    workspace_path: Path | None
    if workspace_raw:
        workspace_path = Path(str(workspace_raw)).expanduser()
    else:
        workspace_path = None

    worktrees_raw = data.get("worktrees_path")
    worktrees_path: Path | None
    if worktrees_raw:
        worktrees_path = Path(str(worktrees_raw)).expanduser()
    else:
        worktrees_path = None

    repos = data.get("repositories") or {}
    primary, primary_subs = _parse_repo_list(repos.get("primary"), source, "primary")
    secondary, secondary_subs = _parse_repo_list(repos.get("secondary"), source, "secondary")
    repo_submodules: dict[str, list[str]] = {**primary_subs, **secondary_subs}

    port_raw = data.get("port", 0)
    if not isinstance(port_raw, int) or not 0 <= port_raw <= 65535:
        raise ConfigIncompleteError(f"{source}: 'port' must be an integer between 0 and 65535")

    native_raw = data.get("native", True)
    if not isinstance(native_raw, bool):
        raise ConfigIncompleteError(f"{source}: 'native' must be a boolean")

    pdf_viewer_raw = data.get("pdf_viewer", [])
    if not isinstance(pdf_viewer_raw, list) or not all(isinstance(c, str) for c in pdf_viewer_raw):
        raise ConfigIncompleteError(f"{source}: 'pdf_viewer' must be a list of command strings")
    pdf_viewer = [c for c in (s.strip() for s in pdf_viewer_raw) if c]

    open_with_raw = data.get("open_with") or {}
    if not isinstance(open_with_raw, dict):
        raise ConfigIncompleteError(f"{source}: 'open_with' must be a table")
    open_with: dict[str, OpenWithSlot] = {}
    for slot_key in OPEN_WITH_SLOT_KEYS:
        defaults = DEFAULT_OPEN_WITH[slot_key]
        slot_data = open_with_raw.get(slot_key) or {}
        if not isinstance(slot_data, dict):
            raise ConfigIncompleteError(f"{source}: 'open_with.{slot_key}' must be a table")
        label = slot_data.get("label", defaults["label"])
        if not isinstance(label, str):
            raise ConfigIncompleteError(f"{source}: 'open_with.{slot_key}.label' must be a string")
        commands_raw = slot_data.get("commands", defaults["commands"])
        if not isinstance(commands_raw, list) or not all(isinstance(c, str) for c in commands_raw):
            raise ConfigIncompleteError(
                f"{source}: 'open_with.{slot_key}.commands' must be a list of strings"
            )
        open_with[slot_key] = OpenWithSlot(label=label, commands=list(commands_raw))

    terminal_raw = data.get("terminal") or {}
    if not isinstance(terminal_raw, dict):
        raise ConfigIncompleteError(f"{source}: 'terminal' must be a table")
    term_shell = terminal_raw.get("shell")
    if term_shell is not None and not isinstance(term_shell, str):
        raise ConfigIncompleteError(f"{source}: 'terminal.shell' must be a string")
    term_shortcut = terminal_raw.get("shortcut", DEFAULT_TERMINAL_SHORTCUT)
    if not isinstance(term_shortcut, str) or not term_shortcut.strip():
        raise ConfigIncompleteError(f"{source}: 'terminal.shortcut' must be a non-empty string")
    screenshot_dir = terminal_raw.get("screenshot_dir")
    if screenshot_dir is not None and not isinstance(screenshot_dir, str):
        raise ConfigIncompleteError(f"{source}: 'terminal.screenshot_dir' must be a string")
    paste_shortcut = terminal_raw.get(
        "screenshot_paste_shortcut", DEFAULT_SCREENSHOT_PASTE_SHORTCUT
    )
    if not isinstance(paste_shortcut, str) or not paste_shortcut.strip():
        raise ConfigIncompleteError(
            f"{source}: 'terminal.screenshot_paste_shortcut' must be a non-empty string"
        )
    launcher_command_raw = terminal_raw.get("launcher_command", DEFAULT_LAUNCHER_COMMAND)
    if not isinstance(launcher_command_raw, str):
        raise ConfigIncompleteError(f"{source}: 'terminal.launcher_command' must be a string")
    move_left_raw = terminal_raw.get("move_tab_left_shortcut", DEFAULT_MOVE_TAB_LEFT_SHORTCUT)
    if not isinstance(move_left_raw, str) or not move_left_raw.strip():
        raise ConfigIncompleteError(
            f"{source}: 'terminal.move_tab_left_shortcut' must be a non-empty string"
        )
    move_right_raw = terminal_raw.get("move_tab_right_shortcut", DEFAULT_MOVE_TAB_RIGHT_SHORTCUT)
    if not isinstance(move_right_raw, str) or not move_right_raw.strip():
        raise ConfigIncompleteError(
            f"{source}: 'terminal.move_tab_right_shortcut' must be a non-empty string"
        )
    terminal = TerminalConfig(
        shell=(term_shell.strip() or None) if term_shell else None,
        shortcut=term_shortcut.strip(),
        screenshot_dir=(screenshot_dir.strip() or None) if screenshot_dir else None,
        screenshot_paste_shortcut=paste_shortcut.strip(),
        launcher_command=launcher_command_raw.strip(),
        move_tab_left_shortcut=move_left_raw.strip(),
        move_tab_right_shortcut=move_right_raw.strip(),
    )

    return CondashConfig(
        conception_path=conception_path,
        workspace_path=workspace_path,
        worktrees_path=worktrees_path,
        repositories_primary=primary,
        repositories_secondary=secondary,
        repo_submodules=repo_submodules,
        terminal=terminal,
        port=port_raw,
        native=native_raw,
        open_with=open_with,
        pdf_viewer=pdf_viewer,
    )


def repositories_yaml_path(conception_path: Path | None) -> Path | None:
    """Return ``<conception_path>/config/repositories.yml`` or ``None``.

    Used by both loaders and savers so the path is defined in one place.
    """
    if conception_path is None:
        return None
    return Path(conception_path).expanduser() / REPOSITORIES_YAML_REL


def preferences_yaml_path(conception_path: Path | None) -> Path | None:
    """Return ``<conception_path>/config/preferences.yml`` or ``None``."""
    if conception_path is None:
        return None
    return Path(conception_path).expanduser() / PREFERENCES_YAML_REL


def load_preferences_yaml(target: Path) -> dict:
    """Read the preferences YAML file into a dict.

    Raises :class:`ConfigIncompleteError` on malformed YAML. Missing-file
    handling lives in :func:`load`; this function assumes ``target`` exists.
    """
    try:
        loaded = yaml.safe_load(target.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigIncompleteError(f"{target}: malformed YAML: {exc}") from exc
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ConfigIncompleteError(f"{target}: top-level YAML must be a mapping")
    return loaded


def _apply_preferences_yaml(cfg: CondashConfig, data: dict, source: Path) -> None:
    """Overlay ``pdf_viewer`` + ``terminal`` from the preferences YAML onto
    ``cfg`` in place. Both keys are optional; missing fields keep whatever
    defaults / TOML values cfg already carries.
    """
    if "pdf_viewer" in data:
        raw = data.get("pdf_viewer") or []
        if not isinstance(raw, list) or not all(isinstance(c, str) for c in raw):
            raise ConfigIncompleteError(f"{source}: 'pdf_viewer' must be a list of command strings")
        cfg.pdf_viewer = [c for c in (s.strip() for s in raw) if c]

    term_raw = data.get("terminal")
    if term_raw is not None:
        if not isinstance(term_raw, dict):
            raise ConfigIncompleteError(f"{source}: 'terminal' must be a mapping")
        current = cfg.terminal

        def _str(key: str, default: str) -> str:
            val = term_raw.get(key, default)
            if not isinstance(val, str) or not val.strip():
                raise ConfigIncompleteError(
                    f"{source}: 'terminal.{key}' must be a non-empty string"
                )
            return val.strip()

        shell_raw = term_raw.get("shell")
        if shell_raw is not None and not isinstance(shell_raw, str):
            raise ConfigIncompleteError(f"{source}: 'terminal.shell' must be a string")
        screenshot_dir_raw = term_raw.get("screenshot_dir")
        if screenshot_dir_raw is not None and not isinstance(screenshot_dir_raw, str):
            raise ConfigIncompleteError(f"{source}: 'terminal.screenshot_dir' must be a string")
        launcher_raw = term_raw.get("launcher_command", current.launcher_command)
        if not isinstance(launcher_raw, str):
            raise ConfigIncompleteError(f"{source}: 'terminal.launcher_command' must be a string")

        cfg.terminal = TerminalConfig(
            shell=(shell_raw.strip() or None) if shell_raw else None,
            shortcut=_str("shortcut", current.shortcut),
            screenshot_dir=(screenshot_dir_raw.strip() or None) if screenshot_dir_raw else None,
            screenshot_paste_shortcut=_str(
                "screenshot_paste_shortcut", current.screenshot_paste_shortcut
            ),
            launcher_command=launcher_raw.strip(),
            move_tab_left_shortcut=_str("move_tab_left_shortcut", current.move_tab_left_shortcut),
            move_tab_right_shortcut=_str(
                "move_tab_right_shortcut", current.move_tab_right_shortcut
            ),
        )

    cfg.preferences_source = source


def save_preferences_yaml(cfg: CondashConfig, path: Path | None = None) -> Path | None:
    """Atomically write ``cfg.pdf_viewer`` + ``cfg.terminal`` to the
    preferences YAML. Returns the written path, or ``None`` when no path
    can be resolved (``conception_path`` unset and no explicit ``path``).
    """
    target = path or preferences_yaml_path(cfg.conception_path)
    if target is None:
        return None
    target.parent.mkdir(parents=True, exist_ok=True)

    term = cfg.terminal
    payload: dict = {
        "pdf_viewer": list(cfg.pdf_viewer),
        "terminal": {
            "shell": term.shell or "",
            "shortcut": term.shortcut or DEFAULT_TERMINAL_SHORTCUT,
            "screenshot_dir": term.screenshot_dir or "",
            "screenshot_paste_shortcut": (
                term.screenshot_paste_shortcut or DEFAULT_SCREENSHOT_PASTE_SHORTCUT
            ),
            "launcher_command": term.launcher_command or "",
            "move_tab_left_shortcut": (
                term.move_tab_left_shortcut or DEFAULT_MOVE_TAB_LEFT_SHORTCUT
            ),
            "move_tab_right_shortcut": (
                term.move_tab_right_shortcut or DEFAULT_MOVE_TAB_RIGHT_SHORTCUT
            ),
        },
    }
    body = yaml.safe_dump(payload, sort_keys=False, default_flow_style=False, allow_unicode=True)
    rendered = PREFERENCES_YAML_HEADER + "\n" + body
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(rendered, encoding="utf-8")
    tmp.replace(target)
    return target


def load_repositories_yaml(target: Path) -> dict:
    """Read the repositories YAML file into a dict.

    Raises :class:`ConfigIncompleteError` on malformed YAML. Missing-file
    handling lives in :func:`load`; this function assumes ``target`` exists.
    """
    try:
        loaded = yaml.safe_load(target.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigIncompleteError(f"{target}: malformed YAML: {exc}") from exc
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ConfigIncompleteError(f"{target}: top-level YAML must be a mapping")
    return loaded


def _apply_repositories_yaml(cfg: CondashConfig, data: dict, source: Path) -> None:
    """Overlay the YAML-managed fields onto ``cfg`` in place."""
    ws_raw = data.get("workspace_path")
    cfg.workspace_path = Path(str(ws_raw)).expanduser() if ws_raw else None

    wt_raw = data.get("worktrees_path")
    cfg.worktrees_path = Path(str(wt_raw)).expanduser() if wt_raw else None

    repos = data.get("repositories") or {}
    if not isinstance(repos, dict):
        raise ConfigIncompleteError(f"{source}: 'repositories' must be a mapping")
    primary, primary_subs = _parse_repo_list(repos.get("primary"), source, "primary")
    secondary, secondary_subs = _parse_repo_list(repos.get("secondary"), source, "secondary")
    cfg.repositories_primary = primary
    cfg.repositories_secondary = secondary
    cfg.repo_submodules = {**primary_subs, **secondary_subs}

    open_with_raw = data.get("open_with") or {}
    if not isinstance(open_with_raw, dict):
        raise ConfigIncompleteError(f"{source}: 'open_with' must be a mapping")
    open_with: dict[str, OpenWithSlot] = {}
    for slot_key in OPEN_WITH_SLOT_KEYS:
        defaults = DEFAULT_OPEN_WITH[slot_key]
        slot_data = open_with_raw.get(slot_key) or {}
        if not isinstance(slot_data, dict):
            raise ConfigIncompleteError(f"{source}: 'open_with.{slot_key}' must be a mapping")
        label = slot_data.get("label", defaults["label"])
        if not isinstance(label, str):
            raise ConfigIncompleteError(f"{source}: 'open_with.{slot_key}.label' must be a string")
        commands_raw = slot_data.get("commands", defaults["commands"])
        if not isinstance(commands_raw, list) or not all(isinstance(c, str) for c in commands_raw):
            raise ConfigIncompleteError(
                f"{source}: 'open_with.{slot_key}.commands' must be a list of strings"
            )
        open_with[slot_key] = OpenWithSlot(label=label, commands=list(commands_raw))
    cfg.open_with = open_with
    cfg.yaml_source = source


def _render_yaml_repo_list(
    names: list[str],
    repo_submodules: dict[str, list[str]],
) -> list:
    """Serialise a repo-name list for YAML. Entries with submodules become
    mappings (``{name: ..., submodules: [...]}``); bare-name entries stay
    as strings. Order preserved.
    """
    out: list = []
    for name in names:
        subs = repo_submodules.get(name) or []
        if subs:
            out.append({"name": name, "submodules": list(subs)})
        else:
            out.append(name)
    return out


def save_repositories_yaml(cfg: CondashConfig, path: Path | None = None) -> Path | None:
    """Atomically write ``cfg``'s YAML-managed fields to the repositories
    YAML file. Returns the written path, or ``None`` when no path can be
    resolved (``conception_path`` unset and no explicit ``path`` passed).

    Comments in the existing file are discarded; the file-level header is
    re-injected from :data:`REPOSITORIES_YAML_HEADER` on every write.
    """
    target = path or repositories_yaml_path(cfg.conception_path)
    if target is None:
        return None
    target.parent.mkdir(parents=True, exist_ok=True)

    payload: dict = {
        "workspace_path": str(cfg.workspace_path) if cfg.workspace_path else "",
        "worktrees_path": str(cfg.worktrees_path) if cfg.worktrees_path else "",
        "repositories": {
            "primary": _render_yaml_repo_list(cfg.repositories_primary, cfg.repo_submodules),
            "secondary": _render_yaml_repo_list(cfg.repositories_secondary, cfg.repo_submodules),
        },
        "open_with": {
            slot_key: {
                "label": cfg.open_with[slot_key].label,
                "commands": list(cfg.open_with[slot_key].commands),
            }
            for slot_key in OPEN_WITH_SLOT_KEYS
            if slot_key in cfg.open_with
        },
    }

    body = yaml.safe_dump(payload, sort_keys=False, default_flow_style=False, allow_unicode=True)
    rendered = REPOSITORIES_YAML_HEADER + "\n" + body
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(rendered, encoding="utf-8")
    tmp.replace(target)
    return target


def load(
    path: Path | None = None,
    *,
    conception_override: Path | None = None,
    port_override: int | None = None,
    native_override: bool | None = None,
) -> CondashConfig:
    """Load config from disk.

    Reads the TOML at ``~/.config/condash/config.toml``, then — when
    ``conception_path`` resolves to an existing repositories YAML at
    ``<conception_path>/config/repositories.yml`` — overlays that file's
    values onto the YAML-managed fields (``workspace_path`` / ``worktrees_path``
    / ``repositories`` / ``open_with``). The TOML values for those fields
    are used only as a first-run fallback when no YAML is present, and are
    stripped from disk on the next :func:`save`.

    Raises ``ConfigNotFoundError`` if the TOML file does not exist. Missing
    ``conception_path`` no longer raises — it leaves the field as ``None``
    so the dashboard can launch and let the user pick it from the gear.
    ``ConfigIncompleteError`` is still raised for shape errors.

    ``conception_override`` / ``port_override`` / ``native_override`` are
    one-shot runtime overrides (e.g. from ``--conception-path`` /
    ``--port`` / ``--native|--no-native``) and are not written back to the
    config file.
    """
    target = path or config_path()
    if not target.is_file():
        raise ConfigNotFoundError(target)
    data = tomllib.loads(target.read_text(encoding="utf-8"))
    cfg = _parse(data, target)
    if conception_override is not None:
        cfg.conception_path = Path(conception_override).expanduser()
    if port_override is not None:
        if not 0 <= port_override <= 65535:
            raise ConfigIncompleteError(f"--port must be between 0 and 65535 (got {port_override})")
        cfg.port = port_override
    if native_override is not None:
        cfg.native = native_override

    yaml_target = repositories_yaml_path(cfg.conception_path)
    if yaml_target is not None and yaml_target.is_file():
        yaml_data = load_repositories_yaml(yaml_target)
        _apply_repositories_yaml(cfg, yaml_data, yaml_target)

    prefs_target = preferences_yaml_path(cfg.conception_path)
    if prefs_target is not None and prefs_target.is_file():
        prefs_data = load_preferences_yaml(prefs_target)
        _apply_preferences_yaml(cfg, prefs_data, prefs_target)

    if cfg.yaml_source is not None or cfg.preferences_source is not None:
        _log_deprecated_toml_keys(data, target)

    return cfg


def _log_deprecated_toml_keys(toml_data: dict, toml_path: Path) -> None:
    """One-shot startup warning when the TOML still carries YAML-managed
    keys after the YAML has taken over. The next save drops them; until
    then the duplicates are ignored silently except for this log line.
    """
    leftovers: list[tuple[str, str]] = []
    if toml_data.get("workspace_path"):
        leftovers.append(("workspace_path", REPOSITORIES_YAML_REL))
    if toml_data.get("worktrees_path"):
        leftovers.append(("worktrees_path", REPOSITORIES_YAML_REL))
    if toml_data.get("repositories"):
        leftovers.append(("[repositories]", REPOSITORIES_YAML_REL))
    if toml_data.get("open_with"):
        leftovers.append(("[open_with]", REPOSITORIES_YAML_REL))
    if toml_data.get("pdf_viewer"):
        leftovers.append(("pdf_viewer", PREFERENCES_YAML_REL))
    if toml_data.get("terminal"):
        leftovers.append(("[terminal]", PREFERENCES_YAML_REL))
    if leftovers:
        for key, moved_to in leftovers:
            log.info(
                "%s: %s is now managed by %s — the next Save from the Configuration "
                "modal will remove it from the TOML.",
                toml_path,
                key,
                moved_to,
            )
