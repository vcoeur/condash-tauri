"""Inline dev-server runner registry.

One PTY-backed session per repo (or sub-repo) key, keyed by
``"<repo>"`` for top-level entries and ``"<repo>--<sub>"`` for sub-repo
entries. The key is repo-scoped, not checkout-scoped: the main checkout
and every worktree share the same lock so only one dev server for a
given repo runs at a time. The registry tracks which *checkout* is
currently hosting it so the Code view can surface a jump-affordance on
the right row.

Sessions reuse the same ring-buffer + attached-websocket pattern as
``app.PtySession``, so the ``/ws/runner/<key>`` handler is a close
sibling of ``/ws/term``: attach/detach does not kill the child; EOF
drains the queue, records ``exit_code``, and holds the session in
``exited`` state until the user hits Stop (which removes it).
"""

from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import os
import signal
import struct
import termios
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import WebSocket

log = logging.getLogger(__name__)

_RUNNER_BUFFER_CAP = 256 * 1024


@dataclass
class RunnerSession:
    """One live (or recently exited) inline runner.

    Exactly one instance per ``key`` may live in ``_RUNNERS`` at a time.
    ``exit_code`` is ``None`` while the child runs; once EOF drains
    through the pump the session stays in the registry with its final
    exit code so the UI can show ``exited: N`` until the user clicks
    Stop.
    """

    key: str
    checkout_key: str
    path: str
    template: str
    shell: str
    pid: int
    fd: int
    started_at: float
    cols: int = 80
    rows: int = 24
    buffer: bytearray = field(default_factory=bytearray)
    out_queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    attached_ws: "WebSocket | None" = None
    pump_task: asyncio.Task | None = None
    exit_code: int | None = None
    stamp: int = 0


_RUNNERS: dict[str, RunnerSession] = {}
_STAMP_COUNTER = 0


def registry() -> dict[str, RunnerSession]:
    """Live map of runner-key → session. Exposed for render / fingerprint."""
    return _RUNNERS


def get(key: str) -> RunnerSession | None:
    return _RUNNERS.get(key)


def fingerprint_token(key: str) -> str:
    """Return a short token that changes whenever the session's visible
    state changes (start / exit / new instance after stop).

    Used by the repo-strip fingerprint to trigger a partial refresh.
    """
    session = _RUNNERS.get(key)
    if session is None:
        return "off"
    if session.exit_code is not None:
        return f"exit:{session.stamp}:{session.exit_code}"
    return f"run:{session.stamp}:{session.checkout_key}"


def _next_stamp() -> int:
    global _STAMP_COUNTER
    _STAMP_COUNTER += 1
    return _STAMP_COUNTER


