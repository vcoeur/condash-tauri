"""HTML rendering for the conception dashboard.

Entry point is :func:`render_page`, which reads the dashboard template
and stamps it with the card list, git repo strip, knowledge tree, and
summary counts. Smaller helpers render individual cards, notes,
deliverables, steps, wikilinks-rewritten markdown, and the git repo
action buttons.
"""

from __future__ import annotations

import html as html_mod
import json
import logging
import re
import subprocess
from datetime import datetime
from itertools import groupby
from pathlib import Path

from . import __version__
from . import runners as runners_mod
from .context import RenderCtx
from .git_scan import _collect_git_repos
from .parser import (
    PRI_ORDER,
    _knowledge_title_and_desc,
    _note_kind,
    collect_knowledge,
)
from .wikilinks import _preprocess_wikilinks

log = logging.getLogger(__name__)


def h(text):
    """HTML-escape."""
    return html_mod.escape(str(text))


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


def _render_markdown(ctx: RenderCtx, full_path, note_dir_rel):
    try:
        text = full_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        log.warning("render_markdown: could not read %s: %s", full_path, exc)
        return '<p class="note-error">Unable to read note.</p>'
    text = _preprocess_wikilinks(ctx, text)
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


def _render_note(ctx: RenderCtx, full_path: Path) -> str:
    """Dispatch preview rendering by file kind — see ``_note_kind``."""
    kind = _note_kind(full_path)
    try:
        note_dir_rel = str(full_path.parent.relative_to(ctx.base_dir))
    except ValueError:
        return '<p class="note-error">Path outside conception tree.</p>'
    file_rel = str(full_path.relative_to(ctx.base_dir))

    if kind == "md":
        return _render_markdown(ctx, full_path, note_dir_rel)

    if kind == "pdf":
        # Mount point for the custom PDF.js viewer defined in dashboard.html.
        # We don't rely on the webview's built-in PDF handler: QtWebEngine
        # ships with PdfViewerEnabled=false and pywebview doesn't flip it,
        # so the native-window modal would otherwise just show Chromium's
        # "Open file externally" card. The dashboard JS picks up any
        # .note-pdf-host element that appears in the view pane and wires
        # the vendored pdf.mjs against /file/... for rendering.
        return (
            f'<div class="note-pdf-host" '
            f'data-pdf-src="/file/{h(file_rel)}" '
            f'data-pdf-filename="{h(full_path.name)}"></div>'
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


def _render_step(item, file_path):
    status = item["status"]
    js_file = json.dumps(file_path).replace("'", "\\'").replace('"', "'")
    dot_char = {"done": "\u2713", "progress": "~", "abandoned": "\u2014", "open": ""}.get(
        status, ""
    )
    return (
        f'<div class="step {status}" '
        f'data-file="{h(file_path)}" data-line="{item["line"]}">'
        f'<span class="drag-handle" '
        f'onpointerdown="stepPointerDown(event)">\u283f</span>'
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


def _render_file_entry(n: dict) -> str:
    js_path = json.dumps(n["path"]).replace("'", "\\'").replace('"', "'")
    label = n["name"][:-3] if n["name"].endswith(".md") else n["name"]
    kind = n.get("kind", "md")
    return (
        f'<div class="note-item" data-kind="{h(kind)}" '
        f"onclick=\"openNotePreview({js_path},'{h(n['name'])}')\">"
        f"{h(label)}</div>"
    )


def _render_subdir_group(group: dict, item_slug: str, readme_rel: str | None) -> str:
    """One ``<details>`` per subdirectory. ``data-subdir-key`` lets the
    client persist collapsed/expanded state per group across reloads.
    Recurses into nested groups.

    Each group's summary hosts three actions, all scoped to that folder:
    ``+`` (new note here), ``↑`` (upload here), ``+ folder`` (mkdir a
    child of this folder). The subdir is passed to the server relative
    to the item root, so writes can land anywhere inside the item — not
    just under ``notes/``.
    """
    rel = group["rel_dir"]
    file_count = len(group["files"]) + sum(_subtree_count(g) for g in group["groups"])
    files_html = "".join(_render_file_entry(n) for n in group["files"])
    nested_html = "".join(_render_subdir_group(g, item_slug, readme_rel) for g in group["groups"])
    key = f"{item_slug}/{rel}"

    actions_html = ""
    if readme_rel:
        js_readme = json.dumps(readme_rel).replace("'", "\\'").replace('"', "'")
        js_sub = json.dumps(rel).replace("'", "\\'").replace('"', "'")
        actions_html = (
            f'<button class="notes-new-btn" title="New note in this folder" '
            f'onclick="event.stopPropagation();event.preventDefault();'
            f'createNoteFor({js_readme},{js_sub})">+</button>'
            f'<button class="notes-upload-btn" title="Upload files into this folder" '
            f'onclick="event.stopPropagation();event.preventDefault();'
            f'uploadToNotes({js_readme},{js_sub})">\u2191</button>'
            f'<button class="notes-mkdir-btn" title="New subdirectory inside this folder" '
            f'onclick="event.stopPropagation();event.preventDefault();'
            f'createNotesSubdir({js_readme},{js_sub})">+ folder</button>'
        )
    return (
        f'<details class="notes-group" data-subdir-key="{h(key)}">'
        f'<summary class="notes-group-heading">'
        f'<span class="notes-chevron" aria-hidden="true">&#9656;</span>'
        f'<span class="notes-group-name">{h(group["label"])}/</span>'
        f'<span class="notes-count">({file_count})</span>'
        f"{actions_html}"
        f"</summary>"
        f'<div class="notes-list">{files_html}{nested_html}</div>'
        f"</details>"
    )


def _subtree_count(group: dict) -> int:
    return len(group["files"]) + sum(_subtree_count(g) for g in group["groups"])


def _render_files(tree, readme_rel: str | None = None, item_slug: str = ""):
    """Render the item-files block for a card.

    ``tree`` is the recursive ``{files, groups}`` shape produced by
    ``parser._list_item_tree``. Top-level files render flat at the root;
    each subdirectory becomes a collapsible ``<details>`` group with its
    own (recursive) contents. Per-folder actions (new note, upload, new
    subfolder) live on each group's summary — see ``_render_subdir_group``.
    The root header is a label + count only.

    If the item has no ``notes/`` directory yet, render a placeholder
    "+ notes folder" action so the user can bootstrap it without touching
    the filesystem manually.
    """
    if not isinstance(tree, dict):  # legacy callers passed a flat list
        tree = {"files": list(tree), "groups": []}
    files = tree.get("files") or []
    groups = tree.get("groups") or []
    top_files_html = "".join(_render_file_entry(n) for n in files)
    groups_html = "".join(_render_subdir_group(g, item_slug, readme_rel) for g in groups)
    total = len(files) + sum(_subtree_count(g) for g in groups)
    # Root-level action: ``+ folder`` only (creates a sibling of notes/
    # at the item root). Per-folder ``+`` and ``↑`` live on each group's
    # summary, so they don't repeat at the root.
    bootstrap_action = ""
    if readme_rel:
        js_readme = json.dumps(readme_rel).replace("'", "\\'").replace('"', "'")
        bootstrap_action = (
            f'<button class="notes-mkdir-btn" '
            f'title="New folder at the item root (sibling of notes/)" '
            f'onclick="event.stopPropagation();event.preventDefault();'
            f"createNotesSubdir({js_readme},'')\">+ folder</button>"
        )
    empty_class = " is-empty" if total == 0 else ""
    return (
        f'<div class="notes-block{empty_class}">'
        f'<div class="notes-heading">'
        f'Files <span class="notes-count">({total})</span>'
        f"{bootstrap_action}</div>"
        f'<div class="notes-list">{top_files_html}{groups_html}</div>'
        f"</div>"
    )


def _render_deliverables(deliverables):
    if not deliverables:
        return ""
    links = []
    for d in deliverables:
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


def _next_step(item):
    """First pending step across all sections, or None.

    "Pending" means status is ``open`` or ``progress`` — ``abandoned``
    steps aren't "next", they're intentionally parked. Used on the
    collapsed card so users can see what the project is blocked on
    without expanding each one.
    """
    for sec in item["sections"]:
        for step in sec["items"]:
            if step["status"] in ("open", "progress"):
                return step
    return None


def _render_card(item):
    from .parser import PRIORITIES

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

    invalid_status = item.get("invalid_status")
    invalid_badge = ""
    if invalid_status:
        escaped = h(invalid_status)
        invalid_badge = (
            f'<span class="invalid-status-badge" '
            f'title="Unknown Status &quot;{escaped}&quot; in README — treated as backlog. '
            f'Valid: now, soon, later, backlog, review, done.">'
            f"!? {escaped}</span>"
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
    notes_html = _render_files(
        item.get("files") or {"files": [], "groups": []},
        readme_rel=item.get("path"),
        item_slug=item.get("slug", ""),
    )

    summary_html = f'<p class="summary">{h(item["summary"])}</p>' if item["summary"] else ""

    pdf_badge = (
        '<span class="dlv-icon" title="Has deliverables">PDF</span>'
        if item.get("deliverables")
        else ""
    )

    next_step = _next_step(item)
    if next_step is not None:
        next_step_html = (
            f'<div class="card-next-step" '
            f"onclick=\"toggleCard(this.closest('.card'))\" "
            f'title="Next pending step">'
            f'<span class="next-step-marker next-step-{next_step["status"]}" '
            f'aria-hidden="true"></span>'
            f'<span class="next-step-text">{h(next_step["text"])}</span>'
            f"</div>"
        )
    else:
        next_step_html = ""

    node_id = f"projects/{pri}/{item['slug']}"
    card_actions_html = _render_card_actions(item)
    return (
        f'<div class="card collapsed" id="{item["slug"]}" '
        f'data-kind="{item["kind"]}" data-priority="{pri}" data-node-id="{node_id}">'
        f'<div class="card-header">'
        f'<div class="card-header-left" onclick="toggleCard(this.closest(\'.card\'))">'
        f'<span class="kind-prefix kind-{kind}">{kind}</span>'
        f'<span class="card-title">{h(item["title"])}</span>'
        f"{pdf_badge}</div>"
        f'<div class="card-header-right">'
        f"{progress} {invalid_badge}{priority_select} "
        f'<span class="date">{h(item["date"])}</span>'
        f"{card_actions_html}</div></div>"
        f"{next_step_html}"
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


def _render_knowledge(root: dict | None) -> str:
    """Render the knowledge tree returned by ``collect_knowledge``."""
    if root is None or root["count"] == 0:
        return (
            '<p class="note-empty">'
            "No <code>knowledge/</code> tree under the configured conception path."
            "</p>"
        )
    parts = ['<div class="knowledge-panel" data-node-id="knowledge">']
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
    """Render one directory as a collapsible group, recursing into subdirs."""
    parts = [f'<details class="knowledge-group" data-node-id="{h(node["rel_dir"])}">']
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
        f'<div class="knowledge-card" data-node-id="{h(e["path"])}" '
        f'onclick="openNotePreview({js_path},{js_title})">'
        f'<div class="knowledge-title">{h(e["title"])}</div>'
        f"{desc_html}"
        f'<div class="knowledge-path">{h(e["path"])}</div>'
        f"</div>"
    )


def _render_index_badge(idx: dict, top_level: bool) -> str:
    """Index files become a clickable pill, not a card."""
    js_path = json.dumps(idx["path"]).replace("'", "\\'").replace('"', "'")
    js_title = json.dumps(idx["title"]).replace("'", "\\'").replace('"', "'")
    cls = "knowledge-index-badge" + (" knowledge-index-top" if top_level else "")
    return (
        f'<a class="{cls}" '
        f'onclick="event.stopPropagation();openNotePreview({js_path},{js_title})" '
        f'title="{h(idx["path"])}">index</a>'
    )


def _index_entry(ctx: RenderCtx, idx_path: Path) -> dict | None:
    """Shape ``idx_path`` into the dict the index-badge renderer wants."""
    if not idx_path.is_file():
        return None
    title, desc = _knowledge_title_and_desc(idx_path)
    return {
        "path": str(idx_path.relative_to(ctx.base_dir)),
        "title": title,
        "desc": desc,
    }


def _render_history_item(item: dict) -> str:
    """Compact row for one project in the on-disk History view."""
    js_path = json.dumps(item["path"]).replace("'", "\\'").replace('"', "'")
    js_title = json.dumps(item["title"]).replace("'", "\\'").replace('"', "'")
    pri = item["priority"]
    kind = item["kind"]
    slug = item["slug"]
    return (
        f'<div class="knowledge-card history-card" '
        f'data-priority="{h(pri)}" data-kind="{h(kind)}" '
        f'onclick="openNotePreview({js_path},{js_title})">'
        f'<div class="knowledge-title">{h(item["title"])}</div>'
        f'<div class="history-meta">'
        f'<span class="pill pri-{h(pri)}">{h(pri)}</span>'
        f'<span class="pill">{h(kind)}</span>'
        f"</div>"
        f'<div class="knowledge-path">{h(slug)}</div>'
        f"</div>"
    )


def _render_history(ctx: RenderCtx, items: list[dict]) -> str:
    """Render ``projects/`` as the on-disk tree: month buckets + items.

    Mirrors the knowledge-tree affordances — ``projects/index.md`` and each
    ``projects/YYYY-MM/index.md`` become clickable badges next to their
    heading, and items inside each month appear in creation order (newest
    first). The whole list is a direct reflection of disk state; no
    filtering by priority or status. A project with no items renders an
    explanatory empty state instead.
    """
    root_dir = ctx.base_dir / "projects"
    if not root_dir.is_dir():
        return '<p class="note-empty">No <code>projects/</code> tree under the configured conception path.</p>'

    by_month: dict[str, list[dict]] = {}
    for item in items:
        parts = item["path"].split("/")
        if len(parts) >= 2 and parts[0] == "projects":
            by_month.setdefault(parts[1], []).append(item)

    parts_out = ['<div class="knowledge-panel history-panel">']
    root_index = _index_entry(ctx, root_dir / "index.md")
    if root_index:
        parts_out.append(_render_index_badge(root_index, top_level=True))

    if not by_month:
        parts_out.append('<p class="note-empty">No projects on disk yet.</p>')
        parts_out.append("</div>")
        return "".join(parts_out)

    # Newest month first — month dirs are YYYY-MM so a string sort works.
    for month in sorted(by_month.keys(), reverse=True):
        month_items = sorted(by_month[month], key=lambda x: x["slug"], reverse=True)
        parts_out.append('<details class="knowledge-group history-group" open>')
        parts_out.append('<summary class="knowledge-group-heading">')
        parts_out.append('<span class="knowledge-chevron" aria-hidden="true">&#9656;</span>')
        parts_out.append(f'<span class="knowledge-group-name">{h(month)}</span>')
        parts_out.append(f'<span class="knowledge-count">({len(month_items)})</span>')
        month_index = _index_entry(ctx, root_dir / month / "index.md")
        if month_index:
            parts_out.append(_render_index_badge(month_index, top_level=False))
        parts_out.append("</summary>")
        parts_out.append('<div class="knowledge-list">')
        for item in month_items:
            parts_out.append(_render_history_item(item))
        parts_out.append("</div>")
        parts_out.append("</details>")

    parts_out.append("</div>")
    return "".join(parts_out)


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
    # "Work on" — terminal window with a play triangle inside, signalling
    # "send the `work on <slug>` command to the focused terminal tab".
    "work_on": (
        '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" '
        'stroke="currentColor" stroke-width="2.2" stroke-linecap="round" '
        'stroke-linejoin="round" aria-hidden="true">'
        '<rect x="3" y="4" width="18" height="16" rx="2"/>'
        '<polygon points="10 9 16 12 10 15" fill="currentColor" stroke="none"/></svg>'
    ),
    # Filled play triangle — "start inline dev-server runner".
    "runner_run": (
        '<svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor" '
        'aria-hidden="true">'
        '<polygon points="7 5 19 12 7 19"/></svg>'
    ),
    # Filled square — "stop inline dev-server runner".
    "runner_stop": (
        '<svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor" '
        'aria-hidden="true">'
        '<rect x="6" y="6" width="12" height="12" rx="1"/></svg>'
    ),
    # Down arrow — "a runner is active below, jump to it".
    "runner_jump": (
        '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" '
        'stroke="currentColor" stroke-width="2.4" stroke-linecap="round" '
        'stroke-linejoin="round" aria-hidden="true">'
        '<polyline points="6 9 12 15 18 9"/></svg>'
    ),
    # Chevron that flips between down (expanded) and up (collapsed) via
    # the .runner-collapsed parent class. Used on the inline-terminal
    # header so the user can hide the output area without stopping the
    # child process.
    "runner_collapse": (
        '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" '
        'stroke="currentColor" stroke-width="2.4" stroke-linecap="round" '
        'stroke-linejoin="round" aria-hidden="true">'
        '<polyline points="6 15 12 9 18 15"/></svg>'
    ),
    # Diagonal arrow out of a box — "pop the inline terminal into a modal".
    "runner_popout": (
        '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" '
        'stroke="currentColor" stroke-width="2.2" stroke-linecap="round" '
        'stroke-linejoin="round" aria-hidden="true">'
        '<path d="M14 4h6v6"/>'
        '<line x1="10" y1="14" x2="20" y2="4"/>'
        '<path d="M20 14v6H4V4h6"/></svg>'
    ),
    # Folder outline — opens the item directory in the OS file manager.
    "folder": (
        '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" '
        'stroke="currentColor" stroke-width="2.2" stroke-linecap="round" '
        'stroke-linejoin="round" aria-hidden="true">'
        '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>'
    ),
    # Small down chevron — caret on the split open-with button.
    "open_caret": (
        '<svg viewBox="0 0 24 24" width="10" height="10" fill="none" '
        'stroke="currentColor" stroke-width="3" stroke-linecap="round" '
        'stroke-linejoin="round" aria-hidden="true">'
        '<polyline points="6 9 12 15 18 9"/></svg>'
    ),
    # Diagonal arrow — "jump to this peer-card's live runner terminal".
    "peer_jump": (
        '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" '
        'stroke="currentColor" stroke-width="2.4" stroke-linecap="round" '
        'stroke-linejoin="round" aria-hidden="true">'
        '<line x1="7" y1="17" x2="17" y2="7"/>'
        '<polyline points="7 7 17 7 17 17"/></svg>'
    ),
}


def _render_card_actions(item):
    """Per-card quick-action cluster: "work on <slug>" + open folder."""
    slug = item["slug"]
    # Item folder is the README's parent dir; strip the trailing "README.md".
    rel_dir = item["path"].rsplit("/", 1)[0] + "/"
    js_slug = json.dumps(slug).replace("'", "\\'").replace('"', "'")
    js_dir = json.dumps(rel_dir).replace("'", "\\'").replace('"', "'")
    work_title = f'Work on — insert "work on {slug}" in the focused terminal tab'
    folder_title = "Open folder in file manager"
    return (
        '<div class="card-actions">'
        f'<button class="git-action-btn card-action-work-on" '
        f'title="{h(work_title)}" aria-label="{h(work_title)}" '
        f'onclick="workOn(event,{js_slug})">'
        f"{_ICON_SVGS['work_on']}</button>"
        f'<button class="git-action-btn card-action-folder" '
        f'title="{h(folder_title)}" aria-label="{h(folder_title)}" '
        f'onclick="openFolder(event,{js_dir})">'
        f"{_ICON_SVGS['folder']}</button>"
        "</div>"
    )


def _render_open_with(ctx: RenderCtx, path: str) -> str:
    """Split "Open with" button — primary icon + caret → popover picker.

    The primary icon opens with the first configured slot (``main_ide``).
    The caret reveals a small menu listing every slot plus an entry for
    the integrated terminal so keyboard-only or infrequent targets are
    still reachable without cluttering the row.
    """
    js_path = json.dumps(path).replace("'", "\\'").replace('"', "'")
    primary_slot = "main_ide"
    primary = ctx.open_with.get(primary_slot)
    primary_title = primary.label if primary is not None else primary_slot
    picker_items: list[str] = []
    for slot_key in ("main_ide", "secondary_ide", "terminal"):
        slot = ctx.open_with.get(slot_key)
        label = slot.label if slot is not None else slot_key
        picker_items.append(
            f'<button type="button" class="open-popover-item" '
            f"onclick=\"openPath(event,{js_path},'{slot_key}');gitClosePopovers()\">"
            f'<span class="open-popover-icon">{_ICON_SVGS[slot_key]}</span>'
            f"<span>{h(label)}</span></button>"
        )
    integrated_title = "Open in integrated terminal"
    picker_items.append(
        f'<button type="button" class="open-popover-item" '
        f'onclick="openInTerminal(event,{js_path});gitClosePopovers()">'
        f'<span class="open-popover-icon">{_ICON_SVGS["integrated_terminal"]}</span>'
        f"<span>{h(integrated_title)}</span></button>"
    )
    popover = '<div class="open-popover" role="menu" hidden>' + "".join(picker_items) + "</div>"
    return (
        '<div class="open-grp">'
        f'<button type="button" class="open-primary" title="{h(primary_title)}" '
        f'aria-label="{h(primary_title)}" '
        f"onclick=\"openPath(event,{js_path},'{primary_slot}')\">"
        f"{_ICON_SVGS[primary_slot]}</button>"
        '<button type="button" class="open-caret" title="Open with…" '
        'aria-haspopup="menu" aria-label="Open with menu" '
        'onclick="gitToggleOpenPopover(event,this)">'
        f"{_ICON_SVGS['open_caret']}</button>"
        f"{popover}</div>"
    )


def _runner_key(repo_name: str, sub_name: str | None = None) -> str:
    """Canonical runner-registry key. Mirrors ``config._parse_repo_list``."""
    if sub_name is None:
        return repo_name
    return f"{repo_name}--{sub_name}"


def _runner_key_for_member(family: dict, member: dict) -> str:
    return _runner_key(family["name"], member["name"] if member.get("is_subrepo") else None)


def _render_runner_button(
    key: str,
    checkout_key: str,
    checkout_path: str,
) -> str:
    """Render the per-checkout Run / Stop / Switch affordance.

    Button state is resolved by looking up the live session in
    ``runners_mod.registry()``:

    - no session           → green Run button
    - session on this row  → red Stop button
    - session elsewhere    → amber Switch button (triggers confirm dialog)
    """
    session = runners_mod.get(key)
    js_key = json.dumps(key).replace("'", "\\'").replace('"', "'")
    js_checkout = json.dumps(checkout_key).replace("'", "\\'").replace('"', "'")
    js_path = json.dumps(checkout_path).replace("'", "\\'").replace('"', "'")
    if session is None or session.exit_code is not None:
        # Off or exited — exited gets the same Run affordance; clicking
        # starts a fresh session (replacing the stale record).
        title = "Start dev runner"
        cls = "git-action-runner-run"
        icon = _ICON_SVGS["runner_run"]
        onclick = f"runnerStart(event,{js_key},{js_checkout},{js_path})"
    elif session.checkout_key == checkout_key:
        title = "Stop dev runner"
        cls = "git-action-runner-stop"
        icon = _ICON_SVGS["runner_stop"]
        onclick = f"runnerStop(event,{js_key})"
    else:
        title = f"Switch runner from {session.checkout_key} to this checkout"
        cls = "git-action-runner-switch"
        icon = _ICON_SVGS["runner_run"]
        onclick = f"runnerSwitch(event,{js_key},{js_checkout},{js_path})"
    return (
        f'<button class="git-action-btn git-action-runner {cls}" '
        f'title="{h(title)}" aria-label="{h(title)}" '
        f'onclick="{onclick}">{icon}</button>'
    )


def _render_runner_mount(key: str, checkout_key: str) -> str:
    """Inline terminal mount point, rendered under the checkout that owns
    the live session. The JS side picks this up on DOM insertion and
    opens a WebSocket to ``/ws/runner/<key>``.
    """
    session = runners_mod.get(key)
    if session is None or session.checkout_key != checkout_key:
        return ""
    exited_attr = f' data-exit-code="{session.exit_code}"' if session.exit_code is not None else ""
    js_label = h(f"{key} @ {checkout_key}")
    # Fresh mounts start collapsed — the user clicks the header (or the
    # runner_jump arrow on the repo row) to reveal the output. Expanded
    # state is per-mount and not persisted across reloads.
    return (
        f'<div class="runner-term-mount runner-collapsed" '
        f'data-runner-key="{h(key)}" '
        f'data-runner-checkout="{h(checkout_key)}"{exited_attr}>'
        f'<div class="runner-term-header" '
        f'title="Click to collapse / expand (keeps process running)" '
        f'onclick="runnerToggleCollapse(this)">'
        f'<span class="runner-term-label">{js_label}</span>'
        f'<span class="runner-term-status" aria-live="polite"></span>'
        f'<button class="runner-control runner-collapse" '
        f'aria-label="Collapse terminal" tabindex="-1" '
        f'onclick="event.stopPropagation();runnerToggleCollapse(this)">'
        f"{_ICON_SVGS['runner_collapse']}</button>"
        f'<button class="runner-control runner-popout" '
        f'title="Pop out" aria-label="Pop out" '
        f'onclick="event.stopPropagation();runnerPopout(this)">{_ICON_SVGS["runner_popout"]}</button>'
        f'<button class="runner-control runner-stop-inline" '
        f'title="Stop" aria-label="Stop" '
        f'onclick="event.stopPropagation();runnerStopInline(this)">{_ICON_SVGS["runner_stop"]}</button>'
        f"</div>"
        f'<div class="runner-term-host"></div>'
        f"</div>"
    )


def _family_has_live_runner(ctx: RenderCtx, family: dict) -> bool:
    """True if any configured runner key anchored at any family member is live."""
    for member in family["members"]:
        key = _runner_key_for_member(family, member)
        if key in ctx.repo_run:
            session = runners_mod.get(key)
            if session is not None and session.exit_code is None:
                return True
    return False


def _status_badge(member_or_wt: dict) -> str:
    if member_or_wt.get("missing"):
        return '<span class="git-missing">missing</span>'
    if member_or_wt.get("dirty"):
        return f'<span class="git-changes">{member_or_wt["changed"]} changed</span>'
    return '<span class="git-clean">\u2713</span>'


def _member_live_runner(ctx: RenderCtx, family: dict, member: dict):
    """Return the live :class:`runners.Session` for this member, or ``None``.

    "Live" = the member has a configured runner key AND the session exists
    AND the session has not exited. Callers use this to decide whether to
    emit a jump-to-terminal arrow on the peer-card foot or surface the
    inline runner mount.
    """
    if member.get("missing"):
        return None
    key = _runner_key_for_member(family, member)
    if key not in ctx.repo_run:
        return None
    session = runners_mod.get(key)
    if session is None or session.exit_code is not None:
        return None
    return session


def _branch_status_cell(info: dict) -> str:
    """Status cell content for a branch row — ✓ / dirty pill / missing pill."""
    if info.get("missing"):
        return '<span class="branch-missing">missing</span>'
    if info.get("dirty"):
        return f'<span class="branch-dirty">{info["changed"]}</span>'
    return '<span class="branch-clean">\u2713</span>'


def _branch_dot(info: dict, is_live: bool) -> str:
    """State dot that leads every branch row — clean / dirty / live / missing."""
    if is_live:
        cls = "live"
    elif info.get("missing"):
        cls = "missing"
    elif info.get("dirty"):
        cls = "dirty"
    else:
        cls = "clean"
    return f'<span class="b-dot b-dot-{cls}"></span>'


def _render_branch_row(
    ctx: RenderCtx,
    family: dict,
    member: dict,
    *,
    info: dict,
    checkout_key: str,
    is_main: bool,
    node_id: str,
) -> str:
    """Render one branch row inside a peer-card.

    ``info`` is either the member dict itself (main checkout) or one of
    its ``worktrees`` entries. ``checkout_key`` is ``"main"`` for the
    parent checkout of the family or the worktree ``key`` otherwise — it
    matches :func:`_render_runner_button` / :func:`_render_runner_mount`.
    """
    # Branch label resolution: the main row of a subrepo has no branch of
    # its own (it inherits the parent checkout's branch), so fall back to
    # the parent member's branch.
    if info.get("branch"):
        branch_label = info["branch"]
    elif is_main and member.get("is_subrepo"):
        parent = family["members"][0] if family["members"] else {}
        branch_label = parent.get("branch", "")
    else:
        branch_label = info.get("branch", "")
    kind_label = "checkout" if is_main else "worktree"

    # Runner pill — only when this member has a configured runner.
    runner_pill = ""
    member_key = _runner_key_for_member(family, member)
    is_live = False
    if not info.get("missing") and member_key in ctx.repo_run:
        runner_pill = _render_runner_button(member_key, checkout_key, info["path"])
        session = runners_mod.get(member_key)
        is_live = (
            session is not None
            and session.exit_code is None
            and session.checkout_key == checkout_key
        )

    # Open-with split button (hidden cell when the checkout is missing).
    if info.get("missing"):
        open_cell = '<span class="open-grp open-grp-empty" aria-hidden="true"></span>'
    else:
        open_cell = _render_open_with(ctx, info["path"])

    row_cls = "peer-row"
    if is_main:
        row_cls += " peer-row-main"
    if info.get("missing"):
        row_cls += " peer-row-missing"
    elif is_live and info.get("dirty"):
        row_cls += " peer-row-dirty peer-row-live"
    elif is_live:
        row_cls += " peer-row-live"
    elif info.get("dirty"):
        row_cls += " peer-row-dirty"

    return (
        f'<div class="{row_cls}" data-node-id="{h(node_id)}" '
        f'title="{h(info.get("path", ""))}">'
        f"{_branch_dot(info, is_live)}"
        f'<span class="b-name">{h(branch_label) or "&mdash;"}'
        f'<span class="b-kind">{h(kind_label)}</span></span>'
        f'<span class="b-status">{_branch_status_cell(info)}</span>'
        f'<span class="b-run">{runner_pill}</span>'
        f"{open_cell}</div>"
    )


def _render_peer_card(
    ctx: RenderCtx,
    family: dict,
    member: dict,
    member_id: str,
) -> str:
    """Render one peer card — either the parent repo or a promoted sub-repo.

    Contains a head (name + kind badge + status pill), N branch rows (main
    checkout + one per worktree), an optional inline runner mount, and a
    foot (path + optional jump-to-terminal arrow).
    """
    is_subrepo = bool(member.get("is_subrepo"))
    live_session = _member_live_runner(ctx, family, member)
    is_missing = bool(member.get("missing"))

    # Overall state tag shown in the head.
    dirty_branches = 0
    if member.get("dirty"):
        dirty_branches += 1
    for wt in member.get("worktrees") or []:
        if wt.get("dirty"):
            dirty_branches += 1
    if is_missing:
        head_tag = '<span class="peer-tag peer-tag-missing">missing</span>'
    elif dirty_branches:
        noun = "branch" if dirty_branches == 1 else "branches"
        head_tag = f'<span class="peer-tag peer-tag-dirty">{dirty_branches} {noun} dirty</span>'
    else:
        head_tag = '<span class="peer-tag peer-tag-clean">clean</span>'
    if live_session is not None:
        head_tag += '<span class="peer-tag peer-tag-live">live</span>'

    kind_label = "sub-repo" if is_subrepo else "repo"

    card_cls = "peer-card"
    if is_subrepo:
        card_cls += " peer-card-sub"
    else:
        card_cls += " peer-card-parent"
    if dirty_branches:
        card_cls += " peer-card-dirty"
    if live_session is not None:
        card_cls += " peer-card-live"
    if is_missing:
        card_cls += " peer-card-missing"

    parts: list[str] = [
        f'<div class="{card_cls}" data-node-id="{h(member_id)}">',
        '<div class="peer-head">',
        f'<span class="peer-name">{h(member["name"])}</span>',
        f"{head_tag}",
        f'<span class="peer-kind">{h(kind_label)}</span>',
        "</div>",
        '<div class="peer-rows">',
    ]

    # Main checkout row first, then one row per worktree.
    parts.append(
        _render_branch_row(
            ctx,
            family,
            member,
            info=member,
            checkout_key="main",
            is_main=True,
            node_id=f"{member_id}/b:main",
        )
    )
    for wt in member.get("worktrees") or []:
        wt_id = f"{member_id}/wt:{wt['key']}"
        parts.append(
            _render_branch_row(
                ctx,
                family,
                member,
                info=wt,
                checkout_key=wt["key"],
                is_main=False,
                node_id=wt_id,
            )
        )
    parts.append("</div>")  # /peer-rows

    # Inline runner terminal mount — placed between rows and foot so the
    # card stays scannable even when the terminal is expanded.
    if live_session is not None:
        member_key = _runner_key_for_member(family, member)
        mount = _render_runner_mount(member_key, live_session.checkout_key)
        if mount:
            parts.append(f'<div class="peer-term">{mount}</div>')

    # Foot: repo path + jump-arrow if the card has a live runner.
    foot_path = member.get("path") or ""
    foot_bits: list[str] = [f'<span class="peer-foot-path">{h(foot_path)}</span>']
    if live_session is not None:
        foot_bits.append(
            f'<button type="button" class="peer-jump" '
            f'title="Jump to live terminal" aria-label="Jump to live terminal" '
            f'onclick="runnerJump(event,this)">{_ICON_SVGS["peer_jump"]}</button>'
        )
    parts.append(f'<div class="peer-foot">{"".join(foot_bits)}</div>')

    parts.append("</div>")  # /peer-card
    return "\n".join(parts)


def _render_flat_group(ctx: RenderCtx, family: dict, group_id: str) -> str:
    """Render one family into the bucket grid.

    Both solo and compound families use ``display: contents`` on the
    wrapper so their peer-cards become direct items of the bucket grid
    — preserving column alignment across solo and compound families
    (no sub-grid, no row span, no offset shift). Compound families
    prepend a full-row ornament label that sits above their cards to
    identify the grouping without framing it.
    """
    family_id = f"{group_id}/{family['name']}"
    members = family["members"]
    is_compound = len(members) > 1

    cls = "flat-group flat-group-compound" if is_compound else "flat-group flat-group-solo"
    parts: list[str] = [f'<div class="{cls}" data-node-id="{h(family_id)}">']
    if is_compound:
        parts.append(f'<div class="flat-group-ornament">{h(family["name"])}</div>')
    for member in members:
        member_id = f"{family_id}/m:{member['name']}"
        parts.append(_render_peer_card(ctx, family, member, member_id))
    parts.append("</div>")  # /flat-group
    return "\n".join(parts)


def render_git_repo_fragment(ctx: RenderCtx, node_id: str) -> str | None:
    """Return the HTML for the ``.flat-group`` block matching ``node_id``.

    ``node_id`` shape: ``code/<group-label>/<family-name>``. Returns
    ``None`` when the id doesn't match a known family — the ``/fragment``
    caller then falls back to a global reload.
    """
    prefix = "code/"
    if not node_id.startswith(prefix):
        return None
    rest = node_id[len(prefix) :]
    if "/" not in rest:
        return None
    group_label, family_name = rest.split("/", 1)
    for label, families in _collect_git_repos(ctx):
        if label != group_label:
            continue
        for family in families:
            if family["name"] == family_name:
                return _render_flat_group(ctx, family, f"code/{label}")
    return None


def _render_git_repos(ctx: RenderCtx, groups):
    """Render the Code tab.

    Each bucket (primary / secondary / Others) becomes a labelled section
    holding a grid of peer-cards. Solo families flow directly into the
    grid; compound families (parent + promoted sub-repos) tie their
    cards together under a small family ornament.
    """
    if not groups:
        return ""
    out = []
    for label, families in groups:
        group_id = f"code/{label}"
        out.append(
            f'<section class="flat-bucket" data-node-id="{h(group_id)}">'
            f'<h3 class="flat-bucket-heading">{h(label)}</h3>'
            f'<div class="flat-bucket-body">'
        )
        for family in families:
            out.append(_render_flat_group(ctx, family, group_id))
        out.append("</div></section>")
    return "\n".join(out)


def render_card_fragment(item) -> str:
    """HTML for one project card — used by the /fragment endpoint to
    serve a single card on local reload."""
    return _render_card(item)


def render_knowledge_card_fragment(entry: dict) -> str:
    """HTML for one knowledge card (file)."""
    return _render_knowledge_card(entry)


def render_knowledge_group_fragment(node: dict) -> str:
    """HTML for one knowledge directory (recursive, including children)."""
    return _render_knowledge_group(node)


def render_page(ctx: RenderCtx, items):
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
                f'<div class="group-heading hidden" data-group="{pri}" '
                f'data-node-id="projects/{pri}">{labelled_priorities[pri]}</div>'
            )
            seen.add(pri)
        parts.append(_render_card(item))
    cards = "\n".join(parts)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    count_current = sum(1 for i in all_items if i["priority"] in ("now", "review"))
    count_next = sum(1 for i in all_items if i["priority"] in ("soon", "later"))
    count_backlog = sum(1 for i in all_items if i["priority"] == "backlog")
    count_done = sum(1 for i in all_items if i["priority"] == "done")

    git_groups = _collect_git_repos(ctx)
    git_html = _render_git_repos(ctx, git_groups)
    count_repos = sum(len(repos) for _, repos in git_groups)

    knowledge_root = collect_knowledge(ctx)
    knowledge_html = _render_knowledge(knowledge_root)
    count_knowledge = knowledge_root["count"] if knowledge_root else 0

    count_projects = len(all_items)

    history_html = _render_history(ctx, all_items)

    template = ctx.template
    template = template.replace("{{CARDS}}", cards)
    template = template.replace("{{GIT_REPOS}}", git_html)
    template = template.replace("{{KNOWLEDGE}}", knowledge_html)
    template = template.replace("{{HISTORY}}", history_html)
    return (
        template.replace("{{TIMESTAMP}}", now)
        .replace("{{COUNT_CURRENT}}", str(count_current))
        .replace("{{COUNT_NEXT}}", str(count_next))
        .replace("{{COUNT_BACKLOG}}", str(count_backlog))
        .replace("{{COUNT_DONE}}", str(count_done))
        .replace("{{COUNT_HISTORY}}", str(count_projects))
        .replace("{{COUNT_PROJECTS}}", str(count_projects))
        .replace("{{COUNT_REPOS}}", str(count_repos))
        .replace("{{COUNT_KNOWLEDGE}}", str(count_knowledge))
        .replace("{{VERSION}}", __version__)
    )
