"""External-launcher routes — IDE / file-manager / browser handoff.

The ``open_with`` slot configuration drives ``/open``; ``/open-doc`` and
``/open-folder`` use the OS default opener; ``/open-external`` only
accepts http(s) URLs (rejects file://, javascript:, …) so the dashboard
can't be tricked into spawning arbitrary handlers.

``/recent-screenshot`` is the screenshot-paste shortcut's data source
(newest image in ``terminal.screenshot_dir``).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request

from ..config import SCREENSHOT_IMAGE_EXTENSIONS
from ..openers import _is_external_url, _open_external, _open_path, _os_open
from ..paths import _validate_doc_path, _validate_item_dir, _validate_open_path
from ..state import AppState
from ._common import error


def build_router(state: AppState) -> APIRouter:
    router = APIRouter()

    @router.post("/open")
    async def open_path(req: Request):
        ctx = state.get_ctx()
        data = await req.json()
        resolved = _validate_open_path(ctx, data.get("path", ""))
        if not resolved:
            return error(400, "invalid path")
        tool = data.get("tool", "")
        if _open_path(ctx, tool, resolved):
            return {"ok": True}
        return error(500, f"could not launch {tool}")

    @router.post("/open-doc")
    async def open_doc(req: Request):
        """Hand a conception-tree file to the OS default viewer."""
        ctx = state.get_ctx()
        data = await req.json()
        resolved = _validate_doc_path(ctx, data.get("path", ""))
        if not resolved:
            return error(400, "invalid path")
        if _os_open(ctx, resolved):
            return {"ok": True}
        return error(500, "could not launch system opener")

    @router.post("/open-folder")
    async def open_folder(req: Request):
        """Hand a project-item folder to the OS default file manager."""
        ctx = state.get_ctx()
        data = await req.json()
        resolved = _validate_item_dir(ctx, data.get("path", ""))
        if not resolved:
            return error(400, "invalid path")
        if _os_open(ctx, resolved):
            return {"ok": True}
        return error(500, "could not launch system opener")

    @router.post("/open-external")
    async def open_external(req: Request):
        """Open an http(s) URL in the user's default browser."""
        data = await req.json()
        url = str(data.get("url") or "").strip()
        if not _is_external_url(url):
            return error(400, "invalid url")
        if _open_external(url):
            return {"ok": True}
        return error(500, "could not launch browser")

    @router.get("/recent-screenshot")
    def recent_screenshot():
        """Return the absolute path of the newest image in the screenshot dir.

        Used by the screenshot-paste shortcut to inject a path into the
        active terminal tab without an extra clipboard hop. Returns
        ``{path: <abs>, dir: <abs>}`` on success or
        ``{path: null, dir: <abs>, reason: <message>}`` when the directory
        is missing, unreadable, or empty.
        """
        cfg = state.cfg
        if cfg is None:
            return error(500, "config not initialised")
        directory = cfg.terminal.resolved_screenshot_dir()
        payload = {"path": None, "dir": str(directory), "reason": ""}
        if not directory.exists():
            payload["reason"] = "directory does not exist"
            return payload
        if not directory.is_dir():
            payload["reason"] = "configured path is not a directory"
            return payload
        try:
            entries = list(directory.iterdir())
        except PermissionError:
            payload["reason"] = "permission denied"
            return payload
        candidates: list[tuple[float, Path]] = []
        for entry in entries:
            if not entry.is_file():
                continue
            if entry.suffix.lower() not in SCREENSHOT_IMAGE_EXTENSIONS:
                continue
            try:
                mtime = entry.stat().st_mtime
            except OSError:
                continue
            candidates.append((mtime, entry))
        if not candidates:
            payload["reason"] = "no image files found"
            return payload
        candidates.sort(key=lambda pair: pair[0], reverse=True)
        payload["path"] = str(candidates[0][1])
        return payload

    return router
