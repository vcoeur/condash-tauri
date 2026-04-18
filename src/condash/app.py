"""NiceGUI-backed native window for condash.

The existing ``dashboard.html`` is served verbatim at ``/``; all the AJAX
endpoints the JS calls (``/toggle``, ``/add-step``, …) are re-implemented
here as FastAPI routes on top of NiceGUI's underlying FastAPI instance.
"""

from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import os
import secrets
import signal
import socket
import struct
import sys
import termios
from dataclasses import dataclass, field
from importlib.resources import files as _package_files
from pathlib import Path

from fastapi import Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, Response
from nicegui import app as _ng_app
from nicegui import ui

from . import config as config_mod
from .config import (
    OPEN_WITH_SLOT_KEYS,
    SCREENSHOT_IMAGE_EXTENSIONS,
    CondashConfig,
    OpenWithSlot,
)
from .context import RenderCtx, build_ctx, favicon_bytes
from .git_scan import _git_fingerprint, compute_git_node_fingerprints
from .mutations import (
    _add_step,
    _edit_step,
    _remove_step,
    _reorder_all,
    _set_priority,
    _toggle_checkbox,
    create_note,
    create_notes_subdir,
    read_note_raw,
    rename_note,
    store_uploads,
    write_note,
)
from .openers import _is_external_url, _open_external, _open_path, _os_open
from .parser import (
    _compute_fingerprint,
    _note_kind,
    collect_items,
    collect_knowledge,
    compute_knowledge_node_fingerprints,
    compute_project_node_fingerprints,
    find_knowledge_card,
    find_knowledge_node,
)
from .paths import (
    _validate_doc_path,
    _validate_item_dir,
    _validate_open_path,
    _validate_path,
    validate_asset_path,
    validate_download_path,
    validate_file_path,
    validate_note_path,
)
from .render import (
    _render_note,
    render_card_fragment,
    render_knowledge_card_fragment,
    render_knowledge_group_fragment,
    render_page,
)

log = logging.getLogger(__name__)

# Holds the live runtime config and derived RenderCtx so the in-app editor
# can mutate both after a successful POST /config without forcing a
# process restart. Initialized by `run` before NiceGUI starts.
_RUNTIME_CFG: CondashConfig | None = None
_RUNTIME_CTX: RenderCtx | None = None


def _ctx() -> RenderCtx:
    """Return the live RenderCtx or raise if uninitialised."""
    if _RUNTIME_CTX is None:
        raise RuntimeError("condash.app: _RUNTIME_CTX not initialised")
    return _RUNTIME_CTX


# --- Pty session registry --------------------------------------------------
#
# The old code bound a pty's lifetime 1:1 to its WebSocket: the `finally`
# block in the WS handler SIGTERM'd the child whenever the socket
# disconnected, so any page refresh killed every open shell. We now keep
# ptys in a process-wide registry keyed by an opaque session_id; the
# WebSocket attaches/detaches without touching the child. A ring buffer per
# session preserves the last _PTY_BUFFER_CAP bytes of output so a reattach
# can replay recent scrollback immediately.

# Ring-buffer cap. 256 KiB fits a few screens of scrollback per tab; beyond
# that we trim from the head. Bound so a detached tab that produces fast
# output can't grow memory unboundedly.
_PTY_BUFFER_CAP = 256 * 1024


@dataclass
class PtySession:
    """Server-side pty + its ring buffer. Decoupled from any WebSocket."""

    session_id: str
    pid: int
    fd: int
    shell: str
    cwd: str
    cols: int = 80
    rows: int = 24
    buffer: bytearray = field(default_factory=bytearray)
    out_queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    attached_ws: WebSocket | None = None
    pump_task: asyncio.Task | None = None


