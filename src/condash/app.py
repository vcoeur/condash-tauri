"""NiceGUI-backed native window for condash.

The existing ``dashboard.html`` is served verbatim at ``/``; all the AJAX
endpoints the JS calls (``/toggle``, ``/add-step``, ``/tidy``, …) are
re-implemented here as FastAPI routes on top of NiceGUI's underlying
FastAPI instance.
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from nicegui import app as _ng_app
from nicegui import ui

from . import legacy
from .config import CondashConfig


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": message})


def _register_routes() -> None:
    """Attach all API routes to NiceGUI's FastAPI instance."""

    @_ng_app.get("/", response_class=HTMLResponse)
    def index():
        items = legacy.collect_items()
        return HTMLResponse(content=legacy.render_page(items))

    @_ng_app.get("/favicon.svg")
    def favicon_svg():
        data = legacy._favicon_bytes()
        if data is None:
            return Response(status_code=404)
        return Response(
            content=data,
            media_type="image/svg+xml",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    @_ng_app.get("/favicon.ico")
    def favicon_ico():
        data = legacy._favicon_bytes()
        if data is None:
            return Response(status_code=404)
        return Response(content=data, media_type="image/svg+xml")

    @_ng_app.get("/check-updates")
    def check_updates():
        items = legacy.collect_items()
        return {
            "fingerprint": legacy._compute_fingerprint(items),
            "tidy_needed": legacy._tidy_needed(items),
            "git_fingerprint": legacy._git_fingerprint(),
        }

    @_ng_app.get("/note")
    def get_note(path: str = ""):
        full = legacy.validate_note_path(path)
        if full is None:
            return Response(status_code=403)
        return HTMLResponse(content=legacy._render_note(full))

    @_ng_app.get("/download/{rel_path:path}")
    def download(rel_path: str):
        full = legacy.validate_download_path(rel_path)
        if full is None:
            return Response(status_code=403)
        return Response(
            content=full.read_bytes(),
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{full.name}"'},
        )

    @_ng_app.get("/asset/{rel_path:path}")
    def asset(rel_path: str):
        result = legacy.validate_asset_path(rel_path)
        if result is None:
            return Response(status_code=403)
        full, ctype = result
        return Response(
            content=full.read_bytes(),
            media_type=ctype,
            headers={"Cache-Control": "public, max-age=300"},
        )

    @_ng_app.post("/toggle")
    async def toggle(req: Request):
        data = await req.json()
        full = legacy._validate_path(data.get("file", ""))
        if not full:
            return _error(400, "invalid path")
        status = legacy._toggle_checkbox(full, data.get("line", -1))
        if status is None:
            return _error(400, "not a checkbox line")
        return {"ok": True, "status": status}

    @_ng_app.post("/remove-step")
    async def remove_step(req: Request):
        data = await req.json()
        full = legacy._validate_path(data.get("file", ""))
        if not full:
            return _error(400, "invalid path")
        if legacy._remove_step(full, data.get("line", -1)):
            return {"ok": True}
        return _error(400, "cannot remove")

    @_ng_app.post("/edit-step")
    async def edit_step(req: Request):
        data = await req.json()
        text = (data.get("text") or "").strip()
        if not text:
            return _error(400, "empty text")
        full = legacy._validate_path(data.get("file", ""))
        if not full:
            return _error(400, "invalid path")
        if legacy._edit_step(full, data.get("line", -1), text):
            return {"ok": True}
        return _error(400, "cannot edit")

    @_ng_app.post("/add-step")
    async def add_step(req: Request):
        data = await req.json()
        text = (data.get("text") or "").strip()
        if not text:
            return _error(400, "empty text")
        full = legacy._validate_path(data.get("file", ""))
        if not full:
            return _error(400, "invalid path")
        line = legacy._add_step(full, text, data.get("section"))
        return {"ok": True, "line": line}

    @_ng_app.post("/set-priority")
    async def set_priority(req: Request):
        data = await req.json()
        full = legacy._validate_path(data.get("file", ""))
        if not full:
            return _error(400, "invalid path")
        priority = data.get("priority", "")
        if legacy._set_priority(full, priority):
            moves = legacy._tidy()
            return {"ok": True, "priority": priority, "moved": bool(moves)}
        return _error(400, "invalid priority")

    @_ng_app.post("/reorder-all")
    async def reorder_all(req: Request):
        data = await req.json()
        full = legacy._validate_path(data.get("file", ""))
        if not full:
            return _error(400, "invalid path")
        order = data.get("order") or []
        if legacy._reorder_all(full, order):
            return {"ok": True}
        return _error(400, "cannot reorder")

    @_ng_app.post("/open")
    async def open_path(req: Request):
        data = await req.json()
        resolved = legacy._validate_open_path(data.get("path", ""))
        if not resolved:
            return _error(400, "invalid path")
        tool = data.get("tool", "")
        if legacy._open_path(tool, resolved):
            return {"ok": True}
        return _error(500, f"could not launch {tool}")

    @_ng_app.post("/tidy")
    async def tidy(_req: Request):
        moves = legacy._tidy()
        return {
            "ok": True,
            "moves": [{"from": f, "to": t} for f, t in moves],
        }


def run(cfg: CondashConfig) -> None:
    """Launch the native condash window."""
    legacy.init(cfg)
    _register_routes()
    ui.run(
        native=True,
        title="condash",
        window_size=(1400, 900),
        reload=False,
        show=False,
        port=0,
    )
