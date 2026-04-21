"""Static + vendored-asset routes.

Serves the dashboard shell at ``/`` (HTML rendered by :mod:`render`),
favicons, and the vendored frontend libraries (Mozilla PDF.js, xterm.js,
CodeMirror 6) under ``/vendor/<lib>/{rel_path}``. Each vendor route is a
narrow read-only window into the package's ``assets/vendor/<lib>/`` tree
with a regex-free traversal guard.
"""

from __future__ import annotations

from importlib.resources import files as _package_files
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, Response

from ..context import favicon_bytes
from ..parser import collect_items
from ..render import render_page
from ..state import AppState

_PDFJS_MIME = {
    ".mjs": "text/javascript",
    ".js": "text/javascript",
    ".json": "application/json",
    ".wasm": "application/wasm",
    ".bcmap": "application/octet-stream",
    ".pfb": "application/octet-stream",
    ".icc": "application/octet-stream",
    ".css": "text/css",
}

_XTERM_MIME = {
    ".js": "text/javascript",
    ".css": "text/css",
}


def _serve_vendor(lib: str, rel_path: str, mime_table: dict[str, str] | None = None) -> Response:
    """Read-only window into ``assets/vendor/<lib>/`` with a traversal guard."""
    if not rel_path or "\x00" in rel_path:
        return Response(status_code=403)
    parts = rel_path.split("/")
    if any(p in ("", "..") for p in parts):
        return Response(status_code=403)
    base = Path(str(_package_files("condash") / "assets" / "vendor" / lib))
    try:
        full = (base / rel_path).resolve()
        full.relative_to(base.resolve())
    except (OSError, ValueError):
        return Response(status_code=403)
    if not full.is_file():
        return Response(status_code=404)
    if mime_table is None:
        ctype = "text/javascript" if full.suffix == ".js" else "text/plain"
    else:
        ctype = mime_table.get(full.suffix.lower(), "application/octet-stream")
    return Response(
        content=full.read_bytes(),
        media_type=ctype,
        headers={"Cache-Control": "public, max-age=86400"},
    )


def build_router(state: AppState) -> APIRouter:
    router = APIRouter()

    @router.get("/", response_class=HTMLResponse)
    def index():
        ctx = state.get_ctx()
        items = collect_items(ctx)
        return HTMLResponse(content=render_page(ctx, items))

    @router.get("/favicon.svg")
    def favicon_svg():
        data = favicon_bytes()
        if data is None:
            return Response(status_code=404)
        return Response(
            content=data,
            media_type="image/svg+xml",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    @router.get("/favicon.ico")
    def favicon_ico():
        data = favicon_bytes()
        if data is None:
            return Response(status_code=404)
        return Response(content=data, media_type="image/svg+xml")

    @router.get("/vendor/pdfjs/{rel_path:path}")
    def pdfjs_asset(rel_path: str):
        """Serve the vendored Mozilla PDF.js library to the in-modal viewer."""
        return _serve_vendor("pdfjs", rel_path, _PDFJS_MIME)

    @router.get("/vendor/xterm/{rel_path:path}")
    def xterm_asset(rel_path: str):
        """Serve the vendored xterm.js bundle (lib + CSS + fit addon)."""
        return _serve_vendor("xterm", rel_path, _XTERM_MIME)

    @router.get("/vendor/codemirror/{rel_path:path}")
    def codemirror_asset(rel_path: str):
        """Serve the vendored CodeMirror 6 IIFE bundle to the config modal."""
        return _serve_vendor("codemirror", rel_path)

    return router
