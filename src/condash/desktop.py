"""Linux XDG desktop-entry installer for condash.

Exposes ``install`` / ``uninstall`` so a user running on a Linux desktop can
register condash with their application launcher (GNOME Activities, KDE
Kickoff, Cinnamon menu, …) in one command:

    condash install-desktop
    condash uninstall-desktop

Installs a single user-local entry under ``$XDG_DATA_HOME`` — never touches
``/usr``. The entry points at the absolute path of whichever ``condash``
binary called this command, so it survives venv / pipx isolation.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .app import icon_path

log = logging.getLogger(__name__)

APP_ID = "condash"
DESKTOP_FILE_NAME = f"{APP_ID}.desktop"
ICON_FILE_NAME = f"{APP_ID}.svg"


def _xdg_data_home() -> Path:
    raw = os.environ.get("XDG_DATA_HOME")
    return Path(raw).expanduser() if raw else Path.home() / ".local" / "share"


def _applications_dir() -> Path:
    return _xdg_data_home() / "applications"


def _icons_dir() -> Path:
    return _xdg_data_home() / "icons" / "hicolor" / "scalable" / "apps"


def desktop_file_path() -> Path:
    return _applications_dir() / DESKTOP_FILE_NAME


def installed_icon_path() -> Path:
    return _icons_dir() / ICON_FILE_NAME


def _binary_path() -> str:
    """Resolve the absolute path of the currently-running condash binary."""
    argv0 = Path(sys.argv[0]).resolve()
    if argv0.exists():
        return str(argv0)
    found = shutil.which("condash")
    if found:
        return str(Path(found).resolve())
    return "condash"


def _format_desktop_entry(exec_path: str, icon_full_path: Path) -> str:
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Version=1.0\n"
        "Name=Condash\n"
        "GenericName=Conception Dashboard\n"
        "Comment=Dashboard for markdown-based projects, incidents and documents\n"
        f"Exec={exec_path}\n"
        f"Icon={icon_full_path}\n"
        "Terminal=false\n"
        "Categories=Development;Office;ProjectManagement;\n"
        "StartupNotify=true\n"
        "StartupWMClass=condash\n"
    )


def install() -> dict[str, str]:
    """Install the user-local desktop entry. Returns the resolved paths."""
    apps_dir = _applications_dir()
    icons_dir = _icons_dir()
    apps_dir.mkdir(parents=True, exist_ok=True)
    icons_dir.mkdir(parents=True, exist_ok=True)

    icon_dest = installed_icon_path()
    shutil.copyfile(icon_path(), icon_dest)

    desktop_dest = desktop_file_path()
    desktop_dest.write_text(
        _format_desktop_entry(_binary_path(), icon_dest),
        encoding="utf-8",
    )
    desktop_dest.chmod(0o644)

    if shutil.which("update-desktop-database"):
        subprocess.run(
            ["update-desktop-database", str(apps_dir)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    return {
        "desktop_file": str(desktop_dest),
        "icon_file": str(icon_dest),
        "exec": _binary_path(),
    }


def uninstall() -> dict[str, bool]:
    """Remove the user-local desktop entry and bundled icon."""
    desktop_dest = desktop_file_path()
    icon_dest = installed_icon_path()
    desktop_removed = False
    icon_removed = False
    if desktop_dest.exists():
        desktop_dest.unlink()
        desktop_removed = True
    if icon_dest.exists():
        icon_dest.unlink()
        icon_removed = True
    if desktop_removed and shutil.which("update-desktop-database"):
        subprocess.run(
            ["update-desktop-database", str(_applications_dir())],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    return {
        "desktop_removed": desktop_removed,
        "icon_removed": icon_removed,
    }
