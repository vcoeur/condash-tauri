"""Filesystem-walk memoization with event-driven invalidation.

Without a cache every request re-walks the conception tree: ``/`` +
``/check-updates`` + ``/fragment`` + ``/search-history`` all call
:func:`parser.collect_items` (which parses every ``README.md`` under
``projects/``) and :func:`parser.collect_knowledge` (which walks
``knowledge/`` recursively). Each ``[[wikilink]]`` inside a rendered note
re-walks ``projects/*/*``.

:class:`WorkspaceCache` memoizes the three hot paths — the parsed item
list, the knowledge tree, and the wikilink resolver — behind an
``RLock`` so reads on FastAPI worker threads are safe alongside
invalidations scheduled on the asyncio loop thread.

Invalidation is driven by :class:`events.EventBus` via
:meth:`on_event`: a ``projects`` event flushes items + wikilinks, a
``knowledge`` event flushes the knowledge tree + wikilinks. Coarse on
purpose — the ``/check-updates`` fingerprint pipeline already reconciles
anything the cache missed, and per-key invalidation would have to
re-parse watchdog paths the current handler already debounces away.
"""

from __future__ import annotations

import logging
from threading import RLock

from .context import RenderCtx
from .parser import collect_items, collect_knowledge
from .wikilinks import _resolve_wikilink_uncached

log = logging.getLogger(__name__)


class WorkspaceCache:
    """Memoize ``collect_items`` / ``collect_knowledge`` / wikilink resolution."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._items: list[dict] | None = None
        self._knowledge: dict | None = None
        self._knowledge_loaded = False
        self._wikilinks: dict[str, str | None] = {}

    def get_items(self, ctx: RenderCtx) -> list[dict]:
        """Return the memoized parsed-item list, warming on first access."""
        with self._lock:
            if self._items is None:
                self._items = collect_items(ctx)
            return self._items

    def get_knowledge(self, ctx: RenderCtx) -> dict | None:
        """Return the memoized knowledge tree, warming on first access.

        ``collect_knowledge`` legitimately returns ``None`` when the
        ``knowledge/`` directory is missing, so a separate ``_loaded``
        flag distinguishes "never warmed" from "warmed and empty".
        """
        with self._lock:
            if not self._knowledge_loaded:
                self._knowledge = collect_knowledge(ctx)
                self._knowledge_loaded = True
            return self._knowledge

    def resolve_wikilink(self, ctx: RenderCtx, target: str) -> str | None:
        """Return the memoized wikilink resolution for ``target``.

        The filesystem walk happens outside the lock — only dictionary
        mutation is guarded, so a slow walk on one target can't block
        reads for another.
        """
        with self._lock:
            if target in self._wikilinks:
                return self._wikilinks[target]
        resolved = _resolve_wikilink_uncached(ctx, target)
        with self._lock:
            self._wikilinks[target] = resolved
            return resolved

    def invalidate_items(self) -> None:
        with self._lock:
            self._items = None
            self._wikilinks.clear()

    def invalidate_knowledge(self) -> None:
        with self._lock:
            self._knowledge = None
            self._knowledge_loaded = False
            self._wikilinks.clear()

    def invalidate_all(self) -> None:
        """Flush every cached slice — used when ``ctx`` itself is swapped."""
        with self._lock:
            self._items = None
            self._knowledge = None
            self._knowledge_loaded = False
            self._wikilinks.clear()

    def on_event(self, payload: dict) -> None:
        """EventBus sync-subscriber hook — routes tab events to invalidators."""
        tab = payload.get("tab")
        if tab == "projects":
            self.invalidate_items()
        elif tab == "knowledge":
            self.invalidate_knowledge()
