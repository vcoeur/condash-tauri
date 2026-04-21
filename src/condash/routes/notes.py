"""Note mutation routes — create / write / rename / mkdir / upload.

Every path goes through ``paths.validate_note_path`` (or
``mutations.create_*`` which composes a similar check) so a caller can't
escape ``<item>/notes/``. Uploads stream to disk to keep RAM bounded
under large drops.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..mutations import (
    create_note,
    create_notes_subdir,
    rename_note,
    store_uploads,
    write_note,
)
from ..parser import _note_kind
from ..paths import validate_note_path
from ..state import AppState
from ._common import error


def build_router(state: AppState) -> APIRouter:
    router = APIRouter()

    @router.post("/note")
    async def post_note(req: Request):
        """Atomically overwrite a note file with the editor's content."""
        ctx = state.get_ctx()
        data = await req.json()
        full = validate_note_path(ctx, str(data.get("path") or ""))
        if full is None:
            return error(403, "invalid path")
        if _note_kind(full) not in ("md", "text"):
            return error(400, "not editable")
        content = data.get("content")
        if not isinstance(content, str):
            return error(400, "content must be a string")
        result = write_note(full, content, data.get("expected_mtime"))
        if not result.get("ok"):
            return JSONResponse(status_code=409, content=result)
        return result

    @router.post("/note/rename")
    async def post_note_rename(req: Request):
        """Rename a file under ``<item>/notes/`` preserving the extension."""
        ctx = state.get_ctx()
        data = await req.json()
        result = rename_note(
            ctx,
            str(data.get("path") or ""),
            str(data.get("new_stem") or ""),
        )
        if not result.get("ok"):
            return error(400, result.get("reason", "rename failed"))
        return result

    @router.post("/note/create")
    async def post_note_create(req: Request):
        """Create an empty note under ``<item>/notes[/subdir]/``."""
        ctx = state.get_ctx()
        data = await req.json()
        result = create_note(
            ctx,
            str(data.get("item_readme") or ""),
            str(data.get("filename") or ""),
            subdir=str(data.get("subdir") or ""),
        )
        if not result.get("ok"):
            return error(400, result.get("reason", "create failed"))
        return result

    @router.post("/note/mkdir")
    async def post_note_mkdir(req: Request):
        """Create a (possibly nested) directory under ``<item>/notes/``."""
        ctx = state.get_ctx()
        data = await req.json()
        result = create_notes_subdir(
            ctx,
            str(data.get("item_readme") or ""),
            str(data.get("subpath") or ""),
        )
        if not result.get("ok"):
            status = 409 if result.get("reason") == "exists" else 400
            return JSONResponse(status_code=status, content=result)
        return result

    @router.post("/note/upload")
    async def post_note_upload(req: Request):
        """Persist files uploaded via ``multipart/form-data`` under
        ``<item>/notes[/subdir]/``. Auto-suffixes ``(2)``, ``(3)``… on
        name collision; rejects > 50 MB per file. Streams to disk so a
        large upload doesn't sit in RAM."""
        ctx = state.get_ctx()
        form = await req.form()
        item_readme = str(form.get("item_readme") or "")
        subdir = str(form.get("subdir") or "")
        uploads: list[tuple[str, object]] = []
        for key in form.keys():
            if key != "file":
                continue
            for entry in form.getlist(key):
                # Starlette gives UploadFile for files, str for plain
                # fields — skip anything that's not a file.
                if hasattr(entry, "file") and hasattr(entry, "filename"):
                    uploads.append((entry.filename, entry.file))
        if not uploads:
            return error(400, "no files in upload")
        result = store_uploads(ctx, item_readme, subdir, uploads)
        if not result.get("ok"):
            return error(400, result.get("reason", "upload failed"))
        return result

    return router
