"""HTTP + WebSocket route packages for condash.

Each submodule exposes ``build_router(state) -> APIRouter`` (and, for the
WebSocket handlers, registers directly on the FastAPI app since
``APIRouter.websocket_route`` and ``include_router`` interact awkwardly
with NiceGUI's ``_ng_app``). :func:`register_all` wires everything onto
the live FastAPI instance — called by :func:`condash.app._register_routes`
on startup and by tests that want to exercise the routes via
``TestClient``.
"""

from __future__ import annotations

from fastapi import FastAPI

from ..state import AppState
from . import (
    clipboard,
    config_,
    files,
    fragments,
    items,
    notes,
    openers,
    runners,
    static,
    steps,
    terminals,
    updates,
)


def register_all(app: FastAPI, state: AppState) -> None:
    """Attach every route group + WebSocket handler to ``app``."""
    for module in (
        static,
        updates,
        fragments,
        notes,
        items,
        files,
        steps,
        clipboard,
        openers,
        config_,
        runners,
    ):
        app.include_router(module.build_router(state))
    # Terminal WebSockets are registered directly on the app — APIRouter
    # WebSockets work but the include path is fussier with NiceGUI's app
    # subclass, and there are exactly two of them.
    terminals.register(app, state)
