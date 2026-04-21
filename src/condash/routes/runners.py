"""Inline dev-server runner routes (start / stop / WebSocket attach).

The runner registry lives in :mod:`condash.runners`; these handlers are
the HTTP / WS surface that the Code-tab "Run" buttons drive. The PTY
attach loop is shared with the embedded terminal — see
:func:`condash.runners.attach_runner_ws` for the receive loop.
"""

from __future__ import annotations

import json
import logging
import sys

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from .. import runners as runners_mod
from ..paths import _validate_open_path
from ..pty import resolve_terminal_shell
from ..state import AppState
from ._common import error

log = logging.getLogger(__name__)


async def _attach_runner_ws(session, ws: WebSocket) -> None:
    """Receive loop for a ws viewing a :class:`runners.RunnerSession`.

    Same shape as :func:`condash.pty.attach_ws` — input bytes go to the
    PTY, resize frames relay TIOCSWINSZ — but backed by
    ``runners.RunnerSession`` instead of ``PtySession``. Disconnect only
    detaches; the child keeps running (or stays in exited state) until
    the user hits Stop.
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
                if session.exit_code is not None:
                    continue  # No pty to write to — swallow post-exit typing.
                ok = await runners_mod.write_input(session, msg["bytes"])
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
                if session.exit_code is None:
                    runners_mod.resize(session, cols, rows)
                else:
                    session.cols, session.rows = cols, rows
    except (WebSocketDisconnect, RuntimeError, OSError) as exc:
        log.debug("attach_runner_ws: receive loop ended: %s", exc)
    finally:
        if session.attached_ws is ws:
            session.attached_ws = None


def build_router(state: AppState) -> APIRouter:
    router = APIRouter()

    @router.post("/api/runner/start")
    async def runner_start(req: Request):
        """Spawn a dev-server runner for ``{key, checkout_key, path}``.

        409 if a non-exited runner already owns the key — the UI shows
        a confirm dialog and re-issues start after stop.
        """
        try:
            data = await req.json()
        except ValueError:
            return error(400, "bad JSON")
        if not isinstance(data, dict):
            return error(400, "payload must be an object")
        key = str(data.get("key") or "").strip()
        checkout_key = str(data.get("checkout_key") or "").strip()
        path_raw = str(data.get("path") or "").strip()
        if not key or not checkout_key or not path_raw:
            return error(400, "key, checkout_key, path required")
        if state.cfg is None:
            return error(500, "runtime config not initialised")
        cmd = state.cfg.repo_run.get(key)
        if cmd is None:
            return error(404, f"no run command configured for {key}")
        validated = _validate_open_path(state.get_ctx(), path_raw)
        if validated is None:
            return error(400, f"path out of sandbox: {path_raw}")
        existing = runners_mod.get(key)
        if existing is not None and existing.exit_code is None:
            return JSONResponse(
                status_code=409,
                content={
                    "error": "runner already active",
                    "key": key,
                    "checkout_key": existing.checkout_key,
                },
            )
        shell = resolve_terminal_shell(state.cfg)
        try:
            session = await runners_mod.start(
                key=key,
                checkout_key=checkout_key,
                path=str(validated),
                template=cmd.template,
                shell=shell,
            )
        except (OSError, RuntimeError) as exc:
            log.warning("runner start %s failed: %s", key, exc)
            return error(500, f"spawn failed: {exc}")
        return {
            "ok": True,
            "key": key,
            "checkout_key": session.checkout_key,
            "pid": session.pid,
            "template": session.template,
        }

    @router.post("/api/runner/stop")
    async def runner_stop(req: Request):
        """Stop the runner for ``{key}`` (SIGTERM + SIGKILL after grace)."""
        try:
            data = await req.json()
        except ValueError:
            return error(400, "bad JSON")
        if not isinstance(data, dict):
            return error(400, "payload must be an object")
        key = str(data.get("key") or "").strip()
        if not key:
            return error(400, "key required")
        session = runners_mod.get(key)
        if session is None:
            return {"ok": True, "cleared": False}
        if session.exit_code is not None:
            runners_mod.clear_exited(key)
            return {"ok": True, "cleared": True, "exited": True}
        await runners_mod.stop(key)
        runners_mod.clear_exited(key)
        return {"ok": True, "cleared": True}

    @router.websocket("/ws/runner/{key}")
    async def runner_ws(ws: WebSocket, key: str):
        """Attach a WebSocket to an existing runner's PTY stream."""
        await ws.accept()
        if sys.platform not in ("linux", "darwin"):
            try:
                await ws.send_text(
                    json.dumps(
                        {"type": "error", "message": "Runner only supported on Linux/macOS."}
                    )
                )
                await ws.close()
            except (WebSocketDisconnect, RuntimeError, OSError):
                pass
            return
        session = runners_mod.get(key)
        if session is None:
            try:
                await ws.send_text(json.dumps({"type": "session-missing", "key": key}))
                await ws.close()
            except (WebSocketDisconnect, RuntimeError, OSError):
                pass
            return
        # Displace any stale viewer — one attached ws per session.
        if session.attached_ws is not None:
            old = session.attached_ws
            session.attached_ws = None
            try:
                await old.close()
            except (WebSocketDisconnect, RuntimeError, OSError):
                pass
        session.attached_ws = ws
        try:
            await ws.send_text(
                json.dumps(
                    {
                        "type": "info",
                        "key": key,
                        "checkout_key": session.checkout_key,
                        "path": session.path,
                        "template": session.template,
                        "exit_code": session.exit_code,
                    }
                )
            )
        except (WebSocketDisconnect, RuntimeError, OSError):
            session.attached_ws = None
            return
        if session.buffer:
            try:
                await ws.send_bytes(bytes(session.buffer))
            except (WebSocketDisconnect, RuntimeError, OSError):
                session.attached_ws = None
                return
        if session.exit_code is not None:
            # Already dead — emit the exit frame so the client renders the
            # greyed status line, then stay attached for ring-buffer replay
            # until the client detaches.
            try:
                await ws.send_text(json.dumps({"type": "exit", "exit_code": session.exit_code}))
            except (WebSocketDisconnect, RuntimeError, OSError):
                session.attached_ws = None
                return
        await _attach_runner_ws(session, ws)

    return router
