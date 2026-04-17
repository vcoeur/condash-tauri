"""Ported from ``conception/tools/dashboard.py``.

This module keeps the original parser, renderers, mutation helpers, and
HTTP surface semantics verbatim. The only differences from the upstream
file are:

* ``BASE_DIR`` is no longer hard-coded from ``__file__``; it is set by
  :func:`init` from the ``CondashConfig``.
* The HTML template lives inside the ``condash`` package as a resource
  and is loaded via ``importlib.resources``.
* The repositories list (primary / secondary) comes from the config, not
  from a YAML file next to the script.
* ``BaseHTTPRequestHandler`` / ``DashboardServer`` / ``main`` are removed —
  the web surface now lives in :mod:`condash.app` on top of NiceGUI /
  FastAPI. All the helpers they called (``_toggle_checkbox``,
  ``_add_step``, ``_render_note``, ``_tidy``, etc.) are still exported
  here unchanged so ``app.py`` can call them directly.
"""

from __future__ import annotations

import html as html_mod
import json
import logging
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime
from importlib.resources import files as _package_files
from itertools import groupby
from pathlib import Path
from typing import Any

from .git_scan import (  # noqa: F401 — re-exported for backward compat during the Phase 1 split
    _collect_git_repos,
    _git_cache,
    _git_fingerprint,
    _git_status,
    _git_worktrees,
    _is_sandbox_stub,
    _load_repository_structure,
    _resolve_submodules,
)
from .parser import (  # noqa: F401 — re-exported for backward compat during the Phase 1 split
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
from .paths import (  # noqa: F401 — re-exported for backward compat during the Phase 1 split
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
from .wikilinks import (  # noqa: F401 — re-exported for backward compat during the Phase 1 split
    _DATE_SLUG_RE,
    _ITEM_TYPE_NORMAL,
    _WIKILINK_RE,
    _find_item_dir,
    _preprocess_wikilinks,
    _resolve_wikilink,
)

log = logging.getLogger(__name__)

# Populated by init() before any rendering / mutation function is called.
BASE_DIR: Path = Path("/nonexistent")

# Populated by init() from CondashConfig.workspace_path. ``None`` means the
# user did not configure a code workspace, and the dashboard's repo strip is
# suppressed entirely.
_WORKSPACE: Path | None = None

# Populated by init() from CondashConfig.worktrees_path. ``None`` means the
# user has no extra git-worktrees sandbox; the "open in IDE" action then
# only accepts paths inside ``_WORKSPACE``.
_WORKTREES: Path | None = None

# Populated by init() from CondashConfig.repositories_{primary,secondary}.
_REPO_STRUCTURE: list[tuple[str, list[tuple[str, list[str]]]]] = []

# Populated by init() from CondashConfig.open_with — the three vendor-neutral
# launcher slots used by the per-repo action buttons. Defaults to an empty
# dict; render_git_actions falls back to slot-key-as-title when missing.
_OPEN_WITH: dict[str, Any] = {}

# Populated by init() from CondashConfig.pdf_viewer. Fallback chain of
# shell-style commands tried for *.pdf files before falling back to the OS
# default opener. Empty list → current behaviour (xdg-open / open / startfile).
_PDF_VIEWER: list[str] = []


def init(cfg) -> None:
    """Wire runtime configuration into this module.

    Must be called exactly once before any other function. Accepts a
    :class:`condash.config.CondashConfig` (typed as ``Any`` here to avoid
    a circular import at module load).
    """
    global BASE_DIR, _WORKSPACE, _WORKTREES, _REPO_STRUCTURE, _OPEN_WITH, _PDF_VIEWER
    if cfg.conception_path is None:
        # Sentinel path that .is_dir() returns False for — collect_items
        # short-circuits to an empty list and the dashboard renders the
        # setup prompt.
        BASE_DIR = Path("/nonexistent")
    else:
        BASE_DIR = Path(cfg.conception_path).expanduser().resolve()
    _WORKSPACE = (
        Path(cfg.workspace_path).expanduser().resolve() if cfg.workspace_path is not None else None
    )
    _WORKTREES = (
        Path(cfg.worktrees_path).expanduser().resolve() if cfg.worktrees_path is not None else None
    )
    submodules = getattr(cfg, "repo_submodules", None) or {}
    _REPO_STRUCTURE = [
        (
            "Primary",
            [(name, list(submodules.get(name) or [])) for name in cfg.repositories_primary],
        ),
        (
            "Secondary",
            [(name, list(submodules.get(name) or [])) for name in cfg.repositories_secondary],
        ),
    ]
    _OPEN_WITH = dict(cfg.open_with or {})
    _PDF_VIEWER = list(getattr(cfg, "pdf_viewer", None) or [])


def _template_path() -> Path:
    return Path(str(_package_files("condash") / "assets" / "dashboard.html"))


def _favicon_bytes() -> bytes | None:
    try:
        return (_package_files("condash") / "assets" / "favicon.svg").read_bytes()
    except FileNotFoundError:
        return None


def h(text):
    """HTML-escape."""
    return html_mod.escape(str(text))


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def _render_knowledge(root: dict | None) -> str:
    """Render the knowledge tree returned by ``collect_knowledge``."""
    if root is None or root["count"] == 0:
        return '<p class="note-empty">No <code>knowledge/</code> tree under the configured conception path.</p>'
    parts = ['<div class="knowledge-panel">']
    # Root index sits above all groups as a panel-level badge — it
    # describes the whole tree, not any one subdir.
    if root["index"]:
        parts.append(_render_index_badge(root["index"], top_level=True))
    if root["body"]:
        parts.append('<div class="knowledge-list">')
        for e in root["body"]:
            parts.append(_render_knowledge_card(e))
        parts.append("</div>")
    for child in root["children"]:
        parts.append(_render_knowledge_group(child))
    parts.append("</div>")
    return "".join(parts)


def _render_knowledge_group(node: dict) -> str:
    """Render one directory as a collapsible group, recursing into subdirs.

    Uses ``<details>`` / ``<summary>`` so the open state is browser-native
    (keyboard + a11y for free) and starts closed by default. The chevron
    span is animated by CSS via ``details[open]``.
    """
    parts = ['<details class="knowledge-group">']
    parts.append('<summary class="knowledge-group-heading">')
    parts.append('<span class="knowledge-chevron" aria-hidden="true">&#9656;</span>')
    parts.append(f'<span class="knowledge-group-name">{h(node["label"])}</span>')
    parts.append(f'<span class="knowledge-count">({node["count"]})</span>')
    if node["index"]:
        parts.append(_render_index_badge(node["index"], top_level=False))
    parts.append("</summary>")
    if node["body"]:
        parts.append('<div class="knowledge-list">')
        for e in node["body"]:
            parts.append(_render_knowledge_card(e))
        parts.append("</div>")
    for child in node["children"]:
        parts.append(_render_knowledge_group(child))
    parts.append("</details>")
    return "".join(parts)


def _render_knowledge_card(e: dict) -> str:
    js_path = json.dumps(e["path"]).replace("'", "\\'").replace('"', "'")
    js_title = json.dumps(e["title"]).replace("'", "\\'").replace('"', "'")
    desc_html = f'<div class="knowledge-desc">{h(e["desc"])}</div>' if e["desc"] else ""
    return (
        f'<div class="knowledge-card" '
        f'onclick="openNotePreview({js_path},{js_title})">'
        f'<div class="knowledge-title">{h(e["title"])}</div>'
        f"{desc_html}"
        f'<div class="knowledge-path">{h(e["path"])}</div>'
        f"</div>"
    )


def _render_index_badge(idx: dict, top_level: bool) -> str:
    """Index files become a clickable pill, not a card.

    The non-top-level badge sits inside a ``<summary>`` — stop the click
    from bubbling up so opening the index doesn't also toggle the parent
    group's open state.
    """
    js_path = json.dumps(idx["path"]).replace("'", "\\'").replace('"', "'")
    js_title = json.dumps(idx["title"]).replace("'", "\\'").replace('"', "'")
    cls = "knowledge-index-badge" + (" knowledge-index-top" if top_level else "")
    return (
        f'<a class="{cls}" '
        f'onclick="event.stopPropagation();openNotePreview({js_path},{js_title})" '
        f'title="{h(idx["path"])}">index</a>'
    )


# ---------------------------------------------------------------------------
# Card rendering
# ---------------------------------------------------------------------------


def _render_step(item, file_path):
    status = item["status"]
    js_file = json.dumps(file_path).replace("'", "\\'").replace('"', "'")
    dot_char = {"done": "\u2713", "progress": "~", "abandoned": "\u2014", "open": ""}.get(
        status, ""
    )
    return (
        f'<div class="step {status}" draggable="true" '
        f'data-file="{h(file_path)}" data-line="{item["line"]}" '
        f'ondragstart="stepDragStart(event)" ondragend="stepDragEnd(event)" '
        f'ondragover="stepDragOver(event)">'
        f'<span class="drag-handle">\u283f</span>'
        f'<span class="status-dot status-{status}" '
        f'onmousedown="event.stopPropagation();event.preventDefault()" '
        f"onclick=\"var s=this.closest('.step');cycle({js_file},+s.dataset.line,s)\">{dot_char}</span>"
        f'<span class="text" onmousedown="event.stopPropagation()" '
        f'onclick="event.stopPropagation();startEditText(this)">{h(item["text"])}</span>'
        f'<button class="remove-btn" '
        f'onmousedown="event.stopPropagation();event.preventDefault()" '
        f"onclick=\"var s=this.closest('.step');removeStep({js_file},+s.dataset.line,this)\">\u00d7</button>"
        f"</div>"
    )


def _render_group(heading, items, file_path):
    done = sum(1 for it in items if it["status"] == "done")
    total = len(items)
    all_done = total > 0 and done == total
    open_cls = "" if all_done else "open"
    display = "none" if all_done else "block"
    items_html = "\n".join(_render_step(it, file_path) for it in items)
    js_file = json.dumps(file_path).replace("'", "\\'").replace('"', "'")
    js_heading = json.dumps(heading).replace("'", "\\'").replace('"', "'")
    add_html = (
        f'<div class="add-row">'
        f'<input type="text" placeholder="Add task\u2026" '
        f"onkeydown=\"if(event.key==='Enter')addStep({js_file},{js_heading},this)\">"
        f'<button onclick="addStep({js_file},{js_heading},this.previousElementSibling)">+</button>'
        f"</div>"
    )
    return (
        f'<div class="sec-group">'
        f'<div class="sec-heading {open_cls}" onclick="toggleSection(this)">'
        f'{h(heading)} <span class="sec-count">({done}/{total})</span></div>'
        f'<div class="sec-items" style="display:{display}">'
        f"{items_html}"
        f"{add_html}</div></div>"
    )


def _render_readme_link(item):
    js_path = json.dumps(item["path"]).replace("'", "\\'").replace('"', "'")
    js_title = json.dumps(item["title"]).replace("'", "\\'").replace('"', "'")
    return (
        f'<div class="readme-preview" '
        f'onclick="openNotePreview({js_path},{js_title})">'
        f"\u2261 README</div>"
    )


def _render_notes(notes, readme_rel: str | None = None):
    """Render the notes block for an item card.

    The block is always emitted (even empty) so the user has a place to
    click ``+`` and create the first note. ``readme_rel`` is the item's
    README.md relative path; it seeds the create-note POST target.
    """
    items_html = ""
    for n in notes:
        js_path = json.dumps(n["path"]).replace("'", "\\'").replace('"', "'")
        label = n["name"][:-3] if n["name"].endswith(".md") else n["name"]
        kind = n.get("kind", "md")
        items_html += (
            f'<div class="note-item" data-kind="{h(kind)}" '
            f"onclick=\"openNotePreview({js_path},'{h(n['name'])}')\">"
            f"{h(label)}</div>"
        )
    count = len(notes)
    create_btn = ""
    if readme_rel:
        js_readme = json.dumps(readme_rel).replace("'", "\\'").replace('"', "'")
        create_btn = (
            f'<button class="notes-new-btn" title="New note" '
            f'onclick="event.stopPropagation();createNoteFor({js_readme})">+</button>'
        )
    empty_class = " is-empty" if not notes else ""
    return (
        f'<div class="notes-block{empty_class}">'
        f'<div class="notes-heading" onclick="toggleNotes(this)">'
        f'Notes <span class="notes-count">({count})</span>'
        f"{create_btn}</div>"
        f'<div class="notes-list" style="display:none">{items_html}</div>'
        f"</div>"
    )


def _render_deliverables(deliverables):
    if not deliverables:
        return ""
    links = []
    for d in deliverables:
        # target="_blank" routed through pywebview is flaky — some backends
        # open the system browser on 127.0.0.1:<port>/download/… and fail to
        # render. Route through /open-doc so the OS default PDF viewer opens
        # the local file directly, same as note-body non-md links.
        js_path = json.dumps(d["full_path"]).replace("'", "\\'").replace('"', "'")
        title = f' title="{h(d["desc"])}"' if d["desc"] else ""
        desc = f' <span class="dlv-desc">— {h(d["desc"])}</span>' if d["desc"] else ""
        links.append(
            f'<a class="dlv-link" href="#" '
            f'onclick="event.preventDefault();event.stopPropagation();'
            f'openDeliverable({js_path});return false;"'
            f"{title}>"
            f"\u2913 {h(d['label'])}</a>{desc}"
        )
    items_html = "".join(f'<div class="dlv-item">{lnk}</div>' for lnk in links)
    return (
        f'<div class="deliverables"><div class="dlv-heading">Deliverables</div>{items_html}</div>'
    )


def _render_card(item):
    kind = item["kind"]
    js_file = json.dumps(item["path"]).replace("'", "\\'").replace('"', "'")
    pri = item["priority"]
    pri_options = "".join(
        f'<span class="pri-option pri-{p}" '
        f"onclick=\"event.stopPropagation();pickPriority({js_file},'{p}',this.closest('.pri-wrap'))\">{p}</span>"
        for p in PRIORITIES
    )
    priority_select = (
        f'<span class="pri-wrap" onclick="event.stopPropagation();togglePriMenu(this)">'
        f'<span class="pri-current pri-{pri}">{pri}</span>'
        f'<span class="pri-menu">{pri_options}</span></span>'
    )

    progress = ""
    if item["total"] > 0:
        pct = round(item["done"] / item["total"] * 100)
        fill_var = "--progress-done" if pct == 100 else "--progress-fill"
        progress = (
            f' <span class="progress-text">{item["done"]}/{item["total"]} '
            f'<span class="progress-bar" style="background:var(--progress-track)">'
            f'<span class="progress-fill" style="width:{pct}%;background:var({fill_var})"></span>'
            f"</span></span>"
        )

    apps_html = " ".join(f'<span class="pill">{h(a)}</span>' for a in item["apps"])
    apps_div = f'<div class="card-apps">{apps_html}</div>' if apps_html else ""

    sections_html = "\n".join(
        _render_group(s["heading"], s["items"], item["path"]) for s in item["sections"]
    )

    deliverables_html = _render_deliverables(item.get("deliverables", []))
    readme_link_html = _render_readme_link(item)
    notes_html = _render_notes(item.get("notes", []), readme_rel=item.get("path"))

    summary_html = f'<p class="summary">{h(item["summary"])}</p>' if item["summary"] else ""

    pdf_badge = (
        '<span class="dlv-icon" title="Has deliverables">PDF</span>'
        if item.get("deliverables")
        else ""
    )

    return (
        f'<div class="card collapsed" id="{item["slug"]}" data-kind="{item["kind"]}" data-priority="{pri}">'
        f'<div class="card-header">'
        f'<div class="card-header-left" onclick="toggleCard(this.closest(\'.card\'))">'
        f'<span class="kind-prefix kind-{kind}">{kind}</span>'
        f'<span class="card-title">{h(item["title"])}</span>'
        f"{pdf_badge}</div>"
        f'<div class="card-header-right">'
        f"{progress} {priority_select} "
        f'<span class="date">{h(item["date"])}</span></div></div>'
        f'<div class="card-body">'
        f'<div class="card-left">'
        f"{apps_div}"
        f"{summary_html}"
        f"{readme_link_html}"
        f"{notes_html}"
        f"{deliverables_html}"
        f"</div>"
        f'<div class="card-right">'
        f'<div class="sections">{sections_html}</div>'
        f"</div></div>"
        f"</div>"
    )


_ICON_SVGS = {
    # Generic "code editor window" — title bar with two horizontal code lines.
    "main_ide": (
        '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" '
        'stroke="currentColor" stroke-width="2.2" stroke-linecap="round" '
        'stroke-linejoin="round" aria-hidden="true">'
        '<rect x="3" y="4" width="18" height="16" rx="2"/>'
        '<line x1="3" y1="9" x2="21" y2="9"/>'
        '<line x1="7" y1="14" x2="13" y2="14"/>'
        '<line x1="7" y1="17" x2="11" y2="17"/></svg>'
    ),
    # Generic "code" chevrons — < / >.
    "secondary_ide": (
        '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" '
        'stroke="currentColor" stroke-width="2.4" stroke-linecap="round" '
        'stroke-linejoin="round" aria-hidden="true">'
        '<polyline points="16 18 22 12 16 6"/>'
        '<polyline points="8 6 2 12 8 18"/></svg>'
    ),
    # Generic "terminal" — prompt arrow + cursor underline.
    "terminal": (
        '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" '
        'stroke="currentColor" stroke-width="2.4" stroke-linecap="round" '
        'stroke-linejoin="round" aria-hidden="true">'
        '<polyline points="4 17 10 11 4 5"/>'
        '<line x1="12" y1="19" x2="20" y2="19"/></svg>'
    ),
    # "Integrated terminal" — window frame with prompt arrow + cursor
    # inside, signalling "open terminal inside the dashboard" rather
    # than the external-terminal slot above.
    "integrated_terminal": (
        '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" '
        'stroke="currentColor" stroke-width="2.2" stroke-linecap="round" '
        'stroke-linejoin="round" aria-hidden="true">'
        '<rect x="3" y="4" width="18" height="16" rx="2"/>'
        '<polyline points="7 11 10 14 7 17"/>'
        '<line x1="12" y1="17" x2="16" y2="17"/></svg>'
    ),
}


def _render_git_actions(path):
    js_path = json.dumps(path).replace("'", "\\'").replace('"', "'")
    items_html: list[str] = []
    for slot_key in ("main_ide", "secondary_ide", "terminal"):
        slot = _OPEN_WITH.get(slot_key)
        title = slot.label if slot is not None else slot_key
        items_html.append(
            f'<button class="git-action-btn git-action-{slot_key}" '
            f'title="{h(title)}" aria-label="{h(title)}" '
            f"onclick=\"openPath(event,{js_path},'{slot_key}')\">"
            f"{_ICON_SVGS[slot_key]}</button>"
        )
    integrated_title = "Open in integrated terminal"
    items_html.append(
        f'<button class="git-action-btn git-action-integrated-terminal" '
        f'title="{h(integrated_title)}" aria-label="{h(integrated_title)}" '
        f'onclick="openInTerminal(event,{js_path})">'
        f"{_ICON_SVGS['integrated_terminal']}</button>"
    )
    return f'<div class="git-actions">{"".join(items_html)}</div>'


def _render_submodule_rows(submodules, worktree=False):
    """Render subrepo rows at the same visual size as parent repos.

    The subrepos live inside a small grouping container (`.git-subgroup`)
    under their parent repo / worktree so the relationship is still clear
    — collapsible via the same toggle — but each row is a full-size
    `.git-row` with its own action buttons, not an indented half-height
    sub-row.
    """
    if not submodules:
        return ""
    rows = []
    for sub in submodules:
        sub_actions = _render_git_actions(sub["path"])
        count = sub.get("changed", 0)
        dirty_cls = " git-dirty" if count else ""
        badge = (
            f'<span class="git-changes">{count} changed</span>'
            if count
            else '<span class="git-clean">\u2713</span>'
        )
        rows.append(
            f'<div class="git-row{dirty_cls}" title="{h(sub["path"])}">'
            f"{sub_actions}"
            f'<span class="git-name">{h(sub["name"])}</span>'
            f'<span class="git-branch"></span>'
            f'<span class="git-status">{badge}</span>'
            f'<span class="git-spacer"></span></div>'
        )
    inner = "\n".join(rows)
    scope = "worktree" if worktree else "repo"
    return (
        f'<div class="git-subgroup git-subgroup-{scope} collapsed">'
        f'<div class="git-subgroup-label">Subrepos</div>'
        f"{inner}"
        f"</div>"
    )


def _render_git_repos(groups):
    if not groups:
        return ""
    out = []
    for label, repos in groups:
        out.append('<div class="git-group">')
        out.append(f'<div class="git-group-header">{h(label)}</div>')
        out.append('<div class="git-group-body">')
        chevron = '<span class="git-chevron">\u25b6</span>'
        for r in repos:
            out.append('<div class="git-repo">')
            dirty_cls = " git-dirty" if r["dirty"] else ""
            badge = (
                f'<span class="git-changes">{r["changed"]} changed</span>'
                if r["dirty"]
                else '<span class="git-clean">\u2713</span>'
            )
            actions = _render_git_actions(r["path"])
            has_subs = bool(r.get("submodules"))
            toggle_cls = " git-row-collapsible" if has_subs else ""
            toggle_attr = ' onclick="toggleSubmodules(this)"' if has_subs else ""
            chev = chevron if has_subs else ""
            out.append(
                f'<div class="git-row{dirty_cls}{toggle_cls}"{toggle_attr}>'
                f"{actions}"
                f'<span class="git-name">{chev}{h(r["name"])}</span>'
                f'<span class="git-branch">{h(r["branch"])}</span>'
                f'<span class="git-status">{badge}</span>'
                f'<span class="git-spacer"></span></div>'
            )
            sub_html = _render_submodule_rows(r.get("submodules") or [])
            if sub_html:
                out.append(sub_html)
            for wt in r.get("worktrees", []):
                wt_dirty_cls = " git-dirty" if wt["dirty"] else ""
                wt_badge = (
                    f'<span class="git-changes">{wt["changed"]} changed</span>'
                    if wt["dirty"]
                    else '<span class="git-clean">\u2713</span>'
                )
                wt_actions = _render_git_actions(wt["path"])
                wt_has_subs = bool(wt.get("submodules"))
                wt_toggle_cls = " git-row-collapsible" if wt_has_subs else ""
                wt_toggle_attr = ' onclick="toggleSubmodules(this)"' if wt_has_subs else ""
                wt_chev = chevron if wt_has_subs else ""
                out.append(
                    f'<div class="git-row git-worktree{wt_dirty_cls}{wt_toggle_cls}" '
                    f'title="{h(wt["path"])}"{wt_toggle_attr}>'
                    f"{wt_actions}"
                    f'<span class="git-name">{wt_chev}\u21b3 {h(wt["key"])}</span>'
                    f'<span class="git-branch">{h(wt["branch"])}</span>'
                    f'<span class="git-status">{wt_badge}</span>'
                    f'<span class="git-spacer"></span></div>'
                )
                wt_sub_html = _render_submodule_rows(wt.get("submodules") or [], worktree=True)
                if wt_sub_html:
                    out.append(wt_sub_html)
            out.append("</div>")  # /git-repo
        out.append("</div>")  # /git-group-body
        out.append("</div>")  # /git-group
    return "\n".join(out)


def render_page(items):
    """Load the HTML template and inject rendered cards."""
    all_items = sorted(
        items,
        key=lambda x: (PRI_ORDER.get(x["priority"], 9), x["slug"][:10]),
    )
    ordered = []
    for _, group in groupby(all_items, key=lambda x: x["priority"]):
        ordered.extend(sorted(group, key=lambda x: x["slug"][:10], reverse=True))
    all_items = ordered

    labelled_priorities = {"now": "Now", "soon": "Soon", "later": "Later", "review": "Review"}
    parts = []
    seen = set()
    for item in all_items:
        pri = item["priority"]
        if pri in labelled_priorities and pri not in seen:
            parts.append(
                f'<div class="group-heading hidden" data-group="{pri}">{labelled_priorities[pri]}</div>'
            )
            seen.add(pri)
        parts.append(_render_card(item))
    cards = "\n".join(parts)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    count_current = sum(1 for i in all_items if i["priority"] in ("now", "review"))
    count_next = sum(1 for i in all_items if i["priority"] in ("soon", "later"))
    count_backlog = sum(1 for i in all_items if i["priority"] == "backlog")
    count_done = sum(1 for i in all_items if i["priority"] == "done")

    git_groups = _collect_git_repos()
    git_html = _render_git_repos(git_groups)
    count_repos = sum(len(repos) for _, repos in git_groups)

    knowledge_root = collect_knowledge()
    knowledge_html = _render_knowledge(knowledge_root)
    count_knowledge = knowledge_root["count"] if knowledge_root else 0
    count_projects = len(all_items)

    template = _template_path().read_text(encoding="utf-8")
    template = template.replace("{{CARDS}}", cards)
    template = template.replace("{{GIT_REPOS}}", git_html)
    template = template.replace("{{KNOWLEDGE}}", knowledge_html)
    return (
        template.replace("{{TIMESTAMP}}", now)
        .replace("{{COUNT_CURRENT}}", str(count_current))
        .replace("{{COUNT_NEXT}}", str(count_next))
        .replace("{{COUNT_BACKLOG}}", str(count_backlog))
        .replace("{{COUNT_DONE}}", str(count_done))
        .replace("{{COUNT_PROJECTS}}", str(count_projects))
        .replace("{{COUNT_REPOS}}", str(count_repos))
        .replace("{{COUNT_KNOWLEDGE}}", str(count_knowledge))
    )


# ---------------------------------------------------------------------------
# Editing
# ---------------------------------------------------------------------------

_IMG_SRC_RE = re.compile(r'(<img\b[^>]*?\bsrc=")([^"]+)(")', re.IGNORECASE)


def _rewrite_img_src(html, note_dir_rel):
    def sub(m):
        src = m.group(2)
        if (
            src.startswith("http://")
            or src.startswith("https://")
            or src.startswith("//")
            or src.startswith("/")
            or src.startswith("data:")
        ):
            return m.group(0)
        return f"{m.group(1)}/asset/{note_dir_rel}/{src}{m.group(3)}"

    return _IMG_SRC_RE.sub(sub, html)


def _render_markdown(full_path, note_dir_rel):
    try:
        text = full_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        log.warning("render_markdown: could not read %s: %s", full_path, exc)
        return '<p class="note-error">Unable to read note.</p>'
    text = _preprocess_wikilinks(text)
    try:
        out = subprocess.run(
            ["pandoc", "--from=gfm", "--to=html", "--no-highlight"],
            input=text,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if out.returncode == 0 and out.stdout.strip():
            return _rewrite_img_src(out.stdout, note_dir_rel)
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("render_markdown: pandoc failed for %s: %s", full_path, exc)
    return f'<pre class="note-raw">{h(text)}</pre>'


def _render_note(full_path: Path) -> str:
    """Dispatch preview rendering by file kind — see ``_note_kind``.

    Non-markdown kinds emit HTML that reuses the existing plumbing:
    images/PDFs reference ``/file/<rel>``; text files are inlined in a
    ``<pre>``; anything else falls back to an "Open externally" button
    that the existing link-wiring routes through ``/open-doc``.
    """
    kind = _note_kind(full_path)
    try:
        note_dir_rel = str(full_path.parent.relative_to(BASE_DIR))
    except ValueError:
        return '<p class="note-error">Path outside conception tree.</p>'
    file_rel = str(full_path.relative_to(BASE_DIR))

    if kind == "md":
        return _render_markdown(full_path, note_dir_rel)

    if kind == "pdf":
        return (
            f'<iframe class="note-preview-embed" '
            f'src="/file/{h(file_rel)}" '
            f'title="{h(full_path.name)}"></iframe>'
        )

    if kind == "image":
        return (
            f'<img class="note-preview-image" src="/file/{h(file_rel)}" alt="{h(full_path.name)}">'
        )

    if kind == "text":
        try:
            text = full_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            log.warning("render_note: could not read %s: %s", full_path, exc)
            return '<p class="note-error">Unable to read file.</p>'
        return f'<pre class="note-raw note-preview-text">{h(text)}</pre>'

    # Anything else — offer the OS default viewer as a fallback. The
    # anchor gets picked up by _wireNoteLinks and routed to /open-doc.
    return (
        '<div class="note-preview-binary">'
        "<p>No inline preview available for this file.</p>"
        f'<p><a href="{h(file_rel)}">Open externally</a></p>'
        "</div>"
    )


def read_note_raw(full_path: Path) -> dict[str, Any]:
    """Return the plain bytes + mtime for the edit surface."""
    stat_res = full_path.stat()
    content = full_path.read_text(encoding="utf-8", errors="replace")
    return {
        "path": str(full_path.relative_to(BASE_DIR)),
        "content": content,
        "mtime": stat_res.st_mtime,
    }


def write_note(full_path: Path, content: str, expected_mtime: float | None) -> dict[str, Any]:
    """Atomically rewrite ``full_path`` with ``content``.

    Refuses when the on-disk mtime doesn't match ``expected_mtime`` so
    a stale editor never silently overwrites out-of-band edits.
    Returns ``{ok, mtime | reason}``.
    """
    try:
        current_mtime = full_path.stat().st_mtime
    except FileNotFoundError:
        return {"ok": False, "reason": "file vanished"}
    if expected_mtime is not None and abs(current_mtime - float(expected_mtime)) > 1e-6:
        return {"ok": False, "reason": "file changed on disk", "mtime": current_mtime}
    tmp = full_path.with_suffix(full_path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(full_path)
    return {"ok": True, "mtime": full_path.stat().st_mtime}


def rename_note(rel_path: str, new_stem: str) -> dict[str, Any]:
    """Rename a file under ``<item>/notes/`` while preserving its extension.

    ``new_stem`` is the user-typed basename without the extension. The
    original suffix is re-attached and the resulting filename is
    validated against the same whitelist as ``create_note``. README and
    knowledge/* files are deliberately out of scope — those have
    structural meaning elsewhere in the dashboard.
    """
    full = validate_note_path(rel_path)
    if full is None:
        return {"ok": False, "reason": "invalid path"}
    if not _VALID_ITEM_FILE_RE.match(rel_path):
        return {"ok": False, "reason": "only files under <item>/notes/ can be renamed"}
    new_stem = (new_stem or "").strip()
    if not new_stem or not re.match(r"^[\w.-]+$", new_stem) or new_stem in (".", ".."):
        return {"ok": False, "reason": "invalid filename"}
    new_filename = new_stem + full.suffix
    if not _VALID_NOTE_FILENAME_RE.match(new_filename):
        return {"ok": False, "reason": "invalid filename"}
    new_path = full.parent / new_filename
    if new_path.exists() and new_path.resolve() != full.resolve():
        return {"ok": False, "reason": "target already exists"}
    if new_path == full:
        return {"ok": True, "path": rel_path, "mtime": full.stat().st_mtime}
    full.rename(new_path)
    return {
        "ok": True,
        "path": str(new_path.relative_to(BASE_DIR)),
        "mtime": new_path.stat().st_mtime,
    }


def create_note(item_readme_rel: str, filename: str) -> dict[str, Any]:
    """Create an empty note file under the item's ``notes/`` directory.

    ``item_readme_rel`` is the README.md path of the owning item (validated
    against ``_VALID_PATH_RE``). ``filename`` must be a plain basename with
    an extension — no slashes, no traversal. Returns ``{ok, path | reason}``.
    """
    item = _validate_path(item_readme_rel)
    if item is None or item.name != "README.md":
        return {"ok": False, "reason": "invalid item"}
    if not _VALID_NOTE_FILENAME_RE.match(filename):
        return {"ok": False, "reason": "invalid filename"}
    notes_dir = item.parent / "notes"
    notes_dir.mkdir(exist_ok=True)
    target = notes_dir / filename
    if target.exists():
        return {"ok": False, "reason": "file exists"}
    target.write_text("", encoding="utf-8")
    return {
        "ok": True,
        "path": str(target.relative_to(BASE_DIR)),
        "mtime": target.stat().st_mtime,
    }


def _set_priority(full_path, priority):
    if priority not in PRIORITIES:
        return False
    lines = full_path.read_text(encoding="utf-8").split("\n")
    for i, line in enumerate(lines):
        if STATUS_RE.match(line):
            if " : " in line:
                lines[i] = f"**Status** : {priority}"
            else:
                lines[i] = f"**Status**: {priority}"
            full_path.write_text("\n".join(lines), encoding="utf-8")
            return True
    insert_at = 1
    for i in range(1, len(lines)):
        if HEADING2_RE.match(lines[i]):
            break
        if METADATA_RE.match(lines[i]):
            insert_at = i + 1
    if insert_at > 1 and " : " in lines[insert_at - 1]:
        lines.insert(insert_at, f"**Status** : {priority}")
    else:
        lines.insert(insert_at, f"**Status**: {priority}")
    full_path.write_text("\n".join(lines), encoding="utf-8")
    return True


_KIND_MAP = {"incidents": "incident", "projects": "project", "documents": "document"}


def _tidy():
    moves = []
    for folder in ("incidents", "projects", "documents"):
        base = BASE_DIR / folder
        if not base.is_dir():
            continue
        kind = _KIND_MAP[folder]

        for child in sorted(base.iterdir()):
            if not child.is_dir():
                continue

            if _ITEM_DIR_RE.match(child.name):
                readme = child / "README.md"
                if not readme.exists():
                    continue
                item = parse_readme(readme, kind)
                if item and item["priority"] == "done":
                    month = child.name[:7]
                    month_dir = base / month
                    month_dir.mkdir(exist_ok=True)
                    new_path = month_dir / child.name
                    if not new_path.exists():
                        child.rename(new_path)
                        moves.append((f"{folder}/{child.name}", f"{folder}/{month}/{child.name}"))

            elif _MONTH_DIR_RE.match(child.name):
                for sub in sorted(child.iterdir()):
                    if not sub.is_dir() or not _ITEM_DIR_RE.match(sub.name):
                        continue
                    readme = sub / "README.md"
                    if not readme.exists():
                        continue
                    item = parse_readme(readme, kind)
                    if item and item["priority"] != "done":
                        new_path = base / sub.name
                        if not new_path.exists():
                            sub.rename(new_path)
                            moves.append(
                                (f"{folder}/{child.name}/{sub.name}", f"{folder}/{sub.name}")
                            )

                if child.exists() and not any(child.iterdir()):
                    child.rmdir()

    return moves


def run_tidy():
    """Public alias used by the CLI entry point."""
    return _tidy()


def _toggle_checkbox(full_path, line_num):
    lines = full_path.read_text(encoding="utf-8").split("\n")
    if not (0 <= line_num < len(lines)):
        return None
    line = lines[line_num]
    if "- [ ]" in line:
        lines[line_num] = line.replace("- [ ]", "- [x]", 1)
        new_status = "done"
    elif re.search(r"- \[[xX]\]", line):
        lines[line_num] = re.sub(r"- \[[xX]\]", "- [~]", line, count=1)
        new_status = "progress"
    elif "- [~]" in line:
        lines[line_num] = line.replace("- [~]", "- [-]", 1)
        new_status = "abandoned"
    elif "- [-]" in line:
        lines[line_num] = line.replace("- [-]", "- [ ]", 1)
        new_status = "open"
    else:
        return None
    full_path.write_text("\n".join(lines), encoding="utf-8")
    return new_status


def _remove_step(full_path, line_num):
    lines = full_path.read_text(encoding="utf-8").split("\n")
    if not (0 <= line_num < len(lines)):
        return False
    if not CHECKBOX_RE.match(lines[line_num]):
        return False
    lines.pop(line_num)
    full_path.write_text("\n".join(lines), encoding="utf-8")
    return True


def _edit_step(full_path, line_num, new_text):
    new_text = new_text.replace("\n", " ").replace("\r", "")
    lines = full_path.read_text(encoding="utf-8").split("\n")
    if not (0 <= line_num < len(lines)):
        return False
    m = CHECKBOX_RE.match(lines[line_num])
    if not m:
        return False
    lines[line_num] = f"{m.group(1)}- [{m.group(2)}] {new_text}"
    full_path.write_text("\n".join(lines), encoding="utf-8")
    return True


def _add_step(full_path, text, section_heading=None):
    text = text.replace("\n", " ").replace("\r", "")
    lines = full_path.read_text(encoding="utf-8").split("\n")

    if section_heading:
        target_line = None
        target_level = 0
        for i, line in enumerate(lines):
            m = re.match(r"^(#{2,})\s+(.+)$", line)
            if m and m.group(2).strip() == section_heading:
                target_line = i
                target_level = len(m.group(1))
                break

        if target_line is not None:
            end = len(lines)
            for i in range(target_line + 1, len(lines)):
                m = re.match(r"^(#{2,})\s+", lines[i])
                if m and len(m.group(1)) <= target_level:
                    end = i
                    break
            insert_at = end
            while insert_at > target_line + 1 and lines[insert_at - 1].strip() == "":
                insert_at -= 1
            lines.insert(insert_at, f"- [ ] {text}")
            full_path.write_text("\n".join(lines), encoding="utf-8")
            return insert_at

    ns_line = None
    for i, line in enumerate(lines):
        if re.match(r"^##\s+Steps", line, re.IGNORECASE):
            ns_line = i
            break

    if ns_line is None:
        insert_before = len(lines)
        for i, line in enumerate(lines):
            if re.match(r"^##\s+(Notes|Timeline|Chronologie)\b", line, re.IGNORECASE):
                insert_before = i
                break
        lines[insert_before:insert_before] = ["", "## Steps", "", f"- [ ] {text}", ""]
        full_path.write_text("\n".join(lines), encoding="utf-8")
        return insert_before + 3

    else:
        end = len(lines)
        for i in range(ns_line + 1, len(lines)):
            if HEADING2_RE.match(lines[i]):
                end = i
                break
        insert_end = end
        for i in range(ns_line + 1, end):
            if HEADING3_RE.match(lines[i]):
                insert_end = i
                break
        insert_at = insert_end
        while insert_at > ns_line + 1 and lines[insert_at - 1].strip() == "":
            insert_at -= 1
        lines.insert(insert_at, f"- [ ] {text}")

    full_path.write_text("\n".join(lines), encoding="utf-8")
    return insert_at


def _open_path(slot_key, path):
    """Launch the user-configured command for ``slot_key`` against ``path``.

    ``slot_key`` is one of ``main_ide`` / ``secondary_ide`` / ``terminal``.
    The fallback chain comes from ``cfg.open_with[slot_key]`` (set by ``init``).
    Each command is shell-parsed and tried in order until one starts.
    """
    path_str = str(path)
    slot = _OPEN_WITH.get(slot_key)
    if slot is None:
        log.warning("unknown slot: %r", slot_key)
        return False
    candidates = slot.resolve(path_str)
    if not candidates:
        log.warning("%s: no commands configured", slot_key)
        return False
    last_err = None
    for cmd in candidates:
        try:
            subprocess.Popen(
                cmd,
                cwd=path_str,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            log.info("%s: launched %s", slot_key, cmd[0])
            return True
        except FileNotFoundError as exc:
            last_err = exc
            continue
        except OSError as exc:
            log.warning("%s: %s failed: %s", slot_key, cmd[0], exc)
            return False
    log.warning("%s: no launcher found (last error: %s)", slot_key, last_err)
    return False


def _try_pdf_viewer(path_str: str) -> bool:
    """Try the configured ``pdf_viewer`` fallback chain.

    Each entry is shlex-split and ``{path}`` replaced by ``path_str``. Returns
    True on the first command that starts without raising; False if the list
    is empty or every entry fails (bad shell syntax, missing binary, …).
    """
    for raw in _PDF_VIEWER:
        if not raw.strip():
            continue
        try:
            argv = shlex.split(raw)
        except ValueError as exc:
            log.warning("pdf_viewer parse failed for %r: %s", raw, exc)
            continue
        argv = [arg.replace("{path}", path_str) for arg in argv]
        if not argv:
            continue
        try:
            subprocess.Popen(
                argv,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return True
        except FileNotFoundError:
            continue
        except OSError as exc:
            log.warning("pdf_viewer %r failed: %s", argv[0], exc)
            continue
    return False


def _os_open(path: Path) -> bool:
    """Hand ``path`` to the OS-native default-application launcher.

    Linux uses ``xdg-open``; macOS ``open``; Windows uses ``os.startfile``.
    PDFs additionally honour the ``pdf_viewer`` config chain and only fall
    back to the OS default if every configured command fails to launch.
    """
    path_str = str(path)
    if path.suffix.lower() == ".pdf" and _try_pdf_viewer(path_str):
        return True
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", path_str], start_new_session=True)
        elif os.name == "nt":
            os.startfile(path_str)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(
                ["xdg-open", path_str],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        return True
    except OSError as exc:
        log.warning("open-doc failed: %s", exc)
        return False


_EXTERNAL_URL_RE = re.compile(r"^https?://[^\s]+$", re.IGNORECASE)


def _is_external_url(url: str) -> bool:
    return bool(url) and bool(_EXTERNAL_URL_RE.match(url))


def _open_external(url: str) -> bool:
    """Open ``url`` in the user's default browser via ``webbrowser``.

    pywebview intercepts in-page navigation, so we always route external
    URLs through the host browser — otherwise they'd replace the dashboard.
    """
    import webbrowser

    try:
        return bool(webbrowser.open(url, new=2))
    except (OSError, webbrowser.Error) as exc:
        log.warning("open-external failed: %s", exc)
        return False


def _reorder_all(full_path, order):
    lines = full_path.read_text(encoding="utf-8").split("\n")
    for ln in order:
        if not (0 <= ln < len(lines)) or not CHECKBOX_RE.match(lines[ln]):
            return False
    contents = [lines[ln] for ln in order]
    sorted_positions = sorted(order)
    for pos, content in zip(sorted_positions, contents):
        lines[pos] = content
    full_path.write_text("\n".join(lines), encoding="utf-8")
    return True
