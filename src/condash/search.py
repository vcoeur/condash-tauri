"""History-tab search backend.

The in-page history filter (``dashboard.html::_filterTree``) only inspects
each card's rendered ``textContent`` — effectively the project's title, slug,
kind and status. :func:`search_items` broadens the corpus to every project's
README body, note/text-file content and filenames, returning per-project hits
with highlighted snippets. The route that exposes this is
``GET /search-history`` in :mod:`condash.app`.
"""

from __future__ import annotations

import html as html_mod
import logging
import re
from pathlib import Path

from .context import RenderCtx

log = logging.getLogger(__name__)

# File extensions whose content is searched. Filenames of any extension are
# searched regardless.
_CONTENT_EXTS = {".md", ".txt", ".yml", ".yaml"}

# Skip content-indexing files larger than this — keeps a stray large log or
# exported PDF-text from dominating search cost.
_MAX_CONTENT_BYTES = 512 * 1024

# Per-source ranking weights. Matches in the project header (title, slug,
# apps) should dominate deep note-body matches; filename hits rank between
# header and content.
_SOURCE_WEIGHTS = {"title": 4, "filename": 3, "readme": 2, "note": 2, "file": 1}

_SNIPPET_RADIUS = 60


def _tokenise(q: str) -> list[str]:
    """Lower-case, whitespace-split, dedupe preserving first occurrence."""
    seen: set[str] = set()
    out: list[str] = []
    for tok in (q or "").lower().split():
        if tok and tok not in seen:
            seen.add(tok)
            out.append(tok)
    return out


def _build_snippet(text: str, tokens: list[str], radius: int = _SNIPPET_RADIUS) -> str:
    """Return HTML-escaped snippet with tokens wrapped in ``<mark>``.

    Picks the earliest token hit as the anchor, expands ``radius`` chars on
    each side, snaps to word boundaries, collapses whitespace. Returns an
    empty string when no token matches.
    """
    if not text or not tokens:
        return ""
    hay = text.lower()
    pos = -1
    hit_len = 0
    for tok in tokens:
        p = hay.find(tok)
        if p < 0:
            continue
        if pos < 0 or p < pos:
            pos = p
            hit_len = len(tok)
    if pos < 0:
        return ""
    start = max(0, pos - radius)
    end = min(len(text), pos + hit_len + radius)
    if start > 0:
        ws = text.rfind(" ", 0, start)
        if 0 <= start - ws < 20:
            start = ws + 1
    if end < len(text):
        we = text.find(" ", end)
        if we >= 0 and we - end < 20:
            end = we
    frag = re.sub(r"\s+", " ", text[start:end]).strip()
    escaped = html_mod.escape(frag)
    pattern = re.compile("(" + "|".join(re.escape(t) for t in tokens) + ")", re.IGNORECASE)
    marked = pattern.sub(r"<mark>\1</mark>", escaped)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{marked}{suffix}"


