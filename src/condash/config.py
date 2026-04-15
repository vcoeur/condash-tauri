"""Configuration loader for condash.

Config file lives at ``~/.config/condash/config.toml`` (or ``$XDG_CONFIG_HOME``
if set). Schema:

    conception_path = "/path/to/conception"

    [repositories]
    primary = ["repo1", "repo2"]
    secondary = ["repo3", "repo4"]

First-run flow: if the file is missing, ``load`` prompts for a conception
directory on stdin, writes a default config, and returns it.
"""

from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_PRIMARY: list[str] = []
DEFAULT_SECONDARY: list[str] = []


@dataclass
class CondashConfig:
    """Runtime configuration for a condash session."""

    conception_path: Path
    repositories_primary: list[str] = field(default_factory=list)
    repositories_secondary: list[str] = field(default_factory=list)


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
        "primary = ["
        + ", ".join(f'"{_toml_escape(r)}"' for r in cfg.repositories_primary)
        + "]",
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


def _parse(data: dict, source: Path) -> CondashConfig:
    conception_raw = data.get("conception_path")
    if not conception_raw:
        raise ValueError(f"{source}: missing required key 'conception_path'")
    conception_path = Path(str(conception_raw)).expanduser()
    repos = data.get("repositories") or {}
    primary = list(repos.get("primary") or [])
    secondary = list(repos.get("secondary") or [])
    return CondashConfig(
        conception_path=conception_path,
        repositories_primary=[str(r) for r in primary],
        repositories_secondary=[str(r) for r in secondary],
    )


def _prompt_first_run(target: Path) -> CondashConfig:
    print(f"condash: no config at {target}", file=sys.stderr)
    print("condash: first-run setup", file=sys.stderr)
    default = Path.home() / "src" / "vcoeur" / "conception"
    prompt = f"conception directory [{default}]: "
    try:
        answer = input(prompt).strip()
    except EOFError:
        answer = ""
    conception_path = Path(answer).expanduser() if answer else default
    if not conception_path.is_dir():
        print(
            f"condash: warning: {conception_path} is not an existing directory",
            file=sys.stderr,
        )
    cfg = CondashConfig(
        conception_path=conception_path,
        repositories_primary=list(DEFAULT_PRIMARY),
        repositories_secondary=list(DEFAULT_SECONDARY),
    )
    save(cfg, target)
    print(f"condash: wrote config to {target}", file=sys.stderr)
    return cfg


def load(
    path: Path | None = None,
    *,
    conception_override: Path | None = None,
) -> CondashConfig:
    """Load config, running first-run prompt if the file is missing.

    ``conception_override`` is a one-shot runtime override (e.g. from
    ``--conception-path``) and is not written back to the config file.
    """
    target = path or config_path()
    if target.is_file():
        data = tomllib.loads(target.read_text(encoding="utf-8"))
        cfg = _parse(data, target)
    else:
        cfg = _prompt_first_run(target)
    if conception_override is not None:
        cfg.conception_path = Path(conception_override).expanduser()
    return cfg
