"""Tests for WorkspaceCache — memoization + event-driven invalidation."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from condash import app as app_mod
from condash.cache import WorkspaceCache
from condash.config import CondashConfig
from condash.context import build_ctx
from condash.events import EventBus


def _seed_project(conception_root: Path, slug: str, status: str = "now") -> Path:
    date = "2026-01-01"
    project = conception_root / "projects" / "2026-01" / f"{date}-{slug}"
    project.mkdir(parents=True, exist_ok=True)
    (project / "README.md").write_text(
        f"# {slug}\n\n**Date**: {date}\n**Kind**: project\n"
        f"**Status**: {status}\n\n## Steps\n\n- [ ] task\n",
        encoding="utf-8",
    )
    return project


def test_get_items_warms_and_reuses(cfg: CondashConfig):
    cache = WorkspaceCache()
    ctx = build_ctx(cfg)
    first = cache.get_items(ctx)
    second = cache.get_items(ctx)
    # Same object — no re-walk.
    assert first is second


def test_get_items_ignores_fs_until_invalidated(cfg: CondashConfig, tmp_conception: Path):
    cache = WorkspaceCache()
    ctx = build_ctx(cfg)
    first = cache.get_items(ctx)
    assert len(first) == 1
    # Add a second project; cache must still return the old snapshot
    # because no invalidation event has fired.
    _seed_project(tmp_conception, "extra")
    assert cache.get_items(ctx) is first
    cache.invalidate_items()
    refreshed = cache.get_items(ctx)
    assert len(refreshed) == 2


def test_invalidate_items_drops_wikilinks_too(cfg: CondashConfig, tmp_conception: Path):
    cache = WorkspaceCache()
    ctx = build_ctx(cfg)
    # Warm the wikilink cache on a target that doesn't exist yet.
    assert cache.resolve_wikilink(ctx, "brand-new") is None
    _seed_project(tmp_conception, "brand-new")
    # Still cached as None until projects invalidation flushes it.
    assert cache.resolve_wikilink(ctx, "brand-new") is None
    cache.invalidate_items()
    assert cache.resolve_wikilink(ctx, "brand-new") == (
        "projects/2026-01/2026-01-01-brand-new/README.md"
    )


def test_get_knowledge_warms_once(cfg: CondashConfig, tmp_conception: Path):
    cache = WorkspaceCache()
    ctx = build_ctx(cfg)
    # No knowledge tree yet — get_knowledge returns None and remembers that.
    assert cache.get_knowledge(ctx) is None
    # Create one now; still cached as None until invalidated.
    (tmp_conception / "knowledge").mkdir()
    (tmp_conception / "knowledge" / "index.md").write_text("# Root\n", encoding="utf-8")
    assert cache.get_knowledge(ctx) is None
    cache.invalidate_knowledge()
    tree = cache.get_knowledge(ctx)
    assert tree is not None
    assert tree["label"] == "Knowledge"


def test_on_event_routes_projects_and_knowledge():
    cache = WorkspaceCache()
    # Seed internal state so we can observe the flush.
    cache._items = [{"slug": "sentinel"}]  # type: ignore[assignment]
    cache._knowledge = {"label": "sentinel"}
    cache._knowledge_loaded = True
    cache._wikilinks = {"t": "p"}
    cache.on_event({"tab": "projects"})
    assert cache._items is None
    assert cache._wikilinks == {}
    assert cache._knowledge_loaded is True  # untouched
    cache.on_event({"tab": "knowledge"})
    assert cache._knowledge_loaded is False
    # Unknown tab — no-op, and no exception.
    cache.on_event({"tab": "other"})


def test_eventbus_sync_subscriber_fires_on_publish():
    """Sync subscribers run inside _fanout on the event loop thread —
    before the asyncio queues receive the payload. That ordering is
    what lets the cache flush before SSE clients see the event."""

    async def run():
        bus = EventBus()
        bus.bind_loop(asyncio.get_running_loop())
        received: list[dict] = []
        bus.subscribe_sync(received.append)
        queue = bus.subscribe()
        bus.publish_threadsafe({"tab": "projects", "ts": 42.0})
        evt = await asyncio.wait_for(queue.get(), timeout=1.0)
        # Sync subscriber must have captured the same payload by the
        # time the async queue surfaces it.
        assert received == [{"tab": "projects", "ts": 42.0}]
        assert evt["tab"] == "projects"

    asyncio.run(run())


def test_eventbus_sync_subscriber_exception_does_not_block_fanout():
    async def run():
        bus = EventBus()
        bus.bind_loop(asyncio.get_running_loop())

        def boom(_payload: dict) -> None:
            raise RuntimeError("subscriber blew up")

        bus.subscribe_sync(boom)
        queue = bus.subscribe()
        bus.publish_threadsafe({"tab": "projects"})
        # Async queue must still get the event despite the raising sub.
        evt = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert evt["tab"] == "projects"

    asyncio.run(run())


def test_cache_invalidates_through_event_bus(cfg: CondashConfig, tmp_conception: Path):
    """End-to-end: WorkspaceCache.on_event via EventBus.subscribe_sync
    flushes the items slice when a ``projects`` event fires."""

    async def run():
        bus = EventBus()
        bus.bind_loop(asyncio.get_running_loop())
        cache = WorkspaceCache()
        bus.subscribe_sync(cache.on_event)
        ctx = build_ctx(cfg)
        first = cache.get_items(ctx)
        assert len(first) == 1
        _seed_project(tmp_conception, "second")
        queue = bus.subscribe()
        bus.publish_threadsafe({"tab": "projects"})
        await asyncio.wait_for(queue.get(), timeout=1.0)
        # After the sync callback has run, get_items re-walks the tree.
        refreshed = cache.get_items(ctx)
        assert refreshed is not first
        assert len(refreshed) == 2

    asyncio.run(run())


def test_state_cache_warmed_and_flushed_by_register_routes(cfg: CondashConfig):
    """The module-level state keeps its cache across _register_routes
    calls — the conftest autouse fixture flushes between tests."""
    app_mod.state.cfg = cfg
    app_mod.state.ctx = build_ctx(cfg)
    app_mod._register_routes()
    assert app_mod.state.cache is not None


@pytest.fixture
def tmp_conception_large(tmp_conception: Path) -> Path:
    """Add a second project so cache hits show on multiple-item lists."""
    _seed_project(tmp_conception, "another", status="soon")
    return tmp_conception
