"""Transition shim — to be deleted in Phase 3.

Re-exports everything the split submodules used to import via ``core``,
plus an :func:`init` shim that builds a :class:`RenderCtx` and stashes it
in ``_CTX`` for callers that haven't been migrated yet.

Once :mod:`condash.app` and :mod:`condash.cli` are fully ported to
``build_ctx(cfg)`` + explicit ``ctx`` threading, this whole module goes
away.
"""

from __future__ import annotations

from .context import RenderCtx, build_ctx, favicon_bytes  # noqa: F401
from .git_scan import (  # noqa: F401
    _collect_git_repos,
    _git_cache,
    _git_fingerprint,
    _git_status,
    _git_worktrees,
    _is_sandbox_stub,
    _load_repository_structure,
    _resolve_submodules,
)
from .mutations import (  # noqa: F401
    _KIND_MAP,
    _add_step,
    _edit_step,
    _remove_step,
    _reorder_all,
    _set_priority,
    _tidy,
    _toggle_checkbox,
    create_note,
    read_note_raw,
    rename_note,
    run_tidy,
    write_note,
)
from .openers import (  # noqa: F401
    _EXTERNAL_URL_RE,
    _is_external_url,
    _open_external,
    _open_path,
    _os_open,
    _try_pdf_viewer,
)
from .parser import (  # noqa: F401
    _IMAGE_EXTS,
    _ITEM_DIR_RE,
    _MONTH_DIR_RE,
    _PDF_EXTS,
    _TEXT_EXTS,
    CHECKBOX_RE,
    DELIVERABLE_RE,
    HEADING2_RE,
    HEADING3_RE,
    METADATA_RE,
    PRI_ORDER,
    PRIORITIES,
    STATUS_RE,
    _compute_fingerprint,
    _knowledge_node,
    _knowledge_title_and_desc,
    _list_notes,
    _note_kind,
    _parse_deliverables,
    _parse_sections,
    _tidy_needed,
    collect_items,
    collect_knowledge,
    parse_readme,
)
from .paths import (  # noqa: F401
    _ASSET_CONTENT_TYPES,
    _VALID_ASSET_RE,
    _VALID_DOWNLOAD_RE,
    _VALID_ITEM_FILE_RE,
    _VALID_KNOWLEDGE_NOTE_RE,
    _VALID_NOTE_FILENAME_RE,
    _VALID_NOTE_RE,
    _VALID_PATH_RE,
    _guess_content_type,
    _safe_resolve,
    _validate_doc_path,
    _validate_open_path,
    _validate_path,
    validate_asset_path,
    validate_download_path,
    validate_file_path,
    validate_note_path,
)
from .render import (  # noqa: F401
    _ICON_SVGS,
    _IMG_SRC_RE,
    _render_card,
    _render_deliverables,
    _render_git_actions,
    _render_git_repos,
    _render_group,
    _render_index_badge,
    _render_knowledge,
    _render_knowledge_card,
    _render_knowledge_group,
    _render_markdown,
    _render_note,
    _render_notes,
    _render_readme_link,
    _render_step,
    _render_submodule_rows,
    _rewrite_img_src,
    h,
    render_page,
)
from .wikilinks import (  # noqa: F401
    _DATE_SLUG_RE,
    _ITEM_TYPE_NORMAL,
    _WIKILINK_RE,
    _find_item_dir,
    _preprocess_wikilinks,
    _resolve_wikilink,
)

# Transition shim: a single mutable RenderCtx shared with tests / CLI
# call sites that haven't been updated. ``init(cfg)`` rebuilds it in place.
_CTX: RenderCtx | None = None


def init(cfg) -> RenderCtx:
    """Build a fresh :class:`RenderCtx` and stash it for transition callers."""
    global _CTX
    _CTX = build_ctx(cfg)
    return _CTX


def get_ctx() -> RenderCtx:
    """Return the last :class:`RenderCtx` produced by :func:`init`."""
    if _CTX is None:
        raise RuntimeError("condash.core.init(cfg) must be called before get_ctx()")
    return _CTX
