"""Filesystem-driven staleness push.

Phase 6 of the update-view overhaul replaces the 5-second polling loop
with a watchdog observer + a server-sent-events channel.

The backend emits coarse tab-level events (``projects`` / ``knowledge``
/ ``code`` / ``config``) whenever a watched path changes. The frontend
listens via ``EventSource('/events')`` and, on receipt, calls
``/check-updates`` (for content tabs) or refetches ``/config`` (for
config-tab events). The event-id scheme stays simple while the
fingerprint pipeline acts as authoritative reconciler — any event the
watcher misses shows up on the next reconnect pass.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
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
_DEBOUNCE_SECONDS = 0.75


class EventBus:
    """Thread-safe fan-out from watchdog's worker thread to asyncio subs.

    The ``Observer`` delivers events on its own thread; SSE consumers
    live on the asyncio event loop. ``publish_threadsafe`` bridges the
    two via ``loop.call_soon_threadsafe``, so handler threads never
    touch asyncio primitives directly.
    """

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue] = []
        self._sync_subscribers: list[Callable[[dict], None]] = []
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

    def subscribe_sync(self, callback: Callable[[dict], None]) -> None:
        """Register a synchronous callback invoked on every published event.

        Sync subscribers run inline on the event loop thread (inside
        ``_fanout``) before the asyncio queues are filled, so a cache
        invalidator can flip cached state *before* SSE clients see the
        event and re-poll ``/check-updates``.
        """
        with self._lock:
            self._sync_subscribers.append(callback)

    def publish_threadsafe(self, payload: dict) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        loop.call_soon_threadsafe(self._fanout, payload)

    def _fanout(self, payload: dict) -> None:
        with self._lock:
            subs = list(self._subscribers)
            sync_subs = list(self._sync_subscribers)
        for callback in sync_subs:
            try:
                callback(payload)
            except Exception:
                logger.exception("EventBus: sync subscriber raised")
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


class _ConfigHandler(FileSystemEventHandler):
    """Emit ``config`` events on changes to the two YAML config files.

    Only reacts to ``repositories.yml`` / ``preferences.yml`` — anything
    else under ``<conception>/config/`` (scratch files, editor backups)
    is ignored. Only write-style events trigger reload — open and
    close-no-write events are dropped so an open for reading (e.g. the
    dashboard's own ``GET /config`` path) never kicks off a reload
    cycle. Before fanning out to SSE clients the handler invokes
    ``on_reload`` (via ``loop.call_soon_threadsafe``) so the server can
    rebuild its runtime config atomically on the event loop thread
    rather than on watchdog's worker thread.

    Debouncing is per-file: a burst of events for ``repositories.yml``
    doesn't swallow a concurrent edit of ``preferences.yml``. The
    window is short (0.3 s) — just enough to collapse the three-event
    storm a single atomic write produces on Linux.
    """

    _WATCHED = frozenset({"repositories.yml", "preferences.yml"})
    _WRITE_EVENTS = frozenset({"modified", "created", "moved", "closed"})
    _DEBOUNCE = 0.3

    def __init__(
        self,
        bus: EventBus,
        on_reload: Callable[[str], None] | None = None,
    ) -> None:
        self._bus = bus
        self._on_reload = on_reload
        self._last_emit: dict[str, float] = {}

    def on_any_event(self, event) -> None:
        leaf = Path(getattr(event, "src_path", "") or "").name
        if leaf not in self._WATCHED:
            return
        if event.event_type not in self._WRITE_EVENTS:
            return
        now = time.time()
        if now - self._last_emit.get(leaf, 0.0) < self._DEBOUNCE:
            return
        self._last_emit[leaf] = now
        logger.info("_ConfigHandler: firing reload for %s (%s)", leaf, event.event_type)
        if self._on_reload is not None:
            loop = self._bus._loop  # noqa: SLF001 — deliberate bridge
            if loop is not None and not loop.is_closed():
                loop.call_soon_threadsafe(self._on_reload, leaf)
            else:
                logger.warning("_ConfigHandler: event loop not bound; reload skipped")
        self._bus.publish_threadsafe({"tab": "config", "file": leaf, "ts": now})


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


def start_watcher(
    ctx: RenderCtx,
    bus: EventBus,
    on_config_reload: Callable[[str], None] | None = None,
) -> Observer | None:
    """Spin up the watchdog observer against the ctx's conception paths.

    ``on_config_reload`` runs on the asyncio event loop whenever one of
    the watched YAML config files changes — the server uses it to rebuild
    the live :class:`CondashConfig` and :class:`RenderCtx` before the SSE
    fanout notifies browsers. Pass ``None`` to only push events.

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

    config_dir = ctx.base_dir / "config"
    if config_dir.is_dir():
        observer.schedule(
            _ConfigHandler(bus, on_reload=on_config_reload),
            str(config_dir),
            recursive=False,
        )

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