def _read_text(path: Path) -> str | None:
    """Read ``path`` as UTF-8 text, or return ``None`` on any failure mode."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if len(data) > _MAX_CONTENT_BYTES:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _readme_body(text: str) -> str:
    """Drop the README header block (title + metadata lines) from ``text``.

    The header fields are indexed separately via the parsed item, so the
    README contribution is just the ## Goal / ## Scope / … prose body.
    """
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("## "):
            return "\n".join(lines[i:])
    return ""


def _iter_item_files(item_dir: Path):
    """Yield ``(rel_path, abs_path, is_content)`` for each non-hidden file.

    The top-level ``README.md`` is skipped because its body is indexed
    separately. Hidden entries (names starting with ``.``) are skipped at
    every depth.
    """
    for path in sorted(item_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(item_dir)
        if any(part.startswith(".") for part in rel.parts):
            continue
        if len(rel.parts) == 1 and rel.parts[0] == "README.md":
            continue
        yield rel, path, path.suffix.lower() in _CONTENT_EXTS


_STATUS_TO_SUBTAB = {
    "now": "current",
    "review": "current",
    "soon": "next",
    "later": "next",
    "backlog": "backlog",
    "done": "done",
}


def _status_to_subtab(status: str) -> str:
    return _STATUS_TO_SUBTAB.get(status, "current")


def search_items(ctx: RenderCtx, items: list[dict], query: str) -> list[dict]:
    """Return per-project search results matching ``query``.

    Each result is a dict with ``slug``, ``title``, ``kind``, ``status``,
    ``subtab`` (Projects sub-tab that holds the card), ``path`` (README rel),
    ``month`` (``YYYY-MM``), and a ``hits`` list of
    ``{source, label, path, snippet}`` entries. Results are token-AND:
    every token must appear somewhere in the project's combined corpus.
    Empty or whitespace-only queries return ``[]``.
    """
    tokens = _tokenise(query)
    if not tokens:
        return []

    results: list[tuple[int, dict]] = []
    base_dir = ctx.base_dir

    for item in items:
        item_rel = Path(item["path"]).parent
        item_dir = base_dir / item_rel
        if not item_dir.is_dir():
            continue

        status = item.get("priority", "")
        header_text = " ".join(
            [
                item.get("title", ""),
                item.get("slug", ""),
                item.get("kind", ""),
                status,
                " ".join(item.get("apps", []) or []),
            ]
        )
        header_lower = header_text.lower()

        readme_body_text = ""
        readme_path = item_dir / "README.md"
        if readme_path.is_file():
            raw = _read_text(readme_path)
            if raw:
                readme_body_text = _readme_body(raw)

        per_file: list[tuple[Path, str, str | None]] = []
        for rel, abs_path, is_content in _iter_item_files(item_dir):
            text = _read_text(abs_path) if is_content else None
            source = "note" if rel.parts and rel.parts[0] == "notes" else "file"
            per_file.append((rel, source, text))

        matched: set[str] = set()
        for t in tokens:
            if t in header_lower:
                matched.add(t)
        if readme_body_text:
            rl = readme_body_text.lower()
            for t in tokens:
                if t in rl:
                    matched.add(t)
        for rel, _src, text in per_file:
            rel_lower = str(rel).lower()
            for t in tokens:
                if t in rel_lower:
                    matched.add(t)
            if text:
                tl = text.lower()
                for t in tokens:
                    if t in tl:
                        matched.add(t)

        if len(matched) < len(tokens):
            continue

        hits: list[dict] = []
        hit_paths_with_content: set[str] = set()
        readme_rel = str(item_rel / "README.md")

        if any(t in header_lower for t in tokens):
            hits.append(
                {
                    "source": "title",
                    "label": "Title",
                    "path": readme_rel,
                    "snippet": _build_snippet(header_text, tokens),
                }
            )

        if readme_body_text and any(t in readme_body_text.lower() for t in tokens):
            snippet = _build_snippet(readme_body_text, tokens)
            if snippet:
                hits.append(
                    {
                        "source": "readme",
                        "label": "README",
                        "path": readme_rel,
                        "snippet": snippet,
                    }
                )
                hit_paths_with_content.add(readme_rel)

        for rel, source, text in per_file:
            if text is None:
                continue
            tl = text.lower()
            if not any(t in tl for t in tokens):
                continue
            file_rel = str(item_rel / rel)
            hits.append(
                {
                    "source": source,
                    "label": str(rel),
                    "path": file_rel,
                    "snippet": _build_snippet(text, tokens),
                }
            )
            hit_paths_with_content.add(file_rel)

        # Filename-only hits — skip when the same file already has a content hit.
        for rel, _source, _text in per_file:
            file_rel = str(item_rel / rel)
            if file_rel in hit_paths_with_content:
                continue
            rel_str = str(rel)
            if not any(t in rel_str.lower() for t in tokens):
                continue
            hits.append(
                {
                    "source": "filename",
                    "label": rel_str,
                    "path": file_rel,
                    "snippet": _build_snippet(rel_str, tokens),
                }
            )

        if not hits:
            continue

        score = 0
        for hit in hits:
            hay = (str(hit.get("snippet") or "") + " " + hit["label"]).lower()
            token_count = sum(hay.count(t) for t in tokens)
            score += _SOURCE_WEIGHTS.get(hit["source"], 1) * max(1, token_count)

        parts = Path(item["path"]).parts
        month = parts[1] if len(parts) >= 2 else ""

        results.append(
            (
                score,
                {
                    "slug": item["slug"],
                    "title": item["title"],
                    "kind": item["kind"],
                    "status": status,
                    "subtab": _status_to_subtab(status),
                    "path": item["path"],
                    "month": month,
                    "hits": hits,
                },
            )
        )

    # Score DESC, then slug DESC (newest-first tie-break) — slugs start with
    # ``YYYY-MM-DD`` so string sort works.
    results.sort(key=lambda x: (x[0], x[1]["slug"]), reverse=True)
    return [r[1] for r in results]
