"""Project-item scaffolder route.

Powers the "+ New item" modal: writes
``projects/<YYYY-MM>/<YYYY-MM-DD>-<slug>/README.md`` and an empty
``notes/`` directory with a minimal seeded body. Every field is
revalidated server-side; ``409`` on slug collision, ``400`` otherwise.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..mutations import create_item
from ..state import AppState


def build_router(state: AppState) -> APIRouter:
    router = APIRouter()

    @router.post("/api/items")
    async def post_api_items(req: Request):
        """Scaffold a new conception item from the header "New item" modal."""
        ctx = state.get_ctx()
        data = await req.json()
        result = create_item(
            ctx,
            title=str(data.get("title") or ""),
            slug=str(data.get("slug") or ""),
            kind=str(data.get("kind") or ""),
            status=str(data.get("status") or ""),
            apps=str(data.get("apps") or ""),
            environment=str(data.get("environment") or ""),
            severity=str(data.get("severity") or ""),
            languages=str(data.get("languages") or ""),
        )
        if not result.get("ok"):
            reason = result.get("reason", "create failed")
            status = 409 if "already exists" in reason else 400
            return JSONResponse(status_code=status, content=result)
        # Flush the items cache so the next GET sees the new folder
        # without waiting for the watchdog's debounce window — the
        # round-trip is explicit here, not filesystem-observed.
        if state.cache is not None:
            state.cache.invalidate_items()
        return result

    return router
