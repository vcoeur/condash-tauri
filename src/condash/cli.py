"""Typer CLI entry point for condash.

Default invocation (`condash` with no subcommand) launches the NiceGUI
native window. Explicit subcommands cover configuration inspection /
editing, the tidy pass, and the first-run bootstrap. Matches the shape
quelle uses (`<app> init`, `<app> config show / path / edit`) so the
three vcoeur CLI tools present the same config UX to users.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
from pathlib import Path
from typing import Any

import typer

from . import __version__
from .config import (
    CondashConfig,
    ConfigIncompleteError,
    ConfigNotFoundError,
    config_path,
    load,
    write_default_template,
)

app = typer.Typer(
    help="Standalone desktop dashboard for markdown-based conception items.",
    no_args_is_help=False,
    add_completion=False,
)

config_app = typer.Typer(
    help="Inspect and edit the condash configuration.",
    no_args_is_help=True,
)
app.add_typer(config_app, name="config")


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", help="Print version and exit."),
    config_file: Path | None = typer.Option(
        None,
        "--config",
        help="Path to config file (default: ~/.config/condash/config.toml)",
    ),
    conception_path_override: Path | None = typer.Option(
        None,
        "--conception-path",
        help="One-shot override of the conception directory (does not touch config).",
    ),
) -> None:
    if version:
        typer.echo(f"condash {__version__}")
        raise typer.Exit(0)

    ctx.obj = {
        "config_file": config_file,
        "conception_override": conception_path_override,
    }

    if ctx.invoked_subcommand is not None:
        return

    # Default behaviour: launch the dashboard window.
    cfg = _load_or_exit(config_file, conception_path_override)
    if not cfg.conception_path.is_dir():
        typer.echo(
            f"condash: error: conception directory does not exist: {cfg.conception_path}",
            err=True,
        )
        raise typer.Exit(2)

    from . import legacy

    legacy.init(cfg)

    from . import app as app_module

    app_module.run(cfg)


@app.command("tidy")
def cmd_tidy(ctx: typer.Context) -> None:
    """Move done items into YYYY-MM/ archive dirs and exit."""
    obj = ctx.obj or {}
    cfg = _load_or_exit(obj.get("config_file"), obj.get("conception_override"))
    if not cfg.conception_path.is_dir():
        typer.echo(
            f"condash: error: conception directory does not exist: {cfg.conception_path}",
            err=True,
        )
        raise typer.Exit(2)

    from . import legacy

    legacy.init(cfg)
    moves = legacy.run_tidy()
    if moves:
        for old, new in moves:
            typer.echo(f"  {old} \u2192 {new}")
        typer.echo(f"{len(moves)} item(s) moved.")
    else:
        typer.echo("Nothing to move.")


@app.command("init")
def cmd_init() -> None:
    """Write a commented config template if missing; print the resolved path."""
    target = config_path()
    created = _seed_default_config(target)
    typer.echo(f"config_file: {target}")
    if created:
        typer.echo("(created from template — edit the file to set conception_path)")
        typer.echo("Run `condash config edit` to open it in your editor.")
    else:
        typer.echo("(already present)")


@app.command("install-desktop")
def cmd_install_desktop() -> None:
    """Register condash with your XDG desktop launcher (Linux only)."""
    if platform.system() != "Linux":
        _error("install-desktop is only supported on Linux.")
    from . import desktop

    paths = desktop.install()
    typer.echo("Installed desktop entry:")
    typer.echo(f"  desktop file: {paths['desktop_file']}")
    typer.echo(f"  icon file:    {paths['icon_file']}")
    typer.echo(f"  exec:         {paths['exec']}")
    typer.echo("Condash should now appear in your application launcher.")


@app.command("uninstall-desktop")
def cmd_uninstall_desktop() -> None:
    """Remove the user-local condash desktop entry (Linux only)."""
    if platform.system() != "Linux":
        _error("uninstall-desktop is only supported on Linux.")
    from . import desktop

    result = desktop.uninstall()
    if result["desktop_removed"] or result["icon_removed"]:
        typer.echo("Removed:")
        if result["desktop_removed"]:
            typer.echo(f"  {desktop.desktop_file_path()}")
        if result["icon_removed"]:
            typer.echo(f"  {desktop.installed_icon_path()}")
    else:
        typer.echo("Nothing to remove (no condash desktop entry installed).")


@config_app.command("show")
def cmd_config_show(
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Show the effective configuration."""
    target = config_path()
    if not target.exists():
        _error(f"No config file at {target}. Run `condash init` to create one.")
    cfg = _safe_load(target)
    payload = _full_payload(target, cfg)
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
    else:
        for key, value in payload.items():
            typer.echo(f"{key}: {value}")


@config_app.command("path")
def cmd_config_path(
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Print the resolved config file path."""
    target = config_path()
    payload = {
        "config_file": str(target),
        "exists": target.exists(),
    }
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
    else:
        typer.echo(f"config_file: {target}")
        typer.echo(f"exists: {target.exists()}")


@config_app.command("edit")
def cmd_config_edit() -> None:
    """Open the condash config.toml in $VISUAL / $EDITOR or the OS default editor."""
    target = config_path()
    created = _seed_default_config(target)
    editor = _resolve_editor()
    if created:
        typer.echo(f"Created {target} from template — uncomment values before saving.")
    typer.echo(f"Opening {target} in {editor!r}")
    subprocess.run([editor, str(target)], check=False)


def _seed_default_config(target: Path) -> bool:
    """Write the default config template at ``target`` if it does not exist."""
    if target.exists():
        return False
    write_default_template(target)
    return True


def _load_or_exit(
    config_file: Path | None,
    conception_override: Path | None,
) -> CondashConfig:
    """Load the config or exit with an actionable error message."""
    try:
        return load(path=config_file, conception_override=conception_override)
    except ConfigNotFoundError as exc:
        _error(
            f"No config file at {exc}. Run `condash init` to create one, "
            f"then `condash config edit` to fill it in."
        )
    except ConfigIncompleteError as exc:
        _error(f"{exc}. Run `condash config edit` to fix it.")


def _full_payload(target: Path, cfg: CondashConfig) -> dict[str, Any]:
    return {
        "config_file": str(target),
        "conception_path": str(cfg.conception_path),
        "workspace_path": str(cfg.workspace_path) if cfg.workspace_path else None,
        "worktrees_path": str(cfg.worktrees_path) if cfg.worktrees_path else None,
        "port": cfg.port,
        "native": cfg.native,
        "repositories_primary": cfg.repositories_primary,
        "repositories_secondary": cfg.repositories_secondary,
        "repo_submodules": dict(cfg.repo_submodules),
        "open_with": {
            slot_key: {
                "label": slot.label,
                "commands": list(slot.commands),
            }
            for slot_key, slot in cfg.open_with.items()
        },
    }


def _safe_load(target: Path) -> CondashConfig:
    try:
        return load(path=target)
    except Exception as exc:
        _error(str(exc))


def _error(message: str) -> Any:
    typer.echo(f"condash: error: {message}", err=True)
    raise typer.Exit(2)


def _resolve_editor() -> str:
    for var in ("VISUAL", "EDITOR"):
        value = os.environ.get(var)
        if value:
            return value
    system = platform.system()
    if system == "Windows":
        return "notepad"
    if system == "Darwin":
        return "open"
    return "xdg-open"


def main() -> None:
    """Entry point used by the `condash` console script."""
    app()


if __name__ == "__main__":
    main()
