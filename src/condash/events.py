"""Filesystem-driven staleness push.

Phase 6 of the update-view overhaul replaces the 5-second polling loop
with a watchdog observer + a server-sent-events channel.

The backend emits coarse tab-level events (``projects`` / ``knowledge``
/ ``code``) whenever a watched path changes. The frontend listens via
``EventSource('/events')`` and, on receipt, calls ``/check-updates`` to
compute the precise per-node dirty set. This keeps the event-id scheme
simple (three constants) while preserving the fingerprint pipeline as
an authoritative reconciler — any event the watcher misses shows up on
the next reconnect pass.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

if TYPE_CHECKING:
    from .context import RenderCtx

logger = logging.getLogger(__name__)

# Drop duplicate events within this window — filesystem churn (save +
# editor swap file + metadata touch) can otherwise fire three events
# for one logical change.
_DEBOUNCE_SECONDS = 0.3


class EventBus:
    """Thread-safe fan-out from watchdog's worker thread to asyncio subs.

    The ``Observer`` delivers events on its own thread; SSE consumers
    live on the asyncio event loop. ``publish_threadsafe`` bridges the
    two via ``loop.call_soon_threadsafe``, so handler threads never
    touch asyncio primitives directly.
    """

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue] = []
        self._lock = Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        with self._lock:
            self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        with self._lock:
            try:
                self._subscribers.remove(queue)
            except ValueError:
                pass

    def publish_threadsafe(self, payload: dict) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        loop.call_soon_threadsafe(self._fanout, payload)

    def _fanout(self, payload: dict) -> None:
        with self._lock:
            subs = list(self._subscribers)
        for queue in subs:
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                # Drop the oldest — the reconciler catches whatever is
                # missed on the next `/check-updates` call.
                try:
                    queue.get_nowait()
                    queue.put_nowait(payload)
                except Exception:
                    pass


class _DebouncedHandler(FileSystemEventHandler):
    """Emit ``{"tab": <tab>}`` on any change, debounced per tab."""

    def __init__(self, bus: EventBus, tab: str) -> None:
        self._bus = bus
        self._tab = tab
        self._last_emit = 0.0

    def on_any_event(self, event) -> None:
        # Swap files, backups, hidden state — ignore anything whose
        # leaf starts with '.' or ends with '~'. Git has its own handler.
        src = getattr(event, "src_path", "") or ""
        leaf = Path(src).name
        if leaf.startswith(".") or leaf.endswith("~"):
            return
        now = time.time()
        if now - self._last_emit < _DEBOUNCE_SECONDS:
            return
        self._last_emit = now
        self._bus.publish_threadsafe({"tab": self._tab, "ts": now})


class _GitHandler(FileSystemEventHandler):
    """Emit ``code`` events when a repo's HEAD or index file changes."""

    _WATCHED = frozenset({"HEAD", "index", "packed-refs"})

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._last_emit = 0.0

    def on_any_event(self, event) -> None:
        leaf = Path(getattr(event, "src_path", "") or "").name
        if leaf not in self._WATCHED:
            return
        now = time.time()
        if now - self._last_emit < _DEBOUNCE_SECONDS:
            return
        self._last_emit = now
        self._bus.publish_threadsafe({"tab": "code", "ts": now})


def _git_dirs_under(workspace: Path | None) -> list[Path]:
    """Find every ``.git`` directory one level below ``workspace``."""
    if workspace is None or not workspace.is_dir():
        return []
    out = []
    for entry in workspace.iterdir():
        if not entry.is_dir():
            continue
        gitdir = entry / ".git"
        # Worktrees point .git at a file — we skip those and rely on the
        # observer watching the parent .git directory directly.
        if gitdir.is_dir():
            out.append(gitdir)
    return out


def start_watcher(ctx: RenderCtx, bus: EventBus) -> Observer | None:
    """Spin up the watchdog observer against the ctx's conception paths.

    Returns the live ``Observer`` (call ``.stop() + .join()`` on shutdown)
    or ``None`` when the context has no usable base directory.
    """
    if not ctx.base_dir.exists() or not ctx.base_dir.is_dir():
        return None
    observer = Observer()

    projects = ctx.base_dir / "projects"
    if projects.is_dir():
        observer.schedule(_DebouncedHandler(bus, "projects"), str(projects), recursive=True)

    knowledge = ctx.base_dir / "knowledge"
    if knowledge.is_dir():
        observer.schedule(_DebouncedHandler(bus, "knowledge"), str(knowledge), recursive=True)

    for gitdir in _git_dirs_under(ctx.workspace):
        observer.schedule(_GitHandler(bus), str(gitdir), recursive=False)
    if ctx.worktrees and ctx.worktrees.is_dir():
        for branch_dir in ctx.worktrees.iterdir():
            if not branch_dir.is_dir():
                continue
            for gitdir in _git_dirs_under(branch_dir):
                observer.schedule(_GitHandler(bus), str(gitdir), recursive=False)

    observer.daemon = True
    observer.start()
    return observer
