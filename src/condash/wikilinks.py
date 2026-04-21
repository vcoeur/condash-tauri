"""Wikilink resolution and rendering for note bodies.

Markdown note bodies use Obsidian-style ``[[target]]`` / ``[[target|label]]``
links. :func:`_preprocess_wikilinks` rewrites every match into a raw-HTML
anchor before pandoc sees the text — pandoc's GFM reader passes raw HTML
through unchanged, so the two-stage pipeline stays single-pass.
"""

from __future__ import annotations

import html as html_mod
import re
from typing import TYPE_CHECKING

from .context import RenderCtx

if TYPE_CHECKING:
    from .cache import WorkspaceCache

_WIKILINK_RE = re.compile(r"\[\[([^\]\|\n]+?)(?:\|([^\]\n]+?))?\]\]")

# Match short item slugs ("my-project") vs directory-name slugs
# ("2026-04-16-my-project"). Used by the wikilink resolver.
_DATE_SLUG_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-")

_MONTH_DIR_RE = re.compile(r"^\d{4}-\d{2}$")

# Legacy kind prefixes inherited from the three-folder layout. Every item now
# lives under projects/, but users may still type [[incident/slug]] — all
# three prefixes resolve through the single tree.
_LEGACY_KIND_PREFIXES = {"project", "projects", "incident", "incidents", "document", "documents"}


def _find_item_dir(ctx: RenderCtx, target: str) -> str | None:
    """Look up a single item folder under ``projects/YYYY-MM/`` by name or short-name."""
    root = ctx.base_dir / "projects"
    if not root.is_dir():
        return None
    candidates: list[str] = []
    for month in root.iterdir():
        if not month.is_dir() or not _MONTH_DIR_RE.match(month.name):
            continue
        for item in month.iterdir():
            if not item.is_dir():
                continue
            if item.name == target or (_DATE_SLUG_RE.match(item.name) and item.name[11:] == target):
                candidates.append(f"{month.name}/{item.name}")
    if not candidates:
        return None
    return max(candidates)  # sorts by date thanks to the YYYY-MM[-DD] prefix


def _resolve_wikilink_uncached(ctx: RenderCtx, target: str) -> str | None:
    """Resolve a ``[[target]]`` to a conception-relative path, if it exists.

    This is the always-walk implementation. :class:`cache.WorkspaceCache`
    wraps it with memoization; callers without a cache should prefer
    :func:`_resolve_wikilink` so future caching layers can hook in.
    """
    target = target.strip()
    if not target:
        return None

    if "/" in target:
        head, _, tail = target.partition("/")
        if head in _LEGACY_KIND_PREFIXES:
            found = _find_item_dir(ctx, tail)
            if found:
                return f"projects/{found}/README.md"
        if head == "knowledge":
            path = target if target.endswith(".md") else f"{target}.md"
            if (ctx.base_dir / path).is_file():
                return path

    found = _find_item_dir(ctx, target)
    if found:
        return f"projects/{found}/README.md"

    for sub in ("topics", "external", "internal"):
        candidate = ctx.base_dir / "knowledge" / sub / f"{target}.md"
        if candidate.is_file():
            return f"knowledge/{sub}/{target}.md"
    for root_file in ("apps.md", "conventions.md"):
        if target == root_file.removesuffix(".md"):
            candidate = ctx.base_dir / "knowledge" / root_file
            if candidate.is_file():
                return f"knowledge/{root_file}"

    return None


def _resolve_wikilink(
    ctx: RenderCtx, target: str, cache: WorkspaceCache | None = None
) -> str | None:
    """Resolve a wikilink, using ``cache`` when supplied."""
    if cache is not None:
        return cache.resolve_wikilink(ctx, target)
    return _resolve_wikilink_uncached(ctx, target)


def _preprocess_wikilinks(ctx: RenderCtx, text: str, cache: WorkspaceCache | None = None) -> str:
    """Rewrite ``[[target]]`` / ``[[target|label]]`` into raw-HTML anchors."""

    def esc(s: str) -> str:
        return html_mod.escape(str(s))

    def repl(match: re.Match) -> str:
        target = match.group(1).strip()
        label = (match.group(2) or target).strip()
        resolved = _resolve_wikilink(ctx, target, cache=cache)
        if resolved:
            return (
                f'<a class="wikilink" href="{esc(resolved)}" '
                f'data-wikilink-target="{esc(target)}">{esc(label)}</a>'
            )
        return (
            f'<a class="wikilink-missing" '
            f'title="Wikilink target not found: {esc(target)}">{esc(label)}</a>'
        )

    return _WIKILINK_RE.sub(repl, text)