_PTY_SESSIONS: dict[str, PtySession] = {}


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

    _ng_app.on_shutdown(_reap_all_pty_sessions)

    @_ng_app.get("/", response_class=HTMLResponse)
    def index():
        items = collect_items(_ctx())
        return HTMLResponse(content=render_page(_ctx(), items))

    @_ng_app.get("/favicon.svg")
    def favicon_svg():
        data = favicon_bytes()
        if data is None:
            return Response(status_code=404)
        return Response(
            content=data,
            media_type="image/svg+xml",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    @_ng_app.get("/favicon.ico")
    def favicon_ico():
        data = favicon_bytes()
        if data is None:
            return Response(status_code=404)
        return Response(content=data, media_type="image/svg+xml")

    @_ng_app.get("/check-updates")
    def check_updates():
        ctx = _ctx()
        items = collect_items(ctx)
        knowledge = collect_knowledge(ctx)
        nodes: dict[str, str] = {}
        nodes.update(compute_project_node_fingerprints(items))
        nodes.update(compute_knowledge_node_fingerprints(knowledge))
        nodes.update(compute_git_node_fingerprints(ctx))
        return {
            "fingerprint": _compute_fingerprint(items),
            "git_fingerprint": _git_fingerprint(ctx),
            "nodes": nodes,
        }

    @_ng_app.get("/fragment", response_class=HTMLResponse)
    def fragment(id: str = ""):
        """Return the HTML subtree for a single card or knowledge directory.

        Supported id shapes:
          - ``projects/<priority>/<slug>`` — one project card.
          - ``knowledge/<rel>`` — one knowledge card (if ``<rel>`` is a file)
            or one directory subtree (if ``<rel>`` is a knowledge directory).
        Anything else (group, tab, code node) returns 404; the client falls
        back to a global in-place reload for those.
        """
        ctx = _ctx()
        if not id:
            return _error(400, "missing id")
        if id.startswith("projects/"):
            parts = id.split("/", 2)
            if len(parts) != 3:
                return _error(404, "not a card id")
            slug = parts[2]
            for item in collect_items(ctx):
                if item["slug"] == slug:
                    return HTMLResponse(content=render_card_fragment(item))
            return _error(404, "card not found")
        if id == "knowledge":
            # Root pane uses a different wrapper than a subdirectory group;
            # falling back to global reload is simpler than special-casing it.
            return _error(404, "use global reload")
        if id.startswith("knowledge/"):
            tree = collect_knowledge(ctx)
            # File cards have an extension (e.g. ".md"); directories do not.
            if id.endswith(".md"):
                card = find_knowledge_card(tree, id)
                if card is None:
                    return _error(404, "card not found")
                return HTMLResponse(content=render_knowledge_card_fragment(card))
            node = find_knowledge_node(tree, id)
            if node is None:
                return _error(404, "dir not found")
            return HTMLResponse(content=render_knowledge_group_fragment(node))
        return _error(404, "unsupported id")

    @_ng_app.get("/note")
    def get_note(path: str = ""):
        full = validate_note_path(_ctx(), path)
        if full is None:
            return Response(status_code=403)
        return HTMLResponse(content=_render_note(_ctx(), full))

    @_ng_app.get("/note-raw")
    def get_note_raw(path: str = ""):
        """Return plain-text content + mtime for the in-modal edit mode."""
        full = validate_note_path(_ctx(), path)
        if full is None:
            return _error(403, "invalid path")
        kind = _note_kind(full)
        if kind not in ("md", "text"):
            return _error(400, f"not editable ({kind})")
        return read_note_raw(_ctx(), full)

    @_ng_app.post("/note")
    async def post_note(req: Request):
        """Atomically overwrite a note file with the editor's content."""
        data = await req.json()
        full = validate_note_path(_ctx(), str(data.get("path") or ""))
        if full is None:
            return _error(403, "invalid path")
        if _note_kind(full) not in ("md", "text"):
            return _error(400, "not editable")
        content = data.get("content")
        if not isinstance(content, str):
            return _error(400, "content must be a string")
        result = write_note(full, content, data.get("expected_mtime"))
        if not result.get("ok"):
            return JSONResponse(status_code=409, content=result)
        return result

    @_ng_app.post("/note/rename")
    async def post_note_rename(req: Request):
        """Rename a file under ``<item>/notes/`` preserving the extension."""
        data = await req.json()
        result = rename_note(
            _ctx(),
            str(data.get("path") or ""),
            str(data.get("new_stem") or ""),
        )
        if not result.get("ok"):
            return _error(400, result.get("reason", "rename failed"))
        return result

    @_ng_app.post("/note/create")
    async def post_note_create(req: Request):
        """Create an empty note under ``<item>/notes[/subdir]/``."""
        data = await req.json()
        result = create_note(
            _ctx(),
            str(data.get("item_readme") or ""),
            str(data.get("filename") or ""),
            subdir=str(data.get("subdir") or ""),
        )
        if not result.get("ok"):
            return _error(400, result.get("reason", "create failed"))
        return result

    @_ng_app.post("/note/mkdir")
    async def post_note_mkdir(req: Request):
        """Create a (possibly nested) directory under ``<item>/notes/``."""
        data = await req.json()
        result = create_notes_subdir(
            _ctx(),
            str(data.get("item_readme") or ""),
            str(data.get("subpath") or ""),
        )
        if not result.get("ok"):
            status = 409 if result.get("reason") == "exists" else 400
            return JSONResponse(status_code=status, content=result)
        return result

    @_ng_app.post("/note/upload")
    async def post_note_upload(req: Request):
        """Persist files uploaded via ``multipart/form-data`` under
        ``<item>/notes[/subdir]/``. Auto-suffixes ``(2)``, ``(3)``… on
        name collision; rejects > 50 MB per file. Streams to disk so a
        large upload doesn't sit in RAM."""
        form = await req.form()
        item_readme = str(form.get("item_readme") or "")
        subdir = str(form.get("subdir") or "")
        uploads: list[tuple[str, object]] = []
        for key in form.keys():
            if key != "file":
                continue
            for entry in form.getlist(key):
                # Starlette gives UploadFile for files, str for plain
                # fields — skip anything that's not a file.
                if hasattr(entry, "file") and hasattr(entry, "filename"):
                    uploads.append((entry.filename, entry.file))
        if not uploads:
            return _error(400, "no files in upload")
        result = store_uploads(_ctx(), item_readme, subdir, uploads)
        if not result.get("ok"):
            return _error(400, result.get("reason", "upload failed"))
        return result

    @_ng_app.get("/download/{rel_path:path}")
    def download(rel_path: str):
        full = validate_download_path(_ctx(), rel_path)
        if full is None:
            return Response(status_code=403)
        return Response(
            content=full.read_bytes(),
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{full.name}"'},
        )

    @_ng_app.get("/asset/{rel_path:path}")
    def asset(rel_path: str):
        result = validate_asset_path(_ctx(), rel_path)
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
        result = validate_file_path(_ctx(), rel_path)
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
        full = _validate_path(_ctx(), data.get("file", ""))
        if not full:
            return _error(400, "invalid path")
        status = _toggle_checkbox(full, data.get("line", -1))
        if status is None:
            return _error(400, "not a checkbox line")
        return {"ok": True, "status": status}

    @_ng_app.post("/remove-step")
    async def remove_step(req: Request):
        data = await req.json()
        full = _validate_path(_ctx(), data.get("file", ""))
        if not full:
            return _error(400, "invalid path")
        if _remove_step(full, data.get("line", -1)):
            return {"ok": True}
        return _error(400, "cannot remove")

    @_ng_app.post("/edit-step")
    async def edit_step(req: Request):
        data = await req.json()
        text = (data.get("text") or "").strip()
        if not text:
            return _error(400, "empty text")
        full = _validate_path(_ctx(), data.get("file", ""))
        if not full:
            return _error(400, "invalid path")
        if _edit_step(full, data.get("line", -1), text):
            return {"ok": True}
        return _error(400, "cannot edit")

    @_ng_app.post("/add-step")
    async def add_step(req: Request):
        data = await req.json()
        text = (data.get("text") or "").strip()
        if not text:
            return _error(400, "empty text")
        full = _validate_path(_ctx(), data.get("file", ""))
        if not full:
            return _error(400, "invalid path")
        line = _add_step(full, text, data.get("section"))
        return {"ok": True, "line": line}

    @_ng_app.post("/set-priority")
    async def set_priority(req: Request):
        data = await req.json()
        full = _validate_path(_ctx(), data.get("file", ""))
        if not full:
            return _error(400, "invalid path")
        priority = data.get("priority", "")
        if _set_priority(full, priority):
            return {"ok": True, "priority": priority}
        return _error(400, "invalid priority")

    @_ng_app.post("/reorder-all")
    async def reorder_all(req: Request):
        data = await req.json()
        full = _validate_path(_ctx(), data.get("file", ""))
        if not full:
            return _error(400, "invalid path")
        order = data.get("order") or []
        if _reorder_all(full, order):
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
        resolved = _validate_open_path(_ctx(), data.get("path", ""))
        if not resolved:
            return _error(400, "invalid path")
        tool = data.get("tool", "")
        if _open_path(_ctx(), tool, resolved):
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
        resolved = _validate_doc_path(_ctx(), data.get("path", ""))
        if not resolved:
            return _error(400, "invalid path")
        if _os_open(_ctx(), resolved):
            return {"ok": True}
        return _error(500, "could not launch system opener")

    @_ng_app.post("/open-folder")
    async def open_folder(req: Request):
        """Hand a project-item folder to the OS default file manager.

        Accepts a path relative to ``conception_path`` matching the
        ``projects/YYYY-MM/YYYY-MM-DD-slug/`` shape; rejects anything else.
        """
        data = await req.json()
        resolved = _validate_item_dir(_ctx(), data.get("path", ""))
        if not resolved:
            return _error(400, "invalid path")
        if _os_open(_ctx(), resolved):
            return {"ok": True}
        return _error(500, "could not launch system opener")

    @_ng_app.post("/open-external")
    async def open_external(req: Request):
        """Open an http(s) URL in the user's default browser."""
        data = await req.json()
        url = str(data.get("url") or "").strip()
        if not _is_external_url(url):
            return _error(400, "invalid url")
        if _open_external(url):
            return {"ok": True}
        return _error(500, "could not launch browser")

    @_ng_app.get("/recent-screenshot")
    def recent_screenshot():
        """Return the absolute path of the newest image in the screenshot dir.

        Used by the screenshot-paste shortcut to inject a path into the
        active terminal tab without an extra clipboard hop. The directory
        comes from ``terminal.screenshot_dir`` (or the OS-appropriate
        default); only files with an image extension we recognise are
        considered, and "newest" is by file mtime.

        Returns ``{path: <abs>, dir: <abs>}`` on success or ``{path: null,
        dir: <abs>, reason: <message>}`` when the directory is missing,
        unreadable, or empty.
        """
        cfg = _RUNTIME_CFG
        if cfg is None:
            return _error(500, "config not initialised")
        directory = cfg.terminal.resolved_screenshot_dir()
        payload = {"path": None, "dir": str(directory), "reason": ""}
        if not directory.exists():
            payload["reason"] = "directory does not exist"
            return payload
        if not directory.is_dir():
            payload["reason"] = "configured path is not a directory"
            return payload
        try:
            entries = list(directory.iterdir())
        except PermissionError:
            payload["reason"] = "permission denied"
            return payload
        candidates: list[tuple[float, Path]] = []
        for entry in entries:
            if not entry.is_file():
                continue
            if entry.suffix.lower() not in SCREENSHOT_IMAGE_EXTENSIONS:
                continue
            try:
                mtime = entry.stat().st_mtime
            except OSError:
                continue
            candidates.append((mtime, entry))
        if not candidates:
            payload["reason"] = "no image files found"
            return payload
        candidates.sort(key=lambda pair: pair[0], reverse=True)
        payload["path"] = str(candidates[0][1])
        return payload

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
        # Rebuild the RenderCtx so paths / repos / open-with changes
        # take effect on the next request without needing a process restart.
        global _RUNTIME_CTX
        _RUNTIME_CTX = build_ctx(new_cfg)
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
        """View a pty session over a WebSocket.

        If the URL carries ``?session_id=<id>`` and that session exists, the
        client is attaching to an existing pty (typical after a page
        refresh). Otherwise we spawn a fresh pty and tell the client its
        new session id in the first ``info`` frame. Disconnection only
        detaches the view — the pty keeps running and buffering output.

        Linux + macOS only (Windows would need ConPTY).
        """
        await ws.accept()
        if sys.platform not in ("linux", "darwin"):
            await ws.send_text(
                json.dumps({"type": "error", "message": "Terminal only supported on Linux/macOS."})
            )
            await ws.close()
            return

        requested_id = ws.query_params.get("session_id") or None
        session = _PTY_SESSIONS.get(requested_id) if requested_id else None

        if requested_id and session is None:
            # Reattach to an unknown session — almost always "condash was
            # restarted, the pty is long gone". Tell the client so it can
            # drop the stale id from its localStorage instead of silently
            # starting a new shell under the same tab.
            try:
                await ws.send_text(
                    json.dumps({"type": "session-expired", "session_id": requested_id})
                )
            except (WebSocketDisconnect, RuntimeError, OSError):
                pass
            try:
                await ws.close()
            except (WebSocketDisconnect, RuntimeError, OSError):
                pass
            return

        # If another tab is already viewing this session (e.g. two copies
        # of the dashboard pointing at the same pty), boot the old viewer.
        # The pty itself keeps running — only the displaced viewer's ws is
        # closed.
        if session is not None and session.attached_ws is not None:
            old = session.attached_ws
            session.attached_ws = None
            try:
                await old.close()
            except (WebSocketDisconnect, RuntimeError, OSError):
                pass

        if session is None:
            requested_cwd = ws.query_params.get("cwd") or None
            override_cwd: str | None = None
            if requested_cwd:
                validated = _validate_open_path(_ctx(), requested_cwd)
                if validated is not None:
                    override_cwd = str(validated)
                else:
                    log.warning("term: rejecting out-of-sandbox cwd: %r", requested_cwd)
            use_launcher = ws.query_params.get("launcher") == "1"
            session = await _spawn_pty_session(override_cwd=override_cwd, use_launcher=use_launcher)
            if session is None:
                try:
                    await ws.close()
                except (WebSocketDisconnect, RuntimeError, OSError):
                    pass
                return

        session.attached_ws = ws
        try:
            await ws.send_text(
                json.dumps(
                    {
                        "type": "info",
                        "session_id": session.session_id,
                        "shell": session.shell,
                        "cwd": session.cwd,
                    }
                )
            )
        except (WebSocketDisconnect, RuntimeError, OSError):
            session.attached_ws = None
            return

        # Replay whatever the shell has emitted since the last viewer
        # detached. One binary frame so xterm sees it as one chunk (cheap
        # and fine for 256 KiB).
        if session.buffer:
            try:
                await ws.send_bytes(bytes(session.buffer))
            except (WebSocketDisconnect, RuntimeError, OSError):
                session.attached_ws = None
                return

        await _attach_ws(session, ws)


async def _spawn_pty_session(
    override_cwd: str | None = None, use_launcher: bool = False
) -> PtySession | None:
    """Fork a new shell in a pty, register it, and start its reader pump.

    The child starts cwd'd at ``override_cwd`` (when supplied and the
    directory exists), else ``conception_path`` (else ``$HOME``) with
    ``TERM=xterm-256color`` and is launched with ``-l`` so login rc-files
    run. ``override_cwd`` must already be sandbox-validated by the caller
    — this function trusts it and does not re-check. The pty's lifetime
    is independent of any WebSocket; the reader pump keeps draining
    ``fd`` into ``session.buffer`` (and to ``session.attached_ws`` if one
    is bound) until the shell exits.

    When ``use_launcher`` is set, the child execs ``terminal.launcher_command``
    (shlex-parsed) directly instead of a login shell. ``session.shell`` is
    reported as the launcher's argv[0] so the client-side chip label still
    has something meaningful. When the process exits the ws closes and the
    tab disappears — matching what happens when the user types ``exit`` in
    a regular shell.
    """
    import pty
    import shlex

    argv: list[str]
    shell_label: str
    if use_launcher:
        raw_command = (
            _RUNTIME_CFG.terminal.launcher_command
            if _RUNTIME_CFG is not None and _RUNTIME_CFG.terminal.launcher_command
            else ""
        )
        if not raw_command.strip():
            log.warning("term: launcher requested but terminal.launcher_command is empty")
            return None
        try:
            argv = shlex.split(raw_command)
        except ValueError as exc:
            log.warning("term: malformed launcher_command %r: %s", raw_command, exc)
            return None
        if not argv:
            return None
        shell_label = argv[0]
    else:
        shell_label = (
            _resolve_terminal_shell(_RUNTIME_CFG)
            if _RUNTIME_CFG is not None
            else os.environ.get("SHELL") or "/bin/bash"
        )
        argv = [shell_label, "-l"]

    if override_cwd and os.path.isdir(override_cwd):
        cwd = override_cwd
    else:
        cwd = str(_ctx().base_dir) if _ctx().base_dir.is_dir() else os.path.expanduser("~")

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
            os.execvp(argv[0], argv)
        except OSError:
            os._exit(127)

    # Parent: wire the pty fd into the asyncio event loop.
    fl = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)

    session = PtySession(
        session_id=secrets.token_urlsafe(8),
        pid=pid,
        fd=fd,
        shell=shell_label,
        cwd=cwd,
    )

    loop = asyncio.get_running_loop()

    def _on_readable() -> None:
        try:
            data = os.read(fd, 65536)
        except BlockingIOError:
            return
        except OSError:
            data = b""
        if not data:
            session.out_queue.put_nowait(None)
            try:
                loop.remove_reader(fd)
            except (OSError, ValueError):
                pass
            return
        session.out_queue.put_nowait(data)

    loop.add_reader(fd, _on_readable)
    session.pump_task = asyncio.create_task(_pump_session(session))
    _PTY_SESSIONS[session.session_id] = session
    return session


