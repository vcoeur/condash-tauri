"""Configuration loader for condash.

Config file lives at ``~/.config/condash/config.toml`` (or ``$XDG_CONFIG_HOME``
if set). Schema:

    conception_path = "/path/to/conception"
    workspace_path  = "/path/to/code/workspace"   # optional; enables repo strip
    worktrees_path  = "/path/to/git/worktrees"    # optional; "open in IDE" sandbox
    port            = 0                           # 0 = OS picks a free port
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

log = logging.getLogger(__name__)

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

# port: TCP port the embedded HTTP server binds to. 0 means "let the OS
# pick a free port" (default). Set a fixed port if you want to reach the
# dashboard from your browser at http://127.0.0.1:<port>.
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
    """Runtime configuration for a condash session."""

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

    # Top-level scalars
    if cfg.conception_path is not None:
        doc["conception_path"] = str(cfg.conception_path)
    elif "conception_path" in doc:
        del doc["conception_path"]
    if cfg.workspace_path is not None:
        doc["workspace_path"] = str(cfg.workspace_path)
    elif "workspace_path" in doc:
        del doc["workspace_path"]
    if cfg.worktrees_path is not None:
        doc["worktrees_path"] = str(cfg.worktrees_path)
    elif "worktrees_path" in doc:
        del doc["worktrees_path"]
    doc["port"] = int(cfg.port)
    doc["native"] = bool(cfg.native)
    if cfg.pdf_viewer:
        doc["pdf_viewer"] = list(cfg.pdf_viewer)
    elif "pdf_viewer" in doc:
        del doc["pdf_viewer"]

    # [repositories]
    repos = doc.get("repositories")
    if not hasattr(repos, "value"):
        repos = table()
        doc["repositories"] = repos
    repos["primary"] = _render_repo_list(cfg.repositories_primary, cfg.repo_submodules)
    repos["secondary"] = _render_repo_list(cfg.repositories_secondary, cfg.repo_submodules)

    # [terminal]
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

    # [open_with.<slot>]
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

    Each entry is either a bare string (name only) or an inline table
    ``{name = "...", submodules = [...]}``. Submodule paths are plain
    subdirectories relative to the repo root, not real git submodules.
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


def load(
    path: Path | None = None,
    *,
    conception_override: Path | None = None,
    port_override: int | None = None,
    native_override: bool | None = None,
) -> CondashConfig:
    """Load config from disk.

    Raises ``ConfigNotFoundError`` if the file does not exist. Missing
    ``conception_path`` no longer raises — it leaves the field as ``None``
    so the dashboard can launch and let the user pick it from the gear.
    ``ConfigIncompleteError`` is still raised for shape errors (e.g. a
    non-integer port or a malformed ``[repositories]`` entry).

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
    return cfg
