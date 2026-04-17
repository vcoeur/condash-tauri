"""Wikilink resolution and rendering for note bodies.

Markdown note bodies use Obsidian-style ``[[target]]`` / ``[[target|label]]``
links. :func:`_preprocess_wikilinks` rewrites every match into a raw-HTML
anchor before pandoc sees the text — pandoc's GFM reader passes raw HTML
through unchanged, so the two-stage pipeline stays single-pass.
"""

from __future__ import annotations

import html as html_mod
import re

from .context import RenderCtx

_WIKILINK_RE = re.compile(r"\[\[([^\]\|\n]+?)(?:\|([^\]\n]+?))?\]\]")

# Match short item slugs ("my-project") vs directory-name slugs
# ("2026-04-16-my-project"). Used by the wikilink resolver.
_DATE_SLUG_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-")

_ITEM_TYPE_NORMAL = {
    "project": "projects",
    "projects": "projects",
    "incident": "incidents",
    "incidents": "incidents",
    "document": "documents",
    "documents": "documents",
}

_MONTH_DIR_RE = re.compile(r"^\d{4}-\d{2}$")


def _find_item_dir(ctx: RenderCtx, type_plural: str, target: str) -> str | None:
    """Look up a single item directory by exact name or short-name match."""
    root = ctx.base_dir / type_plural
    if not root.is_dir():
        return None
    candidates: list[str] = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        if child.name == target or (_DATE_SLUG_RE.match(child.name) and child.name[11:] == target):
            candidates.append(child.name)
        if _MONTH_DIR_RE.match(child.name):
            for grand in child.iterdir():
                if not grand.is_dir():
                    continue
                if grand.name == target or (
                    _DATE_SLUG_RE.match(grand.name) and grand.name[11:] == target
                ):
                    candidates.append(f"{child.name}/{grand.name}")
    if not candidates:
        return None
    return max(candidates)  # sorts by date thanks to the YYYY-MM[-DD] prefix


def _resolve_wikilink(ctx: RenderCtx, target: str) -> str | None:
    """Resolve a ``[[target]]`` to a conception-relative path, if it exists."""
    target = target.strip()
    if not target:
        return None

    if "/" in target:
        head, _, tail = target.partition("/")
        type_pl = _ITEM_TYPE_NORMAL.get(head)
        if type_pl:
            found = _find_item_dir(ctx, type_pl, tail)
            if found:
                return f"{type_pl}/{found}/README.md"
        if head == "knowledge":
            path = target if target.endswith(".md") else f"{target}.md"
            if (ctx.base_dir / path).is_file():
                return path

    for type_pl in ("projects", "incidents", "documents"):
        found = _find_item_dir(ctx, type_pl, target)
        if found:
            return f"{type_pl}/{found}/README.md"

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


def _preprocess_wikilinks(ctx: RenderCtx, text: str) -> str:
    """Rewrite ``[[target]]`` / ``[[target|label]]`` into raw-HTML anchors."""

    def esc(s: str) -> str:
        return html_mod.escape(str(s))

    def repl(match: re.Match) -> str:
        target = match.group(1).strip()
        label = (match.group(2) or target).strip()
        resolved = _resolve_wikilink(ctx, target)
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
