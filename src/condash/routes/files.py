"""Read-only file-bytes routes.

``/download`` streams a PDF for the in-modal viewer; ``/asset`` serves
images and other static notes; ``/file`` is the generic read window for
the PDF viewer + image previews. Each path goes through a regex-aware
validator (``paths.validate_*``) so callers can't escape the conception
tree.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import Response

from ..paths import validate_asset_path, validate_download_path, validate_file_path
from ..state import AppState


def build_router(state: AppState) -> APIRouter:
    router = APIRouter()

    @router.get("/download/{rel_path:path}")
    def download(rel_path: str):
        full = validate_download_path(state.get_ctx(), rel_path)
        if full is None:
            return Response(status_code=403)
        return Response(
            content=full.read_bytes(),
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{full.name}"'},
        )

    @router.get("/asset/{rel_path:path}")
    def asset(rel_path: str):
        result = validate_asset_path(state.get_ctx(), rel_path)
        if result is None:
            return Response(status_code=403)
        full, ctype = result
        return Response(
            content=full.read_bytes(),
            media_type=ctype,
            headers={"Cache-Control": "public, max-age=300"},
        )

    @router.get("/file/{rel_path:path}")
    def get_file(rel_path: str):
        """Stream raw bytes for any file under the conception tree.

        Powers the in-modal preview for PDFs and images, and the
        "Open externally" fallback path handoff. Narrower than a generic
        static mount: paths are re-validated against conception-tree
        regexes on every call.
        """
        result = validate_file_path(state.get_ctx(), rel_path)
        if result is None:
            return Response(status_code=403)
        full, ctype = result
        return Response(
            content=full.read_bytes(),
            media_type=ctype,
            headers={"Cache-Control": "private, max-age=60"},
        )

    return router
