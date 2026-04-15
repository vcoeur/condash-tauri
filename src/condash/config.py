"""Configuration loader for condash.

Config file lives at ``~/.config/condash/config.toml`` (or ``$XDG_CONFIG_HOME``
if set). Schema:

    conception_path = "/path/to/conception"
    port = 0          # 0 = let the OS pick a free port
    native = true     # false = serve in your browser instead of a window

    [repositories]
    primary = ["repo-a", "repo-b"]
    secondary = ["repo-c", "repo-d"]

First-run flow: if the file is missing, ``condash init`` (or
``condash config edit``) writes a commented template that the user must edit
before condash can launch the dashboard. The template is shipped as
``DEFAULT_CONFIG_TEMPLATE`` below — example values only, never real paths.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG_TEMPLATE = """\
# condash configuration
#
# Uncomment and edit the values below before launching `condash`.

# conception_path: absolute path to the directory holding your conception items
# (projects/, incidents/, documents/). Required.
# conception_path = "/path/to/conception"

# port: TCP port the embedded HTTP server binds to. 0 means "let the OS
# pick a free port" (default). Set a fixed port if you want to reach the
# dashboard from your browser at http://127.0.0.1:<port>.
# port = 0

# native: true (default) opens a native desktop window via pywebview.
# Set to false to serve the dashboard in your usual browser instead —
# useful if you don't have GTK/Qt Python bindings installed.
# native = true

# [repositories]
# primary:   repos shown at the top of the dashboard's repo strip
# secondary: repos shown in the collapsed/secondary section
# Both are lists of directory names found next to `conception_path`.
# primary = ["repo-a", "repo-b"]
# secondary = ["repo-c", "repo-d"]
"""


@dataclass
class CondashConfig:
    """Runtime configuration for a condash session."""

    conception_path: Path
    repositories_primary: list[str] = field(default_factory=list)
    repositories_secondary: list[str] = field(default_factory=list)
    port: int = 0
    native: bool = True


def config_path() -> Path:
    """Return the resolved path to the condash config file."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / "condash" / "config.toml"


def _toml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _format_toml(cfg: CondashConfig) -> str:
    lines = [
        f'conception_path = "{_toml_escape(str(cfg.conception_path))}"',
        "",
        "[repositories]",
        "primary = [" + ", ".join(f'"{_toml_escape(r)}"' for r in cfg.repositories_primary) + "]",
        "secondary = ["
        + ", ".join(f'"{_toml_escape(r)}"' for r in cfg.repositories_secondary)
        + "]",
        "",
    ]
    return "\n".join(lines)


def save(cfg: CondashConfig, path: Path | None = None) -> Path:
    """Atomically write a config file. Returns the path written to."""
    target = path or config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(_format_toml(cfg), encoding="utf-8")
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


def _parse(data: dict, source: Path) -> CondashConfig:
    conception_raw = data.get("conception_path")
    if not conception_raw:
        raise ConfigIncompleteError(
            f"{source}: missing required key 'conception_path' "
            f"(edit the file and uncomment the example)"
        )
    conception_path = Path(str(conception_raw)).expanduser()
    repos = data.get("repositories") or {}
    primary = list(repos.get("primary") or [])
    secondary = list(repos.get("secondary") or [])

    port_raw = data.get("port", 0)
    if not isinstance(port_raw, int) or not 0 <= port_raw <= 65535:
        raise ConfigIncompleteError(
            f"{source}: 'port' must be an integer between 0 and 65535"
        )

    native_raw = data.get("native", True)
    if not isinstance(native_raw, bool):
        raise ConfigIncompleteError(f"{source}: 'native' must be a boolean")

    return CondashConfig(
        conception_path=conception_path,
        repositories_primary=[str(r) for r in primary],
        repositories_secondary=[str(r) for r in secondary],
        port=port_raw,
        native=native_raw,
    )


def load(
    path: Path | None = None,
    *,
    conception_override: Path | None = None,
) -> CondashConfig:
    """Load config from disk.

    Raises ``ConfigNotFoundError`` if the file does not exist and
    ``ConfigIncompleteError`` if it exists but is missing required values.
    The CLI is responsible for turning those into actionable error messages
    that point the user at ``condash init`` or ``condash config edit``.

    ``conception_override`` is a one-shot runtime override (e.g. from
    ``--conception-path``) and is not written back to the config file.
    """
    target = path or config_path()
    if not target.is_file():
        raise ConfigNotFoundError(target)
    data = tomllib.loads(target.read_text(encoding="utf-8"))
    cfg = _parse(data, target)
    if conception_override is not None:
        cfg.conception_path = Path(conception_override).expanduser()
    return cfg