async def _pump_session(session: PtySession) -> None:
    """Drain the pty's read queue into the ring buffer + any attached ws.

    Runs for the pty's entire lifetime. On EOF (shell exited) unregisters
    the session, sends an ``exit`` frame to whoever was viewing, and
    reaps the child.

    Coalesces any chunks already sitting in the queue into one ws frame
    before awaiting the socket. A large paste floods the pty with echo
    output; ``os.read(fd, 4096)`` reads those in 4 KiB chunks but our
    reader callback loops the queue up fast, so by the time we ``await``
    on ``out_queue.get()`` there are often several pending chunks. Sending
    one frame per chunk forces the client to render (and xterm to parse)
    in 4 KiB increments; coalescing cuts frame count ~10× for the common
    case and makes large paste echo feel instant.
    """
    while True:
        data = await session.out_queue.get()
        if data is None:
            # EOF — shell exited. Tear the session down.
            _PTY_SESSIONS.pop(session.session_id, None)
            ws = session.attached_ws
            session.attached_ws = None
            if ws is not None:
                try:
                    await ws.send_text(json.dumps({"type": "exit"}))
                except (WebSocketDisconnect, RuntimeError, OSError):
                    pass
                try:
                    await ws.close()
                except (WebSocketDisconnect, RuntimeError, OSError):
                    pass
            try:
                os.close(session.fd)
            except OSError:
                pass
            try:
                os.waitpid(session.pid, os.WNOHANG)
            except ChildProcessError:
                pass
            return

        chunks = [data]
        eof_pending = False
        while not session.out_queue.empty():
            try:
                extra = session.out_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if extra is None:
                eof_pending = True
                break
            chunks.append(extra)
        data = b"".join(chunks) if len(chunks) > 1 else chunks[0]

        # Append to ring buffer, trimming the head once we overshoot the
        # cap. `del buffer[:n]` on a bytearray is O(n) but cheap at these
        # sizes (256 KiB) and only runs when the buffer is actually full.
        session.buffer.extend(data)
        overflow = len(session.buffer) - _PTY_BUFFER_CAP
        if overflow > 0:
            del session.buffer[:overflow]

        ws = session.attached_ws
        if ws is not None:
            try:
                await ws.send_bytes(data)
            except (WebSocketDisconnect, RuntimeError, OSError):
                # Viewer went away (e.g. F5). Detach so the next attach
                # replays from the buffer; keep pty running.
                if session.attached_ws is ws:
                    session.attached_ws = None

        if eof_pending:
            session.out_queue.put_nowait(None)


