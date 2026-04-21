"""Step-list mutation routes — toggle, add, edit, remove, reorder, priority.

Every handler validates the readme path with ``paths._validate_path``
before delegating to the matching helper in :mod:`condash.mutations`.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from ..mutations import (
    _add_step,
    _edit_step,
    _remove_step,
    _reorder_all,
    _set_priority,
    _toggle_checkbox,
)
from ..paths import _validate_path
from ..state import AppState
from ._common import error


def build_router(state: AppState) -> APIRouter:
    router = APIRouter()

    @router.post("/toggle")
    async def toggle(req: Request):
        data = await req.json()
        full = _validate_path(state.get_ctx(), data.get("file", ""))
        if not full:
            return error(400, "invalid path")
        status = _toggle_checkbox(full, data.get("line", -1))
        if status is None:
            return error(400, "not a checkbox line")
        return {"ok": True, "status": status}

    @router.post("/remove-step")
    async def remove_step(req: Request):
        data = await req.json()
        full = _validate_path(state.get_ctx(), data.get("file", ""))
        if not full:
            return error(400, "invalid path")
        if _remove_step(full, data.get("line", -1)):
            return {"ok": True}
        return error(400, "cannot remove")

    @router.post("/edit-step")
    async def edit_step(req: Request):
        data = await req.json()
        text = (data.get("text") or "").strip()
        if not text:
            return error(400, "empty text")
        full = _validate_path(state.get_ctx(), data.get("file", ""))
        if not full:
            return error(400, "invalid path")
        if _edit_step(full, data.get("line", -1), text):
            return {"ok": True}
        return error(400, "cannot edit")

    @router.post("/add-step")
    async def add_step(req: Request):
        data = await req.json()
        text = (data.get("text") or "").strip()
        if not text:
            return error(400, "empty text")
        full = _validate_path(state.get_ctx(), data.get("file", ""))
        if not full:
            return error(400, "invalid path")
        line = _add_step(full, text, data.get("section"))
        return {"ok": True, "line": line}

    @router.post("/set-priority")
    async def set_priority(req: Request):
        data = await req.json()
        full = _validate_path(state.get_ctx(), data.get("file", ""))
        if not full:
            return error(400, "invalid path")
        priority = data.get("priority", "")
        if _set_priority(full, priority):
            return {"ok": True, "priority": priority}
        return error(400, "invalid priority")

    @router.post("/reorder-all")
    async def reorder_all(req: Request):
        data = await req.json()
        full = _validate_path(state.get_ctx(), data.get("file", ""))
        if not full:
            return error(400, "invalid path")
        order = data.get("order") or []
        if _reorder_all(full, order):
            return {"ok": True}
        return error(400, "cannot reorder")

    return router
