"""Path validation for the conception directory tree.

Every HTTP-facing route that accepts a user-supplied path uses one of the
validators here to resolve it safely under ``BASE_DIR``. The shared
``_safe_resolve`` helper consolidates the "reject traversal + regex-gate +
resolve + relative_to + existence check" dance that every validator used
to duplicate inline.

``BASE_DIR`` lives in :mod:`condash.legacy` during the Phase 1 split; the
validators read it via ``from . import legacy`` as a transition. Phase 2
replaces that with an explicit ``RenderCtx`` parameter.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

_VALID_ITEM_PREFIX = (
    r"^(?:incidents|projects|documents)/(?:\d{4}-\d{2}/)?\d{4}-\d{2}-\d{2}-[\w.-]+/"
)

_VALID_PATH_RE = re.compile(_VALID_ITEM_PREFIX + r"README\.md$")

_VALID_DOWNLOAD_RE = re.compile(_VALID_ITEM_PREFIX + r"(?:notes/)?[\w.-]+\.pdf$")

_VALID_NOTE_RE = re.compile(_VALID_ITEM_PREFIX + r"(?:notes/[\w.-]+|README)\.md$")

# Knowledge pages live outside the date-prefixed item structure. Match
# `knowledge/<file>.md` at the root (apps.md, conventions.md) and
# `knowledge/<subdir>/<file>.md` (topics/, external/, internal/, …).
_VALID_KNOWLEDGE_NOTE_RE = re.compile(r"^knowledge/(?:[\w.-]+/)?[\w.-]+\.md$")

_VALID_ASSET_RE = re.compile(
    _VALID_ITEM_PREFIX + r"(?:notes/)?[\w./-]+\.(?:png|jpg|jpeg|gif|svg|webp)$",
    re.IGNORECASE,
)

# Any file directly under an item's `notes/` tree. Separate from the
# narrower image-only asset regex above so /file can serve PDFs, text,
# and misc binaries for in-modal preview.
_VALID_ITEM_FILE_RE = re.compile(_VALID_ITEM_PREFIX + r"notes/[\w./-]+$")

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
    rel_path: str,
    regexes: Sequence[re.Pattern] = (),
    *,
    require_file: bool = True,
    strict: bool = False,
) -> Path | None:
    """Resolve ``rel_path`` under BASE_DIR, rejecting anything outside the tree.

    - Reject empty input, NUL bytes, and any literal ``..`` substring.
    - If ``regexes`` is non-empty, the input must match at least one.
    - Resolve under ``BASE_DIR``; reject when ``resolve`` or ``relative_to`` fails.
    - If ``require_file`` is True, reject non-files; otherwise reject non-existent.
    - If ``strict`` is True, use ``resolve(strict=True)`` (rejects dangling symlinks).
    """
    if not rel_path or "\x00" in rel_path or ".." in rel_path:
        return None
    if regexes and not any(p.match(rel_path) for p in regexes):
        return None
    from . import legacy

    base = legacy.BASE_DIR
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


def _validate_path(rel_path: str) -> Path | None:
    """Validate an item-README path; returns the absolute path on success."""
    return _safe_resolve(rel_path, (_VALID_PATH_RE,), require_file=False)


def validate_note_path(rel_path: str) -> Path | None:
    """Public: validate a note/README/knowledge/notes-file path.

    Accepts: item READMEs and any file under ``<item>/notes/**``, plus
    pages under ``knowledge/``. Paths outside conception are rejected.
    """
    return _safe_resolve(
        rel_path,
        (_VALID_NOTE_RE, _VALID_KNOWLEDGE_NOTE_RE, _VALID_ITEM_FILE_RE),
    )


def _validate_doc_path(rel_path: str) -> Path | None:
    """Resolve a note-body link target against the conception tree.

    Rejects anything outside ``BASE_DIR`` (symlink-safe) or any non-existent
    file. Returns the resolved absolute path on success, ``None`` otherwise.
    """
    return _safe_resolve(rel_path, strict=True)


def validate_download_path(rel_path: str) -> Path | None:
    return _safe_resolve(rel_path, (_VALID_DOWNLOAD_RE,))


def validate_asset_path(rel_path: str) -> tuple[Path, str] | None:
    full = _safe_resolve(rel_path, (_VALID_ASSET_RE,))
    if full is None:
        return None
    ctype = _ASSET_CONTENT_TYPES.get(full.suffix.lower(), "application/octet-stream")
    return full, ctype


def validate_file_path(rel_path: str) -> tuple[Path, str] | None:
    """Validate a raw-byte serve request for the /file endpoint.

    Same acceptance set as :func:`validate_note_path` (note/README/asset
    files under items, plus pages under ``knowledge/``). Returns the absolute
    path and a best-effort content type.
    """
    full = validate_note_path(rel_path)
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


def _validate_open_path(path_str: str) -> Path | None:
    """Validate an absolute filesystem path against the workspace sandbox.

    Accepts only directories inside ``_WORKSPACE`` or ``_WORKTREES``. Used
    by the "open in IDE" action to stop a crafted URL from launching an
    arbitrary binary against arbitrary paths.
    """
    if not path_str or "\x00" in path_str:
        return None
    try:
        p = Path(path_str).resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if not p.is_dir():
        return None
    from . import legacy

    roots: list[Path] = []
    if legacy._WORKSPACE is not None:
        roots.append(legacy._WORKSPACE.resolve())
    if legacy._WORKTREES is not None:
        roots.append(legacy._WORKTREES.resolve())
    for root in roots:
        try:
            p.relative_to(root)
            return p
        except ValueError:
            continue
    return None