async def _pty_write_all(fd: int, data: bytes) -> bool:
    """Write ``data`` to ``fd`` in full, yielding on EAGAIN.

    The pty master is non-blocking (``O_NONBLOCK``), so a single
    ``os.write`` can return fewer bytes than requested — or raise
    ``BlockingIOError`` once the kernel's tty buffer fills up. That's what
    happens on a large paste: the shell drains the buffer far slower than
    a WebSocket frame can deliver, so the first ``os.write`` ships ~64 KiB
    and the rest would be silently dropped or (worse) would surface as an
    ``OSError`` that tore the ws down. Here we loop, registering a writer
    callback on EAGAIN so the event loop wakes us when the fd is writable
    again. Returns ``True`` on success, ``False`` if the fd went bad.
    """
    loop = asyncio.get_running_loop()
    view = memoryview(data)
    while view:
        try:
            written = os.write(fd, view)
        except BlockingIOError:
            fut: asyncio.Future[None] = loop.create_future()

            def _signal() -> None:
                if not fut.done():
                    fut.set_result(None)

            try:
                loop.add_writer(fd, _signal)
            except (OSError, ValueError):
                return False
            try:
                await fut
            finally:
                try:
                    loop.remove_writer(fd)
                except (OSError, ValueError):
                    pass
            continue
        except OSError:
            return False
        if written <= 0:
            # Shouldn't happen on a healthy fd, but guard against an
            # infinite loop if the kernel ever returns 0.
            return False
        view = view[written:]
    return True


