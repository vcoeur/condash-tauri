"""Embedded-terminal WebSocket — the dashboard's xterm.js tab pane.

Registers ``/ws/term`` directly on the FastAPI app (rather than via a
WebSocket-bearing :class:`APIRouter`) because NiceGUI's ``_ng_app``
subclass doesn't always pick up router-mounted WS handlers reliably,
and there's exactly one of them.

The PTY lifecycle helpers live in :mod:`condash.pty`; this file is the
thin glue between the WS receive loop and the per-process session
registry on :attr:`AppState.pty_sessions`.
"""

from __future__ import annotations

import json
import logging

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from .. import pty
from ..paths import _validate_open_path
from ..state import AppState

log = logging.getLogger(__name__)


def register(app: FastAPI, state: AppState) -> None:
    """Attach the ``/ws/term`` handler to ``app``."""

    @app.websocket("/ws/term")
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
        if not pty.supports_pty():
            await ws.send_text(
                json.dumps({"type": "error", "message": "Terminal only supported on Linux/macOS."})
            )
            await ws.close()
            return

        requested_id = ws.query_params.get("session_id") or None
        session = state.pty_sessions.get(requested_id) if requested_id else None

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
                validated = _validate_open_path(state.get_ctx(), requested_cwd)
                if validated is not None:
                    override_cwd = str(validated)
                else:
                    log.warning("term: rejecting out-of-sandbox cwd: %r", requested_cwd)
            use_launcher = ws.query_params.get("launcher") == "1"
            session = await pty.spawn_session(
                state, override_cwd=override_cwd, use_launcher=use_launcher
            )
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

        await pty.attach_ws(session, ws)
