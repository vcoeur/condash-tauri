"""Long-poll fingerprints + filesystem-driven SSE stream.

``/check-updates`` returns a per-tab fingerprint set that the dashboard
polls; ``/events`` is the SSE channel the watchdog observer publishes to
when files under ``conception_path`` change. The frontend treats any
event as a hint to re-poll ``/check-updates`` — the event payload is not
authoritative state.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from ..git_scan import _git_fingerprint, compute_git_node_fingerprints
from ..parser import (
    _compute_fingerprint,
    collect_items,
    collect_knowledge,
    compute_knowledge_node_fingerprints,
    compute_project_node_fingerprints,
)
from ..state import AppState


def build_router(state: AppState) -> APIRouter:
    router = APIRouter()

    @router.get("/check-updates")
    def check_updates():
        ctx = state.get_ctx()
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

    @router.get("/events")
    async def events(request: Request):
        """SSE stream of filesystem-driven staleness events.

        Each message is a JSON payload with at least a ``tab`` field
        (``projects`` / ``knowledge`` / ``code``). The frontend treats
        any event as a trigger to re-run ``/check-updates`` — the event
        content is a hint, not authoritative state.

        A ``ping`` event fires every 30 seconds so reverse proxies
        (and the browser's EventSource) keep the connection open and
        reconnection logic has a signal to latch onto.
        """
        bus = state.event_bus
        assert bus is not None, "event_bus must be initialised before serving /events"
        bus.bind_loop(asyncio.get_running_loop())
        queue = bus.subscribe()

        async def stream():
            try:
                # Opening hello so EventSource.onopen fires immediately —
                # the UI needs this to clear its "reconnecting" pill.
                yield "event: hello\ndata: {}\n\n"
                while True:
                    if await request.is_disconnected():
                        return
                    try:
                        payload = await asyncio.wait_for(queue.get(), timeout=30.0)
                    except TimeoutError:
                        yield "event: ping\ndata: {}\n\n"
                        continue
                    yield f"data: {json.dumps(payload)}\n\n"
            finally:
                bus.unsubscribe(queue)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    return router