async def _attach_ws(session: PtySession, ws: WebSocket) -> None:
    """Run the receive loop for a ws that is viewing ``session``.

    Input bytes are written to the pty; resize frames relay TIOCSWINSZ.
    On disconnect we only clear ``attached_ws`` — the pty keeps running,
    output keeps going into the ring buffer, ready for the next attach.
    """
    try:
        while True:
            try:
                msg = await ws.receive()
            except WebSocketDisconnect:
                break
            mtype = msg.get("type")
            if mtype == "websocket.disconnect":
                break
            if msg.get("bytes"):
                ok = await _pty_write_all(session.fd, msg["bytes"])
                if not ok:
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
                session.cols, session.rows = cols, rows
                try:
                    fcntl.ioctl(
                        session.fd,
                        termios.TIOCSWINSZ,
                        struct.pack("HHHH", rows, cols, 0, 0),
                    )
                except OSError:
                    pass
    except (WebSocketDisconnect, RuntimeError, OSError) as exc:
        log.debug("attach_ws: receive loop ended: %s", exc)
    finally:
        # Detach only — pty stays alive for the next reconnect.
        if session.attached_ws is ws:
            session.attached_ws = None


def _reap_all_pty_sessions() -> None:
    """SIGTERM every live pty. Called on server shutdown."""
    for session in list(_PTY_SESSIONS.values()):
        try:
            os.kill(session.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except OSError:
            pass
    _PTY_SESSIONS.clear()


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
            "screenshot_dir": cfg.terminal.screenshot_dir or "",
            "resolved_screenshot_dir": str(cfg.terminal.resolved_screenshot_dir()),
            "screenshot_paste_shortcut": cfg.terminal.screenshot_paste_shortcut,
            "launcher_command": cfg.terminal.launcher_command,
            "move_tab_left_shortcut": cfg.terminal.move_tab_left_shortcut,
            "move_tab_right_shortcut": cfg.terminal.move_tab_right_shortcut,
        },
        "open_with": {
            slot_key: {
                "label": cfg.open_with[slot_key].label,
                "commands": list(cfg.open_with[slot_key].commands),
            }
            for slot_key in OPEN_WITH_SLOT_KEYS
            if slot_key in cfg.open_with
        },
        "pdf_viewer": list(cfg.pdf_viewer),
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
    except (RuntimeError, AttributeError):
        return None


