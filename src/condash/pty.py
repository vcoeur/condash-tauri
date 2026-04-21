"""PTY session lifecycle for the embedded terminal.

A PTY's lifetime is decoupled from any single WebSocket: a tab refresh
should detach the viewer without killing the shell. Each session lives in
the per-process registry on :attr:`AppState.pty_sessions`, keyed by an
opaque session id; the WebSocket attaches and detaches via
:func:`attach_ws`, while :func:`pump_session` keeps draining the master fd
into a per-session ring buffer (and the live viewer when one is attached).

The shutdown path (:func:`reap_all`) sends SIGTERM to every live shell so
``ui.run`` can exit cleanly without orphaning ports.
"""

from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import os
import secrets
import signal
import struct
import sys
import termios
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from fastapi import WebSocket, WebSocketDisconnect

if TYPE_CHECKING:
    from .config import CondashConfig
    from .state import AppState

log = logging.getLogger(__name__)

# Ring-buffer cap. 256 KiB fits a few screens of scrollback per tab; beyond
# that we trim from the head. Bound so a detached tab that produces fast
# output can't grow memory unboundedly.
_BUFFER_CAP = 256 * 1024


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


def resolve_terminal_shell(cfg: CondashConfig) -> str:
    """Single source of truth for which shell the pty actually launches.

    Priority: explicit ``terminal.shell`` config → ``$SHELL`` env → /bin/bash.
    """
    if cfg.terminal.shell:
        return cfg.terminal.shell
    return os.environ.get("SHELL") or "/bin/bash"


async def spawn_session(
    state: AppState,
    *,
    override_cwd: str | None = None,
    use_launcher: bool = False,
) -> PtySession | None:
    """Fork a new shell in a pty, register it on ``state``, and start its pump.

    Child starts cwd'd at ``override_cwd`` (when supplied and the directory
    exists), else ``conception_path`` (else ``$HOME``) with ``TERM=
    xterm-256color`` and ``-l`` so login rc-files run. ``override_cwd``
    must already be sandbox-validated by the caller — this function trusts
    it and does not re-check.

    When ``use_launcher`` is set, the child execs
    ``terminal.launcher_command`` (shlex-parsed) directly instead of a
    login shell. ``session.shell`` is reported as the launcher's argv[0]
    so the client-side chip label still has something meaningful. When
    that process exits the ws closes and the tab disappears — matching
    what happens when the user types ``exit`` in a regular shell.
    """
    import pty
    import shlex

    cfg = state.cfg
    argv: list[str]
    shell_label: str
    if use_launcher:
        raw_command = cfg.terminal.launcher_command if cfg is not None else ""
        if not raw_command or not raw_command.strip():
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
            resolve_terminal_shell(cfg)
            if cfg is not None
            else os.environ.get("SHELL") or "/bin/bash"
        )
        argv = [shell_label, "-l"]

    ctx = state.get_ctx()
    if override_cwd and os.path.isdir(override_cwd):
        cwd = override_cwd
    else:
        cwd = str(ctx.base_dir) if ctx.base_dir.is_dir() else os.path.expanduser("~")

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
    session.pump_task = asyncio.create_task(pump_session(state, session))
    state.pty_sessions[session.session_id] = session
    return session


async def pump_session(state: AppState, session: PtySession) -> None:
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
            state.pty_sessions.pop(session.session_id, None)
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
        overflow = len(session.buffer) - _BUFFER_CAP
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


async def write_all(fd: int, data: bytes) -> bool:
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


async def attach_ws(session: PtySession, ws: WebSocket) -> None:
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
                ok = await write_all(session.fd, msg["bytes"])
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


def reap_all(state: AppState) -> None:
    """SIGTERM every live pty. Called on server shutdown."""
    for session in list(state.pty_sessions.values()):
        try:
            os.kill(session.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except OSError:
            pass
    state.pty_sessions.clear()


def supports_pty() -> bool:
    """``pty.fork`` works on Linux + macOS only (Windows would need ConPTY)."""
    return sys.platform in ("linux", "darwin")