async def start(
    key: str,
    checkout_key: str,
    path: str,
    template: str,
    shell: str,
) -> RunnerSession:
    """Fork ``shell -lc <resolved-template>`` in ``path``, register it.

    Raises ``RuntimeError`` if a live (non-exited) session already owns
    ``key`` — callers must stop it first.
    """
    import pty

    existing = _RUNNERS.get(key)
    if existing is not None and existing.exit_code is None:
        raise RuntimeError(f"runner already active for {key}")
    if existing is not None:
        # Exited session being replaced — drop it.
        _detach_exited(existing)

    resolved = template.replace("{path}", path)
    argv = [shell, "-lc", resolved]
    pid, fd = pty.fork()
    if pid == 0:
        try:
            os.chdir(path)
        except OSError:
            pass
        os.environ["TERM"] = "xterm-256color"
        try:
            os.execvp(argv[0], argv)
        except OSError:
            os._exit(127)

    fl = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)

    session = RunnerSession(
        key=key,
        checkout_key=checkout_key,
        path=path,
        template=template,
        shell=shell,
        pid=pid,
        fd=fd,
        started_at=time.time(),
        stamp=_next_stamp(),
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
    session.pump_task = asyncio.create_task(_pump(session))
    _RUNNERS[key] = session
    return session


async def stop(key: str, grace: float = 5.0) -> None:
    """SIGTERM the child, wait briefly, then SIGKILL if it's still alive.

    After the child reaps, the session is removed from the registry. If
    the key is not live, this is a no-op.
    """
    session = _RUNNERS.get(key)
    if session is None:
        return
    if session.exit_code is not None:
        _detach_exited(session)
        return
    try:
        os.kill(session.pid, signal.SIGTERM)
    except ProcessLookupError:
        _detach_exited(session)
        return
    except OSError as exc:
        log.warning("runner stop: SIGTERM %s failed: %s", session.pid, exc)
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        if session.exit_code is not None or _RUNNERS.get(key) is not session:
            return
        await asyncio.sleep(0.1)
    try:
        os.kill(session.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except OSError as exc:
        log.warning("runner stop: SIGKILL %s failed: %s", session.pid, exc)
    # Let the pump notice EOF and clear the session.
    await asyncio.sleep(0.1)
    if _RUNNERS.get(key) is session and session.exit_code is None:
        # Pump didn't fire (e.g. race); force-detach so UI stops lying.
        session.exit_code = -int(signal.SIGKILL)
        _detach_exited(session)


def reap_all() -> None:
    """SIGTERM every live runner. Called from the FastAPI shutdown hook.

    Synchronous — callers that need hard SIGKILL follow-up should run
    a short asyncio drain afterwards.
    """
    for session in list(_RUNNERS.values()):
        if session.exit_code is not None:
            continue
        try:
            os.kill(session.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except OSError as exc:
            log.debug("runner reap: SIGTERM %s failed: %s", session.pid, exc)


def _detach_exited(session: RunnerSession) -> None:
    """Drop an already-exited session from the registry."""
    if _RUNNERS.get(session.key) is session:
        _RUNNERS.pop(session.key, None)
    try:
        os.close(session.fd)
    except OSError:
        pass


async def _pump(session: RunnerSession) -> None:
    """Drain the pty's read queue into the ring buffer + attached ws.

    Mirrors ``app._pump_session`` but marks the session as ``exited``
    (keeping it in the registry) instead of popping it on EOF — the UI
    wants to display ``exited: N`` until the user hits Stop.
    """
    from fastapi import WebSocketDisconnect  # late import — test envs don't load FastAPI eagerly

    while True:
        data = await session.out_queue.get()
        if data is None:
            try:
                _, status = os.waitpid(session.pid, os.WNOHANG)
            except ChildProcessError:
                status = 0
            if os.WIFEXITED(status):
                session.exit_code = os.WEXITSTATUS(status)
            elif os.WIFSIGNALED(status):
                session.exit_code = -os.WTERMSIG(status)
            else:
                session.exit_code = 0
            session.stamp = _next_stamp()
            ws = session.attached_ws
            session.attached_ws = None
            if ws is not None:
                try:
                    await ws.send_text(
                        json.dumps({"type": "exit", "exit_code": session.exit_code})
                    )
                except (WebSocketDisconnect, RuntimeError, OSError):
                    pass
            # Keep the session record around for UI display; _detach_exited
            # is called by stop() or when a fresh start() replaces it.
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

        session.buffer.extend(data)
        overflow = len(session.buffer) - _RUNNER_BUFFER_CAP
        if overflow > 0:
            del session.buffer[:overflow]

        ws = session.attached_ws
        if ws is not None:
            try:
                await ws.send_bytes(data)
            except (WebSocketDisconnect, RuntimeError, OSError):
                if session.attached_ws is ws:
                    session.attached_ws = None

        if eof_pending:
            session.out_queue.put_nowait(None)


def resize(session: RunnerSession, cols: int, rows: int) -> None:
    """Relay a TIOCSWINSZ to the runner's PTY master fd."""
    session.cols, session.rows = cols, rows
    try:
        fcntl.ioctl(
            session.fd,
            termios.TIOCSWINSZ,
            struct.pack("HHHH", rows, cols, 0, 0),
        )
    except OSError:
        pass


async def write_input(session: RunnerSession, data: bytes) -> bool:
    """Write user input to the runner's PTY master fd.

    Non-blocking write loop identical to ``app._pty_write_all``. Returns
    True on success, False if the fd went bad.
    """
    loop = asyncio.get_running_loop()
    view = memoryview(data)
    while view:
        try:
            written = os.write(session.fd, view)
        except BlockingIOError:
            fut: asyncio.Future[None] = loop.create_future()

            def _signal() -> None:
                if not fut.done():
                    fut.set_result(None)

            try:
                loop.add_writer(session.fd, _signal)
            except (OSError, ValueError):
                return False
            try:
                await fut
            finally:
                try:
                    loop.remove_writer(session.fd)
                except (OSError, ValueError):
                    pass
            continue
        except OSError:
            return False
        if written <= 0:
            return False
        view = view[written:]
    return True


def clear_exited(key: str) -> bool:
    """If ``key`` is in exited state, drop it. Returns True when cleared."""
    session = _RUNNERS.get(key)
    if session is None or session.exit_code is None:
        return False
    _detach_exited(session)
    return True