def _clipboard_read() -> str:
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


def _clipboard_write(text: str) -> bool:
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

    pdf_viewer_raw = data.get("pdf_viewer", [])
    if pdf_viewer_raw is None:
        pdf_viewer: list[str] = []
    elif isinstance(pdf_viewer_raw, list):
        pdf_viewer = [str(c).strip() for c in pdf_viewer_raw if str(c).strip()]
    else:
        raise ValueError("pdf_viewer must be a list of command strings")

    term_raw = data.get("terminal") or {}
    if not isinstance(term_raw, dict):
        raise ValueError("terminal must be an object")
    shell_in = str(term_raw.get("shell") or "").strip() or None
    shortcut_in = (
        str(term_raw.get("shortcut") or "").strip() or config_mod.DEFAULT_TERMINAL_SHORTCUT
    )
    screenshot_dir_in = str(term_raw.get("screenshot_dir") or "").strip() or None
    paste_shortcut_in = (
        str(term_raw.get("screenshot_paste_shortcut") or "").strip()
        or config_mod.DEFAULT_SCREENSHOT_PASTE_SHORTCUT
    )
    launcher_command_in = str(term_raw.get("launcher_command", config_mod.DEFAULT_LAUNCHER_COMMAND))
    move_left_in = (
        str(term_raw.get("move_tab_left_shortcut") or "").strip()
        or config_mod.DEFAULT_MOVE_TAB_LEFT_SHORTCUT
    )
    move_right_in = (
        str(term_raw.get("move_tab_right_shortcut") or "").strip()
        or config_mod.DEFAULT_MOVE_TAB_RIGHT_SHORTCUT
    )
    terminal = config_mod.TerminalConfig(
        shell=shell_in,
        shortcut=shortcut_in,
        screenshot_dir=screenshot_dir_in,
        screenshot_paste_shortcut=paste_shortcut_in,
        launcher_command=launcher_command_in.strip(),
        move_tab_left_shortcut=move_left_in,
        move_tab_right_shortcut=move_right_in,
    )

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
        pdf_viewer=pdf_viewer,
    )


# NiceGUI's own find_open_port scans 8000-8999, which regularly collides
# with Django/uvicorn/http.server defaults. Scan a less-contested window
# instead. 11111-12111 is in the IANA registered range but near-empty in
# practice; memcached (11211) and OpenPGP HKP (11371) are skipped
# naturally by the bind-and-try.
_FREE_PORT_RANGE = (11111, 12111)


def _pick_free_port() -> int:
    """Return a free TCP port in ``_FREE_PORT_RANGE`` (inclusive)."""
    start, end = _FREE_PORT_RANGE
    for port in range(start, end + 1):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind(("localhost", port))
                return port
        except OSError:
            continue
    raise OSError(f"No open port found in {start}-{end}")


def run(cfg: CondashConfig) -> None:
    """Launch the condash dashboard (native window or browser, per config)."""
    global _RUNTIME_CFG, _RUNTIME_CTX
    _RUNTIME_CFG = cfg
    _RUNTIME_CTX = build_ctx(cfg)
    _register_routes()
    port = _pick_free_port() if cfg.port == 0 else cfg.port
    kwargs: dict = {
        "native": cfg.native,
        "title": "Conception Dashboard",
        "reload": False,
        "show": not cfg.native,
        "port": port,
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
