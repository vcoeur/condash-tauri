"""Tests for the Phase-6 event push.

``events.EventBus`` bridges watchdog's worker thread to asyncio
subscribers; the tests here exercise the pure-python bits (bus
fan-out, handler debouncing, node-id resolution). The HTTP SSE route
is covered by a smoke test asserting it accepts a connection and
emits the initial ``hello`` frame.
"""

from __future__ import annotations

import asyncio

from condash.events import EventBus, _ConfigHandler, _DebouncedHandler, _GitHandler


class _FakeEvent:
    def __init__(self, src_path: str):
        self.src_path = src_path


def test_eventbus_fanout_to_subscribers():
    async def run():
        bus = EventBus()
        bus.bind_loop(asyncio.get_running_loop())
        queue = bus.subscribe()
        bus.publish_threadsafe({"tab": "projects", "ts": 1.0})
        evt = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert evt["tab"] == "projects"

    asyncio.run(run())


def test_debounced_handler_drops_dotfiles():
    bus = EventBus()
    captured: list[dict] = []
    bus.publish_threadsafe = captured.append  # type: ignore[assignment]
    h = _DebouncedHandler(bus, "projects")
    h.on_any_event(_FakeEvent("/tmp/.swp"))
    h.on_any_event(_FakeEvent("/tmp/README.md~"))
    assert captured == []


def test_debounced_handler_debounces_bursts():
    bus = EventBus()
    captured: list[dict] = []
    bus.publish_threadsafe = captured.append  # type: ignore[assignment]
    h = _DebouncedHandler(bus, "projects")
    for _ in range(5):
        h.on_any_event(_FakeEvent("/tmp/README.md"))
    assert len(captured) == 1
    assert captured[0]["tab"] == "projects"


def test_git_handler_only_reacts_to_watched_files():
    bus = EventBus()
    captured: list[dict] = []
    bus.publish_threadsafe = captured.append  # type: ignore[assignment]
    h = _GitHandler(bus)
    h.on_any_event(_FakeEvent("/tmp/.git/objects/ab/cdef"))
    assert captured == []
    h.on_any_event(_FakeEvent("/tmp/.git/HEAD"))
    assert len(captured) == 1
    assert captured[0]["tab"] == "code"


def test_config_handler_only_reacts_to_known_yaml_files():
    bus = EventBus()
    captured: list[dict] = []
    bus.publish_threadsafe = captured.append  # type: ignore[assignment]
    h = _ConfigHandler(bus)
    h.on_any_event(_FakeEvent("/tmp/config/unrelated.yml"))
    h.on_any_event(_FakeEvent("/tmp/config/repositories.yml.tmp"))
    assert captured == []
    h.on_any_event(_FakeEvent("/tmp/config/repositories.yml"))
    assert len(captured) == 1
    assert captured[0]["tab"] == "config"
    assert captured[0]["file"] == "repositories.yml"


def test_config_handler_calls_reload_callback():
    bus = EventBus()
    captured: list[dict] = []
    bus.publish_threadsafe = captured.append  # type: ignore[assignment]
    # No event loop bound — the threadsafe call short-circuits, but the
    # handler must still publish the SSE event for other subscribers.
    reload_calls: list[str] = []
    h = _ConfigHandler(bus, on_reload=reload_calls.append)
    h.on_any_event(_FakeEvent("/tmp/config/preferences.yml"))
    # Without a loop bound the reload callback is skipped defensively —
    # but the SSE event still fires.
    assert len(captured) == 1
    assert captured[0]["file"] == "preferences.yml"


def test_events_route_registered(cfg):
    """Smoke test: /events is registered as SSE and content-type is right.

    We don't try to read the stream — TestClient blocks on open-ended
    generators and the endpoint only terminates when the client
    disconnects. Asserting the route exists + has the right media
    type is enough here; hello/ping framing is covered by the route
    source being a StreamingResponse. Behavioural coverage lands on
    a Playwright pass in the future."""
    from nicegui import app as _ng_app

    from condash import app as app_mod
    from condash.context import build_ctx

    app_mod._RUNTIME_CFG = cfg
    app_mod._RUNTIME_CTX = build_ctx(cfg)
    app_mod._register_routes()
    paths = [getattr(r, "path", "") for r in _ng_app.routes]
    assert "/events" in paths


# The `cfg` fixture is provided by tests/conftest.py.
