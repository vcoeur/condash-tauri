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

from .context import RenderCtx
from .git_scan import _collect_git_repos
from .parser import PRI_ORDER, _note_kind, collect_knowledge
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
    """Render the notes block for an item card."""
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


def _render_knowledge(root: dict | None) -> str:
    """Render the knowledge tree returned by ``collect_knowledge``."""
    if root is None or root["count"] == 0:
        return '<p class="note-empty">No <code>knowledge/</code> tree under the configured conception path.</p>'
    parts = ['<div class="knowledge-panel">']
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
    """Index files become a clickable pill, not a card."""
    js_path = json.dumps(idx["path"]).replace("'", "\\'").replace('"', "'")
    js_title = json.dumps(idx["title"]).replace("'", "\\'").replace('"', "'")
    cls = "knowledge-index-badge" + (" knowledge-index-top" if top_level else "")
    return (
        f'<a class="{cls}" '
        f'onclick="event.stopPropagation();openNotePreview({js_path},{js_title})" '
        f'title="{h(idx["path"])}">index</a>'
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


def _render_git_actions(ctx: RenderCtx, path):
    js_path = json.dumps(path).replace("'", "\\'").replace('"', "'")
    items_html: list[str] = []
    for slot_key in ("main_ide", "secondary_ide", "terminal"):
        slot = ctx.open_with.get(slot_key)
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


def _render_submodule_rows(ctx: RenderCtx, submodules, worktree=False):
    """Render subrepo rows at the same visual size as parent repos."""
    if not submodules:
        return ""
    rows = []
    for sub in submodules:
        sub_actions = _render_git_actions(ctx, sub["path"])
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


def _render_git_repos(ctx: RenderCtx, groups):
    if not groups:
        return ""
    out = []
    chevron = '<span class="git-chevron">\u25b6</span>'
    for label, repos in groups:
        out.append('<div class="git-group">')
        out.append(f'<div class="git-group-header">{h(label)}</div>')
        out.append('<div class="git-group-body">')
        for r in repos:
            out.append('<div class="git-repo">')
            dirty_cls = " git-dirty" if r["dirty"] else ""
            badge = (
                f'<span class="git-changes">{r["changed"]} changed</span>'
                if r["dirty"]
                else '<span class="git-clean">\u2713</span>'
            )
            actions = _render_git_actions(ctx, r["path"])
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
            sub_html = _render_submodule_rows(ctx, r.get("submodules") or [])
            if sub_html:
                out.append(sub_html)
            for wt in r.get("worktrees", []):
                wt_dirty_cls = " git-dirty" if wt["dirty"] else ""
                wt_badge = (
                    f'<span class="git-changes">{wt["changed"]} changed</span>'
                    if wt["dirty"]
                    else '<span class="git-clean">\u2713</span>'
                )
                wt_actions = _render_git_actions(ctx, wt["path"])
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
                wt_sub_html = _render_submodule_rows(ctx, wt.get("submodules") or [], worktree=True)
                if wt_sub_html:
                    out.append(wt_sub_html)
            out.append("</div>")  # /git-repo
        out.append("</div>")  # /git-group-body
        out.append("</div>")  # /git-group
    return "\n".join(out)


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

    git_groups = _collect_git_repos(ctx)
    git_html = _render_git_repos(ctx, git_groups)
    count_repos = sum(len(repos) for _, repos in git_groups)

    knowledge_root = collect_knowledge(ctx)
    knowledge_html = _render_knowledge(knowledge_root)
    count_knowledge = knowledge_root["count"] if knowledge_root else 0
    count_projects = len(all_items)

    template = ctx.template
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
