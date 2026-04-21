"""HTTP clipboard access for the embedded terminal.

pywebview's Qt webview doesn't grant ``navigator.clipboard.readText``
access over localhost, so the in-page xterm falls back to these endpoints
on Ctrl+V / Ctrl+Shift+C. Implementation lives in
:mod:`condash.clipboard` (shared with the native pywebview JS bridge).
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import Response

from ..clipboard import clipboard_read, clipboard_write
from ..state import AppState


def build_router(state: AppState) -> APIRouter:  # noqa: ARG001 — unused but matches sibling shape
    router = APIRouter()

    @router.get("/clipboard")
    def clipboard_get():
        return Response(
            content=clipboard_read(),
            media_type="text/plain; charset=utf-8",
            headers={"Cache-Control": "no-store"},
        )

    @router.post("/clipboard")
    async def clipboard_post(req: Request):
        body = await req.body()
        text = body.decode("utf-8", errors="replace")
        ok = clipboard_write(text)
        return {"ok": bool(ok)}

    return router
