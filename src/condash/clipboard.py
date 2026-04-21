"""Cross-platform clipboard read/write for the embedded terminal.

Used in two places:

- the FastAPI ``/clipboard`` GET/POST routes (browser mode and Qt mode),
- the pywebview ``js_api`` :class:`ClipboardBridge` (native Qt mode), which
  exposes ``window.pywebview.api.clipboard_get`` / ``clipboard_set`` so the
  in-modal Ctrl+V can pull text without going through the FastAPI loop.

Priority chain on each side: live ``QClipboard`` (only when running inside
pywebview's Qt backend) → ``wl-paste`` → ``xclip`` → ``xsel``. The Qt path
is the only one that survives in a Wayland sandbox without a clipboard
helper installed; the others are graceful fallbacks for browser mode.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def _qt_clipboard():
    """Return the running ``QClipboard``, or ``None`` if Qt isn't initialised.

    Condash runs inside pywebview's Qt backend when ``native=true`` (the
    default), so a ``QGuiApplication`` is live and ``clipboard()`` just
    works. Browser mode has no Qt — the subprocess fallbacks take over.
    """
    try:
        from qtpy.QtGui import QGuiApplication
    except ImportError:
        return None
    app = QGuiApplication.instance()
    if app is None:
        return None
    try:
        return app.clipboard()
    except (RuntimeError, AttributeError):
        return None


def clipboard_read() -> str:
    """Return the current system clipboard contents (best effort, may be empty)."""
    import subprocess as _sp

    cb = _qt_clipboard()
    if cb is not None:
        try:
            return cb.text() or ""
        except RuntimeError as exc:
            log.debug("clipboard_read: Qt clipboard unavailable: %s", exc)
    for argv in (
        ["wl-paste", "--no-newline"],
        ["xclip", "-selection", "clipboard", "-o"],
        ["xsel", "--clipboard", "--output"],
    ):
        try:
            out = _sp.run(argv, capture_output=True, timeout=2)
        except FileNotFoundError:
            continue
        except (OSError, _sp.SubprocessError) as exc:
            log.debug("clipboard_read: %s failed: %s", argv[0], exc)
            continue
        if out.returncode == 0:
            return out.stdout.decode("utf-8", errors="replace")
    return ""


def clipboard_write(text: str) -> bool:
    """Write ``text`` to the system clipboard. Returns True on success."""
    import subprocess as _sp

    cb = _qt_clipboard()
    if cb is not None:
        try:
            cb.setText(text)
            return True
        except RuntimeError as exc:
            log.debug("clipboard_write: Qt clipboard unavailable: %s", exc)
    for argv in (
        ["wl-copy"],
        ["xclip", "-selection", "clipboard", "-i"],
        ["xsel", "--clipboard", "--input"],
    ):
        try:
            proc = _sp.Popen(argv, stdin=_sp.PIPE)
        except FileNotFoundError:
            continue
        except OSError as exc:
            log.debug("clipboard_write: %s failed to spawn: %s", argv[0], exc)
            continue
        try:
            proc.communicate(text.encode("utf-8"), timeout=2)
        except (OSError, _sp.SubprocessError) as exc:
            log.debug("clipboard_write: %s communicate failed: %s", argv[0], exc)
            try:
                proc.kill()
            except OSError:
                pass
            continue
        if proc.returncode == 0:
            return True
    return False


class ClipboardBridge:
    """pywebview JS→Python bridge for clipboard access (Qt native mode only).

    Exposed on ``window.pywebview.api`` via ``js_api``. Each method runs on
    pywebview's main thread (the same thread that owns the QApplication) so
    ``QClipboard`` is safe to touch — unlike the FastAPI worker thread
    where ``QGuiApplication.instance()`` returns ``None`` or Qt warns about
    cross-thread GUI access.

    Method names are intentionally short: the JS side calls
    ``window.pywebview.api.clipboard_get()`` /
    ``clipboard_set(text)``.
    """

    def clipboard_get(self) -> str:
        return clipboard_read()

    def clipboard_set(self, text: str) -> bool:
        return clipboard_write(text or "")
