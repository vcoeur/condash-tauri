"""NiceGUI-backed native window for condash.

The existing ``dashboard.html`` is served verbatim at ``/``; all the AJAX
endpoints the JS calls (``/toggle``, ``/add-step``, ``/tidy``, …) are
re-implemented here as FastAPI routes on top of NiceGUI's underlying
FastAPI instance.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from importlib.resources import files as _package_files
from pathlib import Path

from fastapi import Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, Response
from nicegui import app as _ng_app
from nicegui import ui

from . import config as config_mod
from . import legacy
from .config import (
    OPEN_WITH_SLOT_KEYS,
    CondashConfig,
    OpenWithSlot,
)

# Holds the live runtime config so the in-app editor can mutate it after a
# successful POST /config without forcing a process restart. Initialized by
# `run` before NiceGUI starts.
_RUNTIME_CFG: CondashConfig | None = None


def icon_path() -> str:
    """Absolute path to the bundled app icon (SVG)."""
    return str(_package_files("condash") / "assets" / "favicon.svg")


def _set_qt_desktop_identity() -> None:
    """Advertise this process to Qt as "condash" so Wayland compositors can
    match the running window to ``condash.desktop``.

    On Wayland (default on modern GNOME/KDE), windows are matched to their
    ``.desktop`` file via the ``xdg_toplevel::set_app_id`` protocol. Qt's
    Wayland backend derives that app_id from
    ``QGuiApplication::desktopFileName()``. If it is not set, the app_id
    falls back to the executable name that pywebview happens to pass to
    ``QApplication(sys.argv)`` — which is not ``condash`` after pipx
    wrapping — so GNOME Shell cannot resolve the ``.desktop`` entry and
    the task switcher shows a generic icon.

    Setting this before ``ui.run()`` (which ends up creating the
    QApplication inside pywebview's Qt backend) makes the match succeed.
    """
    try:
        from qtpy.QtGui import QGuiApplication
    except ImportError:
        return
    QGuiApplication.setApplicationName("condash")
    QGuiApplication.setApplicationDisplayName("Condash")
    QGuiApplication.setDesktopFileName("condash")


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": message})


def _register_routes() -> None:
    """Attach all API routes to NiceGUI's FastAPI instance."""

    @_ng_app.get("/", response_class=HTMLResponse)
    def index():
        items = legacy.collect_items()
        return HTMLResponse(content=legacy.render_page(items))

    @_ng_app.get("/favicon.svg")
    def favicon_svg():
        data = legacy._favicon_bytes()
        if data is None:
            return Response(status_code=404)
        return Response(
            content=data,
            media_type="image/svg+xml",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    @_ng_app.get("/favicon.ico")
    def favicon_ico():
        data = legacy._favicon_bytes()
        if data is None:
            return Response(status_code=404)
        return Response(content=data, media_type="image/svg+xml")

    @_ng_app.get("/check-updates")
    def check_updates():
        items = legacy.collect_items()
        return {
            "fingerprint": legacy._compute_fingerprint(items),
            "tidy_needed": legacy._tidy_needed(items),
            "git_fingerprint": legacy._git_fingerprint(),
        }

    @_ng_app.get("/note")
    def get_note(path: str = ""):
        full = legacy.validate_note_path(path)
        if full is None:
            return Response(status_code=403)
        return HTMLResponse(content=legacy._render_note(full))

    @_ng_app.get("/note-raw")
    def get_note_raw(path: str = ""):
        """Return plain-text content + mtime for the in-modal edit mode."""
        full = legacy.validate_note_path(path)
        if full is None:
            return _error(403, "invalid path")
        kind = legacy._note_kind(full)
        if kind not in ("md", "text"):
            return _error(400, f"not editable ({kind})")
        return legacy.read_note_raw(full)

    @_ng_app.post("/note")
    async def post_note(req: Request):
        """Atomically overwrite a note file with the editor's content."""
        data = await req.json()
        full = legacy.validate_note_path(str(data.get("path") or ""))
        if full is None:
            return _error(403, "invalid path")
        if legacy._note_kind(full) not in ("md", "text"):
            return _error(400, "not editable")
        content = data.get("content")
        if not isinstance(content, str):
            return _error(400, "content must be a string")
        result = legacy.write_note(full, content, data.get("expected_mtime"))
        if not result.get("ok"):
            return JSONResponse(status_code=409, content=result)
        return result

    @_ng_app.post("/note/rename")
    async def post_note_rename(req: Request):
        """Rename a file under ``<item>/notes/`` preserving the extension."""
        data = await req.json()
        result = legacy.rename_note(
            str(data.get("path") or ""),
            str(data.get("new_stem") or ""),
        )
        if not result.get("ok"):
            return _error(400, result.get("reason", "rename failed"))
        return result

    @_ng_app.post("/note/create")
    async def post_note_create(req: Request):
        """Create an empty note under an item's ``notes/`` directory."""
        data = await req.json()
        result = legacy.create_note(
            str(data.get("item_readme") or ""),
            str(data.get("filename") or ""),
        )
        if not result.get("ok"):
            return _error(400, result.get("reason", "create failed"))
        return result

    @_ng_app.get("/download/{rel_path:path}")
    def download(rel_path: str):
        full = legacy.validate_download_path(rel_path)
        if full is None:
            return Response(status_code=403)
        return Response(
            content=full.read_bytes(),
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{full.name}"'},
        )

    @_ng_app.get("/asset/{rel_path:path}")
    def asset(rel_path: str):
        result = legacy.validate_asset_path(rel_path)
        if result is None:
            return Response(status_code=403)
        full, ctype = result
        return Response(
            content=full.read_bytes(),
            media_type=ctype,
            headers={"Cache-Control": "public, max-age=300"},
        )

    @_ng_app.get("/file/{rel_path:path}")
    def get_file(rel_path: str):
        """Stream raw bytes for any file under the conception tree.

        Powers the in-modal preview for PDFs and images, and the
        "Open externally" fallback path handoff. Narrower than a generic
        static mount: paths are re-validated against conception-tree
        regexes on every call.
        """
        result = legacy.validate_file_path(rel_path)
        if result is None:
            return Response(status_code=403)
        full, ctype = result
        return Response(
            content=full.read_bytes(),
            media_type=ctype,
            headers={"Cache-Control": "private, max-age=60"},
        )

    @_ng_app.post("/toggle")
    async def toggle(req: Request):
        data = await req.json()
        full = legacy._validate_path(data.get("file", ""))
        if not full:
            return _error(400, "invalid path")
        status = legacy._toggle_checkbox(full, data.get("line", -1))
        if status is None:
            return _error(400, "not a checkbox line")
        return {"ok": True, "status": status}

    @_ng_app.post("/remove-step")
    async def remove_step(req: Request):
        data = await req.json()
        full = legacy._validate_path(data.get("file", ""))
        if not full:
            return _error(400, "invalid path")
        if legacy._remove_step(full, data.get("line", -1)):
            return {"ok": True}
        return _error(400, "cannot remove")

    @_ng_app.post("/edit-step")
    async def edit_step(req: Request):
        data = await req.json()
        text = (data.get("text") or "").strip()
        if not text:
            return _error(400, "empty text")
        full = legacy._validate_path(data.get("file", ""))
        if not full:
            return _error(400, "invalid path")
        if legacy._edit_step(full, data.get("line", -1), text):
            return {"ok": True}
        return _error(400, "cannot edit")

    @_ng_app.post("/add-step")
    async def add_step(req: Request):
        data = await req.json()
        text = (data.get("text") or "").strip()
        if not text:
            return _error(400, "empty text")
        full = legacy._validate_path(data.get("file", ""))
        if not full:
            return _error(400, "invalid path")
        line = legacy._add_step(full, text, data.get("section"))
        return {"ok": True, "line": line}

    @_ng_app.post("/set-priority")
    async def set_priority(req: Request):
        data = await req.json()
        full = legacy._validate_path(data.get("file", ""))
        if not full:
            return _error(400, "invalid path")
        priority = data.get("priority", "")
        if legacy._set_priority(full, priority):
            moves = legacy._tidy()
            return {"ok": True, "priority": priority, "moved": bool(moves)}
        return _error(400, "invalid priority")

    @_ng_app.post("/reorder-all")
    async def reorder_all(req: Request):
        data = await req.json()
        full = legacy._validate_path(data.get("file", ""))
        if not full:
            return _error(400, "invalid path")
        order = data.get("order") or []
        if legacy._reorder_all(full, order):
            return {"ok": True}
        return _error(400, "cannot reorder")

    @_ng_app.get("/clipboard")
    def clipboard_read():
        """Server-side clipboard read for the embedded terminal.

        pywebview's Qt webview doesn't grant ``navigator.clipboard.readText``
        access over localhost, and Qt often doesn't dispatch ``paste``
        events to the xterm textarea. So the client falls back to this
        endpoint, which reads the system clipboard via ``QClipboard``
        (always available when condash runs in native Qt mode) then
        tries wl-paste / xclip / xsel subprocesses.
        """
        return Response(
            content=_clipboard_read(),
            media_type="text/plain; charset=utf-8",
            headers={"Cache-Control": "no-store"},
        )

    @_ng_app.post("/clipboard")
    async def clipboard_write(req: Request):
        """Server-side clipboard write — Ctrl+C copy from terminal."""
        body = await req.body()
        text = body.decode("utf-8", errors="replace")
        ok = _clipboard_write(text)
        return {"ok": bool(ok)}

    @_ng_app.post("/open")
    async def open_path(req: Request):
        data = await req.json()
        resolved = legacy._validate_open_path(data.get("path", ""))
        if not resolved:
            return _error(400, "invalid path")
        tool = data.get("tool", "")
        if legacy._open_path(tool, resolved):
            return {"ok": True}
        return _error(500, f"could not launch {tool}")

    @_ng_app.post("/open-doc")
    async def open_doc(req: Request):
        """Hand a conception-tree file to the OS default viewer.

        Accepts a path relative to ``conception_path``; rejects anything that
        resolves outside of it. Used by note-body links so that PDFs, images,
        and other non-markdown files open in the user's native viewer instead
        of the dashboard's webview.
        """
        data = await req.json()
        resolved = legacy._validate_doc_path(data.get("path", ""))
        if not resolved:
            return _error(400, "invalid path")
        if legacy._os_open(resolved):
            return {"ok": True}
        return _error(500, "could not launch system opener")

    @_ng_app.post("/open-external")
    async def open_external(req: Request):
        """Open an http(s) URL in the user's default browser."""
        data = await req.json()
        url = str(data.get("url") or "").strip()
        if not legacy._is_external_url(url):
            return _error(400, "invalid url")
        if legacy._open_external(url):
            return {"ok": True}
        return _error(500, "could not launch browser")

    @_ng_app.post("/tidy")
    async def tidy(_req: Request):
        moves = legacy._tidy()
        return {
            "ok": True,
            "moves": [{"from": f, "to": t} for f, t in moves],
        }

    @_ng_app.get("/config")
    def get_config():
        cfg = _RUNTIME_CFG
        if cfg is None:
            return _error(500, "config not initialised")
        return _config_to_payload(cfg)

    @_ng_app.post("/config")
    async def post_config(req: Request):
        global _RUNTIME_CFG
        if _RUNTIME_CFG is None:
            return _error(500, "config not initialised")
        data = await req.json()
        try:
            new_cfg = _payload_to_config(data)
        except (ValueError, KeyError, TypeError) as exc:
            return _error(400, f"invalid config: {exc}")
        config_mod.save(new_cfg)
        # Re-init module-level state so paths / repos / open-with changes
        # take effect on the next request without needing a process restart.
        legacy.init(new_cfg)
        # Surface which fields require a restart to actually take effect.
        restart_required = []
        old = _RUNTIME_CFG
        if old.port != new_cfg.port:
            restart_required.append("port")
        if old.native != new_cfg.native:
            restart_required.append("native")
        _RUNTIME_CFG = new_cfg
        return {
            "ok": True,
            "restart_required": restart_required,
            "config": _config_to_payload(new_cfg),
        }

    @_ng_app.websocket("/ws/term")
    async def terminal_ws(ws: WebSocket):
        """Back the bottom-pane terminal with a real pty.

        Spawns the user's shell inside a pty, bridges raw bytes both ways
        over the WebSocket, and relays TIOCSWINSZ on resize control
        frames. Linux + macOS only (Windows would need ConPTY).
        """
        await ws.accept()
        if sys.platform not in ("linux", "darwin"):
            await ws.send_text(
                json.dumps({"type": "error", "message": "Terminal only supported on Linux/macOS."})
            )
            await ws.close()
            return
        await _run_pty_session(ws)


async def _run_pty_session(ws: WebSocket) -> None:
    """Fork a shell inside a pty and bridge it to ``ws`` until disconnect.

    Binary frames carry raw bytes in both directions. Text frames are JSON
    control messages; only ``{"type": "resize", "cols": N, "rows": M}`` is
    handled today.

    The child process starts cwd'd at ``conception_path`` (else ``$HOME``),
    inherits the environment, and is launched with ``-l`` so the login
    rc-files (`~/.bash_profile`, `~/.zprofile`, …) run as the user would
    expect. On disconnect the child is terminated and reaped.
    """
    import fcntl
    import pty
    import struct
    import termios

    shell = (
        _resolve_terminal_shell(_RUNTIME_CFG)
        if _RUNTIME_CFG is not None
        else os.environ.get("SHELL") or "/bin/bash"
    )
    cwd = str(legacy.BASE_DIR) if legacy.BASE_DIR.is_dir() else os.path.expanduser("~")
    # Announce the resolved shell + cwd so the term header can surface them.
    try:
        await ws.send_text(json.dumps({"type": "info", "shell": shell, "cwd": cwd}))
    except Exception:
        return

    pid, fd = pty.fork()
    if pid == 0:
        # Child: cwd, env, then exec. os._exit on failure so we don't run
        # parent-only asyncio finally clauses.
        try:
            os.chdir(cwd)
        except OSError:
            pass
        os.environ["TERM"] = "xterm-256color"
        try:
            os.execvp(shell, [shell, "-l"])
        except OSError:
            os._exit(127)

    # Parent: wire the pty fd into the asyncio event loop.
    fl = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)

    loop = asyncio.get_running_loop()
    out_queue: asyncio.Queue[bytes | None] = asyncio.Queue()

    def _on_readable() -> None:
        try:
            data = os.read(fd, 4096)
        except BlockingIOError:
            return
        except OSError:
            data = b""
        if not data:
            out_queue.put_nowait(None)
            try:
                loop.remove_reader(fd)
            except Exception:
                pass
            return
        out_queue.put_nowait(data)

    loop.add_reader(fd, _on_readable)

    async def pump_to_ws() -> None:
        while True:
            data = await out_queue.get()
            if data is None:
                break
            try:
                await ws.send_bytes(data)
            except Exception:
                break

    pump = asyncio.create_task(pump_to_ws())

    try:
        while True:
            # Race ws.receive against the pump task: if pump finishes,
            # the pty has EOF'd (shell exited) and we push an exit frame
            # so the client can close its tab instead of waiting.
            receive_task = asyncio.ensure_future(ws.receive())
            done, _ = await asyncio.wait(
                {receive_task, pump},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if pump in done:
                receive_task.cancel()
                try:
                    await receive_task
                except (asyncio.CancelledError, WebSocketDisconnect, Exception):
                    pass
                try:
                    await ws.send_text(json.dumps({"type": "exit"}))
                except Exception:
                    pass
                break
            try:
                msg = receive_task.result()
            except WebSocketDisconnect:
                break
            mtype = msg.get("type")
            if mtype == "websocket.disconnect":
                break
            if msg.get("bytes"):
                try:
                    os.write(fd, msg["bytes"])
                except OSError:
                    break
                continue
            text = msg.get("text")
            if not text:
                continue
            try:
                obj = json.loads(text)
            except ValueError:
                continue
            if obj.get("type") == "resize":
                cols = max(2, int(obj.get("cols") or 80))
                rows = max(2, int(obj.get("rows") or 24))
                try:
                    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
                except OSError:
                    pass
    finally:
        try:
            loop.remove_reader(fd)
        except Exception:
            pass
        pump.cancel()
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            pass
        try:
            await ws.close()
        except Exception:
            pass


def _repo_entries(names: list[str], submodules: dict[str, list[str]]) -> list[dict]:
    """Shape a repo-name list for the /config JSON payload: one object per
    repo with its submodule paths attached.
    """
    return [{"name": name, "submodules": list(submodules.get(name) or [])} for name in names]


def _config_to_payload(cfg: CondashConfig) -> dict:
    """Serialise the live config to JSON for ``GET /config``."""
    return {
        "conception_path": str(cfg.conception_path) if cfg.conception_path else "",
        "workspace_path": str(cfg.workspace_path) if cfg.workspace_path else "",
        "worktrees_path": str(cfg.worktrees_path) if cfg.worktrees_path else "",
        "port": int(cfg.port),
        "native": bool(cfg.native),
        "repositories_primary": _repo_entries(cfg.repositories_primary, cfg.repo_submodules),
        "repositories_secondary": _repo_entries(cfg.repositories_secondary, cfg.repo_submodules),
        "terminal": {
            "shell": cfg.terminal.shell or "",
            "shortcut": cfg.terminal.shortcut,
            "resolved_shell": _resolve_terminal_shell(cfg),
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


def _resolve_terminal_shell(cfg: CondashConfig) -> str:
    """Single source of truth for which shell the pty actually launches.

    Priority: explicit ``terminal.shell`` config → ``$SHELL`` env → /bin/bash.
    """
    if cfg.terminal.shell:
        return cfg.terminal.shell
    return os.environ.get("SHELL") or "/bin/bash"


class ClipboardBridge:
    """pywebview JS→Python bridge for clipboard access.

    Exposed on ``window.pywebview.api`` via ``js_api`` in native mode.
    Each method is invoked on pywebview's main thread (the same thread
    that owns the QApplication) so ``QClipboard`` is safe to touch —
    unlike the FastAPI worker thread where ``QGuiApplication.instance()``
    returns None or Qt warns about cross-thread GUI access.

    Method names are intentionally short: the JS side calls
    ``window.pywebview.api.clipboard_get()`` / ``clipboard_set(text)``.
    """

    def clipboard_get(self) -> str:
        return _clipboard_read()

    def clipboard_set(self, text: str) -> bool:
        return _clipboard_write(text or "")


def _qt_clipboard():
    """Return the running QClipboard, or None if Qt isn't initialised.

    condash runs inside pywebview's Qt backend when ``native=true`` (the
    default) so a QGuiApplication is live and ``clipboard()`` just works.
    Browser mode has no Qt — the subprocess fallbacks take over.
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
    except Exception:
        return None


def _clipboard_read() -> str:
    import subprocess as _sp

    cb = _qt_clipboard()
    if cb is not None:
        try:
            return cb.text() or ""
        except Exception:
            pass
    for argv in (
        ["wl-paste", "--no-newline"],
        ["xclip", "-selection", "clipboard", "-o"],
        ["xsel", "--clipboard", "--output"],
    ):
        try:
            out = _sp.run(argv, capture_output=True, timeout=2)
        except FileNotFoundError:
            continue
        except Exception:
            continue
        if out.returncode == 0:
            return out.stdout.decode("utf-8", errors="replace")
    return ""


def _clipboard_write(text: str) -> bool:
    import subprocess as _sp

    cb = _qt_clipboard()
    if cb is not None:
        try:
            cb.setText(text)
            return True
        except Exception:
            pass
    for argv in (
        ["wl-copy"],
        ["xclip", "-selection", "clipboard", "-i"],
        ["xsel", "--clipboard", "--input"],
    ):
        try:
            proc = _sp.Popen(argv, stdin=_sp.PIPE)
        except FileNotFoundError:
            continue
        except Exception:
            continue
        try:
            proc.communicate(text.encode("utf-8"), timeout=2)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
            continue
        if proc.returncode == 0:
            return True
    return False


def _parse_repo_entries(raw: object, key: str) -> tuple[list[str], dict[str, list[str]]]:
    """Parse a `repositories_primary` / `_secondary` payload entry.

    Accepts either a list of strings (legacy) or a list of
    ``{name, submodules}`` objects. Returns the ordered name list plus a
    submodule map keyed by name.
    """
    if raw is None:
        return [], {}
    if not isinstance(raw, list):
        raise ValueError(f"{key} must be a list")
    names: list[str] = []
    subs: dict[str, list[str]] = {}
    for entry in raw:
        if isinstance(entry, str):
            name = entry.strip()
            if name:
                names.append(name)
        elif isinstance(entry, dict):
            name = str(entry.get("name") or "").strip()
            if not name:
                continue
            sub_raw = entry.get("submodules") or []
            if not isinstance(sub_raw, list):
                raise ValueError(f"{key}[].submodules must be a list")
            cleaned = [str(s).strip() for s in sub_raw if str(s).strip()]
            names.append(name)
            if cleaned:
                subs[name] = cleaned
        else:
            raise ValueError(f"{key} entries must be strings or objects")
    return names, subs


def _payload_to_config(data: dict) -> CondashConfig:
    """Build a validated CondashConfig from the in-app editor's JSON payload."""
    if not isinstance(data, dict):
        raise ValueError("payload must be an object")
    conception_raw = (data.get("conception_path") or "").strip()
    conception = Path(conception_raw).expanduser() if conception_raw else None

    workspace_raw = (data.get("workspace_path") or "").strip()
    workspace = Path(workspace_raw).expanduser() if workspace_raw else None
    worktrees_raw = (data.get("worktrees_path") or "").strip()
    worktrees = Path(worktrees_raw).expanduser() if worktrees_raw else None

    port_raw = data.get("port", 0)
    if isinstance(port_raw, str):
        port_raw = int(port_raw or 0)
    if not isinstance(port_raw, int) or not 0 <= port_raw <= 65535:
        raise ValueError("port must be an integer between 0 and 65535")

    native_raw = data.get("native", True)
    if not isinstance(native_raw, bool):
        raise ValueError("native must be a boolean")

    primary, primary_subs = _parse_repo_entries(
        data.get("repositories_primary"), "repositories_primary"
    )
    secondary, secondary_subs = _parse_repo_entries(
        data.get("repositories_secondary"), "repositories_secondary"
    )
    repo_submodules: dict[str, list[str]] = {**primary_subs, **secondary_subs}

    open_with_raw = data.get("open_with") or {}
    if not isinstance(open_with_raw, dict):
        raise ValueError("open_with must be an object")
    open_with: dict[str, OpenWithSlot] = {}
    for slot_key in OPEN_WITH_SLOT_KEYS:
        defaults = config_mod.DEFAULT_OPEN_WITH[slot_key]
        slot_data = open_with_raw.get(slot_key) or {}
        if not isinstance(slot_data, dict):
            raise ValueError(f"open_with.{slot_key} must be an object")
        label = str(slot_data.get("label") or defaults["label"])
        commands_raw = slot_data.get("commands")
        if commands_raw is None:
            commands = list(defaults["commands"])
        elif isinstance(commands_raw, list):
            commands = [str(c) for c in commands_raw if str(c).strip()]
        else:
            raise ValueError(f"open_with.{slot_key}.commands must be a list")
        open_with[slot_key] = OpenWithSlot(label=label, commands=commands)

    term_raw = data.get("terminal") or {}
    if not isinstance(term_raw, dict):
        raise ValueError("terminal must be an object")
    shell_in = str(term_raw.get("shell") or "").strip() or None
    shortcut_in = (
        str(term_raw.get("shortcut") or "").strip() or config_mod.DEFAULT_TERMINAL_SHORTCUT
    )
    terminal = config_mod.TerminalConfig(shell=shell_in, shortcut=shortcut_in)

    return CondashConfig(
        conception_path=conception,
        workspace_path=workspace,
        worktrees_path=worktrees,
        repositories_primary=primary,
        repositories_secondary=secondary,
        repo_submodules=repo_submodules,
        terminal=terminal,
        port=port_raw,
        native=native_raw,
        open_with=open_with,
    )


def run(cfg: CondashConfig) -> None:
    """Launch the condash dashboard (native window or browser, per config)."""
    global _RUNTIME_CFG
    _RUNTIME_CFG = cfg
    legacy.init(cfg)
    _register_routes()
    kwargs: dict = {
        "native": cfg.native,
        "title": "Conception Dashboard",
        "reload": False,
        "show": not cfg.native,
        "port": cfg.port,
    }
    if cfg.native:
        kwargs["window_size"] = (1400, 900)
        # Force the Qt backend so we don't print a noisy GTK traceback on
        # systems missing python3-gi. PyQt6 is a hard runtime dependency
        # (pywebview[qt] in pyproject), so this is always available.
        _ng_app.native.start_args["gui"] = "qt"
        # Expose a Python→JS clipboard bridge. pywebview invokes js_api
        # methods on its main Qt thread, so QClipboard works without
        # tripping navigator.clipboard's permission callback (which
        # crashes on PyQt6 6.x — see qt.py::onFeaturePermissionRequested).
        _ng_app.native.window_args["js_api"] = ClipboardBridge()
        # Set the window icon so the OS task switcher shows it. pywebview 6.x
        # exposes `icon` on webview.start() (i.e. start_args), NOT on
        # create_window() — passing it via window_args raises TypeError on
        # launch.
        _ng_app.native.start_args["icon"] = icon_path()
        # Advertise the Qt desktop identity before pywebview creates the
        # QApplication, so the Wayland app_id matches condash.desktop and
        # GNOME/KDE task switchers can resolve the bundled icon.
        _set_qt_desktop_identity()
        # NiceGUI's check_shutdown thread sometimes fails to actually stop
        # uvicorn after the user closes the window — leaving the port bound
        # for the next launch. Force-exit the whole process when the
        # native window emits its `closed` event.
        _ng_app.native.on("closed", lambda: os._exit(0))
    ui.run(**kwargs)
