"""Scoped-reload + read-only render endpoints.

``/fragment`` returns the HTML subtree for a single project card,
knowledge card, or knowledge directory; the dashboard uses it to swap
exactly one card after a filesystem event without touching the rest of
the page.

``/search-history`` powers the History tab's free-text search.
``/note`` / ``/note-raw`` render and dump a single note for the in-modal
preview and editor.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse, Response

from ..mutations import read_note_raw
from ..parser import (
    _note_kind,
    collect_items,
    collect_knowledge,
    find_knowledge_card,
    find_knowledge_node,
)
from ..paths import validate_note_path
from ..render import (
    _render_note,
    render_card_fragment,
    render_git_repo_fragment,
    render_knowledge_card_fragment,
    render_knowledge_group_fragment,
)
from ..search import search_items
from ..state import AppState
from ._common import error


def build_router(state: AppState) -> APIRouter:
    router = APIRouter()

    @router.get("/fragment", response_class=HTMLResponse)
    def fragment(id: str = ""):
        """Return the HTML subtree for a single card or knowledge directory.

        Supported id shapes:
          - ``projects/<priority>/<slug>`` — one project card.
          - ``knowledge/<rel>`` — one knowledge card (if ``<rel>`` is a file)
            or one directory subtree (if ``<rel>`` is a knowledge directory).
        Anything else (group, tab, code node) returns 404; the client falls
        back to a global in-place reload for those.
        """
        ctx = state.get_ctx()
        if not id:
            return error(400, "missing id")
        if id.startswith("projects/"):
            parts = id.split("/", 2)
            if len(parts) != 3:
                return error(404, "not a card id")
            slug = parts[2]
            for item in collect_items(ctx):
                if item["slug"] == slug:
                    return HTMLResponse(content=render_card_fragment(item))
            return error(404, "card not found")
        if id == "knowledge":
            # Root pane uses a different wrapper than a subdirectory group;
            # falling back to global reload is simpler than special-casing it.
            return error(404, "use global reload")
        if id.startswith("code/"):
            # Only whole-repo nodes are fragmentable — groups and the
            # bare 'code' root still fall through to the global reload.
            rest = id[len("code/") :]
            if "/" not in rest:
                return error(404, "use global reload")
            html = render_git_repo_fragment(ctx, id)
            if html is None:
                return error(404, "repo not found")
            return HTMLResponse(content=html)
        if id.startswith("knowledge/"):
            tree = collect_knowledge(ctx)
            # File cards have an extension (e.g. ".md"); directories do not.
            if id.endswith(".md"):
                card = find_knowledge_card(tree, id)
                if card is None:
                    return error(404, "card not found")
                return HTMLResponse(content=render_knowledge_card_fragment(card))
            node = find_knowledge_node(tree, id)
            if node is None:
                return error(404, "dir not found")
            return HTMLResponse(content=render_knowledge_group_fragment(node))
        return error(404, "unsupported id")

    @router.get("/search-history")
    def search_history(q: str = ""):
        """Broadened history-tab search — matches README bodies, notes, and
        filenames. Returns a list of per-project hits shaped by
        :func:`search.search_items`. Empty query → ``[]``."""
        ctx = state.get_ctx()
        items = collect_items(ctx)
        return JSONResponse(search_items(ctx, items, q))

    @router.get("/note")
    def get_note(path: str = ""):
        ctx = state.get_ctx()
        full = validate_note_path(ctx, path)
        if full is None:
            return Response(status_code=403)
        return HTMLResponse(content=_render_note(ctx, full))

    @router.get("/note-raw")
    def get_note_raw(path: str = ""):
        """Return plain-text content + mtime for the in-modal edit mode."""
        ctx = state.get_ctx()
        full = validate_note_path(ctx, path)
        if full is None:
            return error(403, "invalid path")
        kind = _note_kind(full)
        if kind not in ("md", "text"):
            return error(400, f"not editable ({kind})")
        return read_note_raw(ctx, full)

    return router
