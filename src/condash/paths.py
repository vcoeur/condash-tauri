"""Path validation for the conception directory tree.

Every HTTP-facing route that accepts a user-supplied path uses one of the
validators here to resolve it safely under ``ctx.base_dir``. The shared
``_safe_resolve`` helper consolidates the "reject traversal + regex-gate +
resolve + relative_to + existence check" dance that every validator used
to duplicate inline.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

from .context import RenderCtx

_VALID_ITEM_PREFIX = r"^projects/\d{4}-\d{2}/\d{4}-\d{2}-\d{2}-[\w.-]+/"

_VALID_PATH_RE = re.compile(_VALID_ITEM_PREFIX + r"README\.md$")

# Any file at any depth under an item directory — cards now surface the
# full item tree, not just ``notes/``, so the regexes that gate file
# serving must follow. Traversal is still blocked by ``_safe_resolve``
# (the ".." reject + relative_to check), so relaxing the regex to an
# arbitrary subpath stays safe.
_VALID_DOWNLOAD_RE = re.compile(_VALID_ITEM_PREFIX + r"[\w./-]+\.pdf$")

_VALID_NOTE_RE = re.compile(_VALID_ITEM_PREFIX + r"[\w./-]+\.md$")

# Knowledge pages live outside the date-prefixed item structure. Match
# `knowledge/<file>.md` at the root (conventions.md) and any depth of
# subdir under it (`topics/index.md`, `topics/ops/dev-ports.md`, …).
# `_safe_resolve` still rejects traversal (`..`, `\x00`) and enforces
# `relative_to(base)`, so allowing arbitrary depth here stays safe.
_VALID_KNOWLEDGE_NOTE_RE = re.compile(r"^knowledge/(?:[\w.-]+/)*[\w.-]+\.md$")

_VALID_ASSET_RE = re.compile(
    _VALID_ITEM_PREFIX + r"[\w./-]+\.(?:png|jpg|jpeg|gif|svg|webp)$",
    re.IGNORECASE,
)

# Any file at any depth inside an item directory.
_VALID_ITEM_FILE_RE = re.compile(_VALID_ITEM_PREFIX + r"[\w./-]+$")

# Restricted to files directly under ``<item>/notes/`` — used by rename
# (only notes are user-renamable; loose item files and READMEs are not).
_VALID_ITEM_NOTES_FILE_RE = re.compile(_VALID_ITEM_PREFIX + r"notes/[\w./-]+$")

_VALID_NOTE_FILENAME_RE = re.compile(r"^[\w.-]+\.[A-Za-z0-9]+$")

_ASSET_CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
}


def _safe_resolve(
    ctx: RenderCtx,
    rel_path: str,
    regexes: Sequence[re.Pattern] = (),
    *,
    require_file: bool = True,
    strict: bool = False,
) -> Path | None:
    """Resolve ``rel_path`` under ``ctx.base_dir``, rejecting anything outside."""
    if not rel_path or "\x00" in rel_path or ".." in rel_path:
        return None
    if regexes and not any(p.match(rel_path) for p in regexes):
        return None
    base = ctx.base_dir
    try:
        if strict:
            full = (base / rel_path).resolve(strict=True)
        else:
            full = (base / rel_path).resolve()
        full.relative_to(base.resolve())
    except (OSError, ValueError):
        return None
    if require_file:
        return full if full.is_file() else None
    return full if full.exists() else None


def _validate_path(ctx: RenderCtx, rel_path: str) -> Path | None:
    """Validate an item-README path."""
    return _safe_resolve(ctx, rel_path, (_VALID_PATH_RE,), require_file=False)


def validate_note_path(ctx: RenderCtx, rel_path: str) -> Path | None:
    """Public: validate a note/README/knowledge/notes-file path."""
    return _safe_resolve(
        ctx,
        rel_path,
        (_VALID_NOTE_RE, _VALID_KNOWLEDGE_NOTE_RE, _VALID_ITEM_FILE_RE),
    )


def _validate_doc_path(ctx: RenderCtx, rel_path: str) -> Path | None:
    """Resolve a note-body link target against the conception tree."""
    return _safe_resolve(ctx, rel_path, strict=True)


_VALID_ITEM_DIR_RE = re.compile(r"^projects/\d{4}-\d{2}/\d{4}-\d{2}-\d{2}-[\w.-]+/?$")


def _validate_item_dir(ctx: RenderCtx, rel_path: str) -> Path | None:
    """Resolve a project-item folder path against the conception tree."""
    full = _safe_resolve(ctx, rel_path, (_VALID_ITEM_DIR_RE,), require_file=False)
    if full is None or not full.is_dir():
        return None
    return full


def validate_download_path(ctx: RenderCtx, rel_path: str) -> Path | None:
    return _safe_resolve(ctx, rel_path, (_VALID_DOWNLOAD_RE,))


def validate_asset_path(ctx: RenderCtx, rel_path: str) -> tuple[Path, str] | None:
    full = _safe_resolve(ctx, rel_path, (_VALID_ASSET_RE,))
    if full is None:
        return None
    ctype = _ASSET_CONTENT_TYPES.get(full.suffix.lower(), "application/octet-stream")
    return full, ctype


def validate_file_path(ctx: RenderCtx, rel_path: str) -> tuple[Path, str] | None:
    """Validate a raw-byte serve request for the /file endpoint."""
    full = validate_note_path(ctx, rel_path)
    if full is None:
        return None
    return full, _guess_content_type(full)


def _guess_content_type(path: Path) -> str:
    import mimetypes

    ext = path.suffix.lower()
    if ext in _ASSET_CONTENT_TYPES:
        return _ASSET_CONTENT_TYPES[ext]
    if ext == ".pdf":
        return "application/pdf"
    if ext == ".md":
        return "text/markdown; charset=utf-8"
    guess, _ = mimetypes.guess_type(path.name)
    return guess or "application/octet-stream"


def _validate_open_path(ctx: RenderCtx, path_str: str) -> Path | None:
    """Validate an absolute filesystem path against the workspace sandbox."""
    if not path_str or "\x00" in path_str:
        return None
    try:
        p = Path(path_str).resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if not p.is_dir():
        return None
    roots: list[Path] = []
    if ctx.workspace is not None:
        roots.append(ctx.workspace.resolve())
    if ctx.worktrees is not None:
        roots.append(ctx.worktrees.resolve())
    for root in roots:
        try:
            p.relative_to(root)
            return p
        except ValueError:
            continue
    return None
