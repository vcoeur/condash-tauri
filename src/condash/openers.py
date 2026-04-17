"""External-launcher helpers for the per-repo action buttons and note links.

Four public-ish entry points:
  - :func:`_open_path` — fire the configured ``main_ide`` / ``secondary_ide``
    / ``terminal`` command against a sandbox-validated directory.
  - :func:`_os_open` — hand a file to the OS default (``xdg-open`` / ``open``
    / ``startfile``), with a ``pdf_viewer`` fallback chain for PDFs.
  - :func:`_is_external_url` / :func:`_open_external` — recognise
    ``http(s)://…`` anchors and route them through the host browser.
"""

from __future__ import annotations

import logging
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

from .context import RenderCtx

log = logging.getLogger(__name__)


def _open_path(ctx: RenderCtx, slot_key, path):
    """Launch the user-configured command for ``slot_key`` against ``path``."""
    path_str = str(path)
    slot = ctx.open_with.get(slot_key)
    if slot is None:
        log.warning("unknown slot: %r", slot_key)
        return False
    candidates = slot.resolve(path_str)
    if not candidates:
        log.warning("%s: no commands configured", slot_key)
        return False
    last_err = None
    for cmd in candidates:
        try:
            subprocess.Popen(
                cmd,
                cwd=path_str,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            log.info("%s: launched %s", slot_key, cmd[0])
            return True
        except FileNotFoundError as exc:
            last_err = exc
            continue
        except OSError as exc:
            log.warning("%s: %s failed: %s", slot_key, cmd[0], exc)
            return False
    log.warning("%s: no launcher found (last error: %s)", slot_key, last_err)
    return False


def _try_pdf_viewer(ctx: RenderCtx, path_str: str) -> bool:
    """Try the configured ``pdf_viewer`` fallback chain.

    Entries may include a literal ``{path}`` placeholder; if none is
    present the absolute path is appended as an extra argv entry. That
    matches the intuition of typing ``evince`` into the config field and
    expecting the PDF to open in evince — without the auto-append the
    viewer launches with no file argument and the user sees an empty
    window (the original "I set evince but it doesn't open in evince"
    bug).
    """
    for raw in ctx.pdf_viewer:
        if not raw.strip():
            continue
        try:
            argv = shlex.split(raw)
        except ValueError as exc:
            log.warning("pdf_viewer parse failed for %r: %s", raw, exc)
            continue
        had_placeholder = "{path}" in raw
        argv = [arg.replace("{path}", path_str) for arg in argv]
        if not argv:
            continue
        if not had_placeholder:
            argv.append(path_str)
        try:
            subprocess.Popen(
                argv,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            log.info("pdf_viewer: launched %s", argv[0])
            return True
        except FileNotFoundError:
            log.debug("pdf_viewer: %s not on PATH, trying next", argv[0])
            continue
        except OSError as exc:
            log.warning("pdf_viewer %r failed: %s", argv[0], exc)
            continue
    return False


def _os_open(ctx: RenderCtx, path: Path) -> bool:
    """Hand ``path`` to the OS-native default-application launcher.

    Linux uses ``xdg-open``; macOS ``open``; Windows uses ``os.startfile``.
    PDFs additionally honour the ``pdf_viewer`` config chain and only fall
    back to the OS default if every configured command fails to launch.
    """
    path_str = str(path)
    if path.suffix.lower() == ".pdf" and _try_pdf_viewer(ctx, path_str):
        return True
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", path_str], start_new_session=True)
        elif os.name == "nt":
            os.startfile(path_str)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(
                ["xdg-open", path_str],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        return True
    except OSError as exc:
        log.warning("open-doc failed: %s", exc)
        return False


_EXTERNAL_URL_RE = re.compile(r"^https?://[^\s]+$", re.IGNORECASE)


def _is_external_url(url: str) -> bool:
    return bool(url) and bool(_EXTERNAL_URL_RE.match(url))


def _open_external(url: str) -> bool:
    """Open ``url`` in the user's default browser via ``webbrowser``.

    pywebview intercepts in-page navigation, so we always route external
    URLs through the host browser — otherwise they'd replace the dashboard.
    """
    import webbrowser

    try:
        return bool(webbrowser.open(url, new=2))
    except (OSError, webbrowser.Error) as exc:
        log.warning("open-external failed: %s", exc)
        return False
