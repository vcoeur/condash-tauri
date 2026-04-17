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

import hashlib
import html as html_mod
import json
import logging
import os
import re
import shlex
import stat
import subprocess
import sys
import time
from datetime import datetime
from importlib.resources import files as _package_files
from itertools import groupby
from pathlib import Path
from typing import Any

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


METADATA_RE = re.compile(r"^\*\*(.+?)\*\*\s*:\s*(.+)$")
CHECKBOX_RE = re.compile(r"^(\s*)-\s*\[([ xX~\-])\]\s+(.+)$")
HEADING2_RE = re.compile(r"^##\s+(.+)$")
HEADING3_RE = re.compile(r"^###\s+(.+)$")
STATUS_RE = re.compile(r"^\*\*Status\*\*\s*:\s*.*$", re.IGNORECASE)
DELIVERABLE_RE = re.compile(
    r"-\s+\[([^\]]+)\]\(([^)]+\.pdf)\)"
    r"(?:\s*[—–-]\s*(.+))?$"
)

PRIORITIES = ("now", "soon", "later", "backlog", "review", "done")
PRI_ORDER = {p: i for i, p in enumerate(PRIORITIES)}


def h(text):
    """HTML-escape."""
    return html_mod.escape(str(text))


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def _parse_sections(lines):
    """Extract the ## Steps section with its checkboxes."""
    sections = []
    cur_sec = None

    for i, line in enumerate(lines):
        m2 = HEADING2_RE.match(line)
        if m2:
            if cur_sec:
                sections.append(cur_sec)
            heading = m2.group(1).strip()
            cur_sec = {"heading": heading, "items": []}
            continue

        mc = CHECKBOX_RE.match(line)
        if mc and cur_sec is not None:
            char = mc.group(2)
            status = (
                "done"
                if char.lower() == "x"
                else ("progress" if char == "~" else ("abandoned" if char == "-" else "open"))
            )
            cur_sec["items"].append(
                {
                    "text": mc.group(3).strip(),
                    "done": status in ("done", "abandoned"),
                    "status": status,
                    "line": i,
                }
            )

    if cur_sec:
        sections.append(cur_sec)

    return [s for s in sections if s["items"] or s["heading"].lower() == "steps"]


def _parse_deliverables(lines):
    """Extract PDF links from the ## Deliverables section."""
    deliverables = []
    in_section = False

    for line in lines:
        if HEADING2_RE.match(line):
            if in_section:
                break
            if line.strip().lstrip("#").strip().lower() == "deliverables":
                in_section = True
            continue

        if in_section:
            m = DELIVERABLE_RE.match(line.strip())
            if m:
                deliverables.append(
                    {
                        "label": m.group(1).strip(),
                        "path": m.group(2).strip(),
                        "desc": (m.group(3) or "").strip(),
                    }
                )

    return deliverables


_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".avif"}
_PDF_EXTS = {".pdf"}
_TEXT_EXTS = {
    ".txt",
    ".log",
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".json",
    ".yml",
    ".yaml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".sh",
    ".bash",
    ".zsh",
    ".rs",
    ".go",
    ".java",
    ".kt",
    ".rb",
    ".php",
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".xml",
    ".html",
    ".css",
    ".scss",
    ".sass",
    ".sql",
    ".env",
    ".gitignore",
}


def _note_kind(path: Path) -> str:
    """Classify a file by extension — drives the preview dispatcher."""
    ext = path.suffix.lower()
    if ext == ".md":
        return "md"
    if ext in _PDF_EXTS:
        return "pdf"
    if ext in _IMAGE_EXTS:
        return "image"
    if ext in _TEXT_EXTS:
        return "text"
    return "binary"


def _list_notes(item_dir, max_depth: int = 2):
    """List every file under ``<item_dir>/notes/`` with its detected kind.

    Walks up to ``max_depth`` levels of subdirectories so items can group
    related files (e.g. `notes/drafts/…`) without the dashboard flattening
    the structure. Hidden files and dirs (`.…`) are skipped.
    """
    notes_dir = item_dir / "notes"
    if not notes_dir.is_dir():
        return []
    out: list[dict[str, str]] = []

    def walk(current: Path, depth: int) -> None:
        for entry in sorted(current.iterdir()):
            if entry.name.startswith("."):
                continue
            if entry.is_dir():
                if depth < max_depth:
                    walk(entry, depth + 1)
                continue
            if not entry.is_file():
                continue
            out.append(
                {
                    "name": str(entry.relative_to(notes_dir)),
                    "path": str(entry.relative_to(BASE_DIR)),
                    "kind": _note_kind(entry),
                }
            )

    walk(notes_dir, 1)
    return out


def parse_readme(path, kind):
    """Parse a single incident/project README."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        log.warning("parse_readme: could not read %s: %s", path, exc)
        return None
    lines = text.split("\n")
    if not lines:
        return None

    title = lines[0].lstrip("#").strip()

    meta = {}
    first_section_idx = None
    for i in range(1, len(lines)):
        if HEADING2_RE.match(lines[i]):
            first_section_idx = i
            break
        m = METADATA_RE.match(lines[i])
        if m:
            meta[m.group(1).strip().lower()] = m.group(2).strip()

    date = meta.get("date", "")
    apps_raw = meta.get("apps", meta.get("composant", ""))
    severity = meta.get("sévérité", meta.get("severity", None))
    apps = [a.strip().strip("`").split("(")[0].strip() for a in apps_raw.split(",") if a.strip()]

    summary = ""
    if first_section_idx is not None:
        para = []
        in_code = False
        for line in lines[first_section_idx + 1 :]:
            if line.startswith("```"):
                in_code = not in_code
                continue
            if in_code:
                continue
            if HEADING2_RE.match(line) or HEADING3_RE.match(line):
                break
            if line.strip() == "" and para:
                break
            if line.strip() == "" or line.startswith("|"):
                continue
            para.append(line.strip())
        summary = " ".join(para)
        if len(summary) > 300:
            summary = summary[:297] + "..."

    sections = _parse_sections(lines)
    if not any(s["heading"].lower() == "steps" for s in sections):
        sections.insert(0, {"heading": "Steps", "items": []})

    deliverables = _parse_deliverables(lines)
    item_dir = str(path.parent.relative_to(BASE_DIR))
    for d in deliverables:
        d["full_path"] = f"{item_dir}/{d['path']}"

    notes = _list_notes(path.parent)

    done = sum(it["done"] for s in sections for it in s["items"])
    total = sum(len(s["items"]) for s in sections)

    priority = meta.get("status", "backlog").lower()
    if priority not in PRIORITIES:
        priority = "backlog"

    return {
        "slug": path.parent.name,
        "title": title,
        "date": date,
        "priority": priority,
        "apps": apps,
        "severity": severity,
        "summary": summary,
        "sections": sections,
        "deliverables": deliverables,
        "notes": notes,
        "done": done,
        "total": total,
        "path": str(path.relative_to(BASE_DIR)),
        "kind": kind,
    }


def _knowledge_title_and_desc(path: Path) -> tuple[str, str]:
    """Pick a human label + short description from a knowledge file.

    Title: first ``# heading`` line, else the filename without extension.
    Description: first non-blank line after the heading that is not
    itself a heading or frontmatter.
    """
    title = path.stem.replace("-", " ").replace("_", " ")
    desc = ""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return title, desc
    title_taken = False
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if not title_taken and line.startswith("#"):
            title = line.lstrip("#").strip() or title
            title_taken = True
            continue
        if line.startswith("#") or line.startswith("---"):
            continue
        desc = line.rstrip(".")
        break
    return title, desc[:220]


def collect_knowledge() -> dict | None:
    """Scan ``knowledge/`` recursively and return a tree for the explorer tab.

    Mirrors the on-disk shape: every directory becomes a node with its
    direct ``index.md`` (if any) lifted out as a special "index" entry,
    its non-index ``.md`` files as ``body`` entries, and its subdirectories
    as ``children`` (recursive). ``count`` is the total navigable page
    count at and below this node (index counts as 1, body files count, all
    descendants roll up).

    Returns ``None`` if ``knowledge/`` doesn't exist.
    """
    root = BASE_DIR / "knowledge"
    if not root.is_dir():
        return None
    return _knowledge_node(root)


def _knowledge_node(d: Path) -> dict:
    """Build one tree node for directory ``d``."""
    is_root = d == BASE_DIR / "knowledge"
    label = "Knowledge" if is_root else d.name.replace("_", " ").replace("-", " ").title()
    index: dict[str, str] | None = None
    body: list[dict[str, str]] = []
    children: list[dict] = []
    for entry in sorted(d.iterdir()):
        if entry.name.startswith("."):
            continue
        if entry.is_file() and entry.suffix.lower() == ".md":
            title, desc = _knowledge_title_and_desc(entry)
            item = {"path": str(entry.relative_to(BASE_DIR)), "title": title, "desc": desc}
            if entry.name == "index.md":
                index = item
            else:
                body.append(item)
        elif entry.is_dir():
            child = _knowledge_node(entry)
            # Drop empty subtrees so the UI doesn't render lone headings.
            if child["count"] > 0:
                children.append(child)
    count = len(body) + (1 if index else 0) + sum(c["count"] for c in children)
    return {
        "name": "" if is_root else d.name,
        "label": label,
        "rel_dir": str(d.relative_to(BASE_DIR)),
        "index": index,
        "body": body,
        "children": children,
        "count": count,
    }


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


def collect_items():
    """Find and parse all incident/project/document READMEs."""
    items = []
    for kind, folder in [
        ("incident", "incidents"),
        ("project", "projects"),
        ("document", "documents"),
    ]:
        base = BASE_DIR / folder
        if not base.is_dir():
            continue
        readmes = set(base.glob("*/README.md")) | set(base.glob("*/*/README.md"))
        for readme in sorted(readmes):
            item = parse_readme(readme, kind)
            if item:
                items.append(item)

    return items


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


def _is_sandbox_stub(repo_path: Path, status: str, rel: str) -> bool:
    """Return True for harness-synthesized stub files that should not count
    as real repo changes.

    When condash runs inside a sandbox (e.g. Claude Code's bwrap harness),
    the runtime binds zero-byte read-only copies of the user's home
    dotfiles (``.bashrc``, ``.gitconfig``, ``.mcp.json``, …) into every
    working directory so programs don't crash on missing config. These
    show up as untracked files in ``git status`` but they are not real
    changes, and the commit skill already filters them with the same
    logic — we want condash's dirty-badge to agree.
    """
    if "D" in status:
        return False
    try:
        st = (Path(repo_path) / rel).lstat()
    except OSError:
        return False
    if stat.S_ISCHR(st.st_mode):
        return True
    if stat.S_ISLNK(st.st_mode):
        try:
            return os.readlink(str(Path(repo_path) / rel)) == "/dev/null"
        except OSError:
            return False
    if status != "??":
        return False
    if not stat.S_ISREG(st.st_mode):
        return False
    if st.st_size != 0:
        return False
    if st.st_mode & 0o222:
        return False
    return True


def _git_status(path):
    try:
        branch = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
        status_out = subprocess.run(
            ["git", "-C", str(path), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return "?", False, 0, []
    changed_files = []
    for ln in status_out.splitlines():
        if len(ln) < 4:
            continue
        status = ln[:2]
        rest = ln[3:]
        if " -> " in rest:
            rest = rest.split(" -> ", 1)[1]
        if _is_sandbox_stub(path, status, rest):
            continue
        changed_files.append(rest)
    return branch, bool(changed_files), len(changed_files), changed_files


def _git_worktrees(repo_path):
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_path), "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    main = str(Path(repo_path).resolve())
    worktrees = []
    current = {}
    for line in out.splitlines() + [""]:
        if not line:
            if current.get("path") and current["path"] != main:
                wt_path = Path(current["path"])
                key = (
                    wt_path.parent.name
                    if wt_path.parent.parent.name == "worktrees"
                    else wt_path.name
                )
                branch, dirty, changed, changed_files = _git_status(wt_path)
                worktrees.append(
                    {
                        "key": key,
                        "path": current["path"],
                        "branch": branch or current.get("branch", ""),
                        "dirty": dirty,
                        "changed": changed,
                        "changed_files": changed_files,
                    }
                )
            current = {}
            continue
        if line.startswith("worktree "):
            current["path"] = line[len("worktree ") :]
        elif line.startswith("branch "):
            current["branch"] = line[len("branch ") :].replace("refs/heads/", "")
    return worktrees


def _load_repository_structure():
    """Return configured primary/secondary repo buckets."""
    return list(_REPO_STRUCTURE)


def _resolve_submodules(base_path, submodule_names):
    out = []
    base = Path(base_path)
    for name in submodule_names:
        sub = base / name
        if sub.is_dir():
            out.append({"name": name, "path": str(sub.resolve())})
    return out


def _collect_git_repos():
    """Find git repos under the configured workspace and group them.

    Returns ``[]`` (no repo strip) when ``workspace_path`` is unset.
    """
    if _WORKSPACE is None:
        return []
    workspace = _WORKSPACE
    found = {}
    if workspace.is_dir():
        for child in sorted(workspace.iterdir()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            git_dir = child / ".git"
            if not git_dir.exists():
                continue
            branch, dirty, changed, changed_files = _git_status(child)
            found[child.name] = {
                "name": child.name,
                "path": str(child.resolve()),
                "branch": branch,
                "dirty": dirty,
                "changed": changed,
                "changed_files": changed_files,
                "worktrees": _git_worktrees(child),
                "submodules": [],
            }

    structure = _load_repository_structure()
    submodule_map = {name: subs for _, entries in structure for name, subs in entries}

    def _attach_counts(container):
        changed_files = container.get("changed_files") or []
        for sub in container.get("submodules") or []:
            prefix = sub["name"] + "/"
            sub["changed"] = sum(1 for f in changed_files if f.startswith(prefix))
            sub["dirty"] = sub["changed"] > 0

    for repo_name, repo in found.items():
        subs = submodule_map.get(repo_name) or []
        if not subs:
            continue
        repo["submodules"] = _resolve_submodules(repo["path"], subs)
        _attach_counts(repo)
        for wt in repo["worktrees"]:
            wt["submodules"] = _resolve_submodules(wt["path"], subs)
            _attach_counts(wt)

    groups = []
    placed = set()
    for label, entries in structure:
        bucket = [found[n] for n, _ in entries if n in found]
        placed.update(n for n, _ in entries if n in found)
        if bucket:
            groups.append((label, bucket))

    others = [found[n] for n in sorted(found) if n not in placed]
    if others:
        groups.append(("Others", others))
    return groups


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

_VALID_PATH_RE = re.compile(
    r"^(?:incidents|projects|documents)/"
    r"(?:\d{4}-\d{2}/)?"
    r"\d{4}-\d{2}-\d{2}-[\w.-]+/"
    r"README\.md$"
)

_VALID_DOWNLOAD_RE = re.compile(
    r"^(?:incidents|projects|documents)/"
    r"(?:\d{4}-\d{2}/)?"
    r"\d{4}-\d{2}-\d{2}-[\w.-]+/"
    r"(?:notes/)?[\w.-]+\.pdf$"
)

_VALID_NOTE_RE = re.compile(
    r"^(?:incidents|projects|documents)/"
    r"(?:\d{4}-\d{2}/)?"
    r"\d{4}-\d{2}-\d{2}-[\w.-]+/"
    r"(?:notes/[\w.-]+|README)\.md$"
)

# Knowledge pages live outside the date-prefixed item structure. Match
# `knowledge/<file>.md` at the root (apps.md, conventions.md) and
# `knowledge/<subdir>/<file>.md` (topics/, external/, internal/, …).
_VALID_KNOWLEDGE_NOTE_RE = re.compile(r"^knowledge/(?:[\w.-]+/)?[\w.-]+\.md$")

_VALID_ASSET_RE = re.compile(
    r"^(?:incidents|projects|documents)/"
    r"(?:\d{4}-\d{2}/)?"
    r"\d{4}-\d{2}-\d{2}-[\w.-]+/"
    r"(?:notes/)?[\w./-]+\.(?:png|jpg|jpeg|gif|svg|webp)$",
    re.IGNORECASE,
)

_ASSET_CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
}

# Any file directly under an item's `notes/` tree. Separate from the
# narrower image-only asset regex above so /file can serve PDFs, text,
# and misc binaries for in-modal preview.
_VALID_ITEM_FILE_RE = re.compile(
    r"^(?:incidents|projects|documents)/"
    r"(?:\d{4}-\d{2}/)?"
    r"\d{4}-\d{2}-\d{2}-[\w.-]+/"
    r"notes/[\w./-]+$"
)

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


def _find_item_dir(type_plural: str, target: str) -> str | None:
    """Look up a single item directory by exact name or short-name match.

    Scans both the type's top-level and any `YYYY-MM/` archive folders.
    Prefers the most recent directory when several short-names collide.
    """
    root = BASE_DIR / type_plural
    if not root.is_dir():
        return None
    candidates: list[str] = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        if child.name == target or (_DATE_SLUG_RE.match(child.name) and child.name[11:] == target):
            candidates.append(child.name)
        if re.match(r"^\d{4}-\d{2}$", child.name):
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


def _resolve_wikilink(target: str) -> str | None:
    """Resolve a `[[target]]` to a conception-relative path, if it exists.

    Resolution order:
    1. Prefixed item reference: `project/<slug>`, `incidents/<slug>`, etc.
    2. Knowledge path: `knowledge/topics/foo` or `knowledge/foo`.
    3. Short slug across all three item kinds — most recent wins.
    4. Short knowledge page across `topics/`, `external/`, `internal/` and
       the root `apps.md` / `conventions.md`.
    """
    target = target.strip()
    if not target:
        return None

    if "/" in target:
        head, _, tail = target.partition("/")
        type_pl = _ITEM_TYPE_NORMAL.get(head)
        if type_pl:
            found = _find_item_dir(type_pl, tail)
            if found:
                return f"{type_pl}/{found}/README.md"
        if head == "knowledge":
            path = target if target.endswith(".md") else f"{target}.md"
            if (BASE_DIR / path).is_file():
                return path

    for type_pl in ("projects", "incidents", "documents"):
        found = _find_item_dir(type_pl, target)
        if found:
            return f"{type_pl}/{found}/README.md"

    for sub in ("topics", "external", "internal"):
        candidate = BASE_DIR / "knowledge" / sub / f"{target}.md"
        if candidate.is_file():
            return f"knowledge/{sub}/{target}.md"
    for root_file in ("apps.md", "conventions.md"):
        if target == root_file.removesuffix(".md"):
            candidate = BASE_DIR / "knowledge" / root_file
            if candidate.is_file():
                return f"knowledge/{root_file}"

    return None


def _preprocess_wikilinks(text: str) -> str:
    """Rewrite `[[target]]` / `[[target|label]]` into raw-HTML anchors.

    Pandoc GFM passes raw HTML through unchanged, so emitting the final
    `<a>` here keeps the rendering pipeline single-pass. Resolved links
    get class `wikilink`; misses get `wikilink-missing` and no href so the
    webview doesn't try to navigate.
    """

    def repl(match: re.Match) -> str:
        target = match.group(1).strip()
        label = (match.group(2) or target).strip()
        resolved = _resolve_wikilink(target)
        if resolved:
            return (
                f'<a class="wikilink" href="{h(resolved)}" '
                f'data-wikilink-target="{h(target)}">{h(label)}</a>'
            )
        return (
            f'<a class="wikilink-missing" '
            f'title="Wikilink target not found: {h(target)}">{h(label)}</a>'
        )

    return _WIKILINK_RE.sub(repl, text)


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


def _validate_path(rel_path):
    if ".." in rel_path:
        return None
    if not _VALID_PATH_RE.match(rel_path):
        return None
    full = (BASE_DIR / rel_path).resolve()
    try:
        full.relative_to(BASE_DIR.resolve())
    except ValueError:
        return None
    return full if full.exists() else None


def validate_note_path(rel_path: str) -> Path | None:
    """Public: validate a note/README/knowledge/notes-file path.

    Accepts: item READMEs and any file under `<item>/notes/**`, plus
    pages under `knowledge/`. Paths outside conception are rejected.
    """
    if ".." in rel_path:
        return None
    if not (
        _VALID_NOTE_RE.match(rel_path)
        or _VALID_KNOWLEDGE_NOTE_RE.match(rel_path)
        or _VALID_ITEM_FILE_RE.match(rel_path)
    ):
        return None
    full = (BASE_DIR / rel_path).resolve()
    try:
        full.relative_to(BASE_DIR.resolve())
    except ValueError:
        return None
    return full if full.is_file() else None


_VALID_NOTE_FILENAME_RE = re.compile(r"^[\w.-]+\.[A-Za-z0-9]+$")


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


def validate_file_path(rel_path: str) -> tuple[Path, str] | None:
    """Validate a raw-byte serve request for the /file endpoint.

    Same acceptance set as :func:`validate_note_path` (note/README/asset
    files under items, plus pages under `knowledge/`). Returns the absolute
    path and a best-effort content type.
    """
    result = validate_note_path(rel_path)
    if result is None:
        return None
    return result, _guess_content_type(result)


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


def validate_download_path(rel_path: str) -> Path | None:
    if ".." in rel_path or not _VALID_DOWNLOAD_RE.match(rel_path):
        return None
    full = (BASE_DIR / rel_path).resolve()
    try:
        full.relative_to(BASE_DIR.resolve())
    except ValueError:
        return None
    return full if full.is_file() else None


def validate_asset_path(rel_path: str) -> tuple[Path, str] | None:
    if ".." in rel_path or not _VALID_ASSET_RE.match(rel_path):
        return None
    full = (BASE_DIR / rel_path).resolve()
    try:
        full.relative_to(BASE_DIR.resolve())
    except ValueError:
        return None
    if not full.is_file():
        return None
    ctype = _ASSET_CONTENT_TYPES.get(full.suffix.lower(), "application/octet-stream")
    return full, ctype


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


_MONTH_DIR_RE = re.compile(r"^\d{4}-\d{2}$")
_ITEM_DIR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-.+$")

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


def _compute_fingerprint(items):
    data = []
    for item in sorted(items, key=lambda x: x["slug"]):
        sections = tuple(
            (s["heading"], tuple((it["text"], it["status"]) for it in s["items"]))
            for s in item["sections"]
        )
        deliverables = tuple((d["label"], d["path"]) for d in item.get("deliverables", []))
        notes = tuple(n["path"] for n in item.get("notes", []))
        data.append(
            (
                item["slug"],
                item["title"],
                item["priority"],
                item["kind"],
                tuple(item["apps"]),
                item["summary"],
                sections,
                deliverables,
                notes,
            )
        )
    return hashlib.md5(repr(data).encode()).hexdigest()[:16]


def _tidy_needed(items):
    for item in items:
        parts = item["path"].split("/")
        if len(parts) == 3 and item["priority"] == "done":
            return True
        if len(parts) == 4 and _MONTH_DIR_RE.match(parts[1]) and item["priority"] != "done":
            return True
    return False


_git_cache = {"fingerprint": None, "timestamp": 0.0}


def _git_fingerprint():
    now = time.monotonic()
    if _git_cache["fingerprint"] and now - _git_cache["timestamp"] < 30:
        return _git_cache["fingerprint"]

    if _WORKSPACE is None:
        _git_cache["fingerprint"] = "no-workspace"
        _git_cache["timestamp"] = now
        return _git_cache["fingerprint"]

    workspace = _WORKSPACE
    parts = []
    if workspace.is_dir():
        for child in sorted(workspace.iterdir()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            if not (child / ".git").exists():
                continue
            try:
                head = subprocess.run(
                    ["git", "-C", str(child), "rev-parse", "HEAD"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                ).stdout.strip()
                status = subprocess.run(
                    ["git", "-C", str(child), "status", "--porcelain"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                ).stdout
                parts.append(f"{child.name}:{head}:{status}")
            except (OSError, subprocess.SubprocessError):
                parts.append(f"{child.name}:error")

    fp = hashlib.md5("".join(parts).encode()).hexdigest()[:16]
    _git_cache["fingerprint"] = fp
    _git_cache["timestamp"] = now
    return fp


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


def _validate_open_path(path_str):
    if not path_str or "\x00" in path_str:
        return None
    try:
        p = Path(path_str).resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if not p.is_dir():
        return None
    roots: list[Path] = []
    if _WORKSPACE is not None:
        roots.append(_WORKSPACE.resolve())
    if _WORKTREES is not None:
        roots.append(_WORKTREES.resolve())
    for root in roots:
        try:
            p.relative_to(root)
            return p
        except ValueError:
            continue
    return None


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


def _validate_doc_path(rel_path: str) -> Path | None:
    """Resolve a note-body link target against the conception tree.

    Rejects anything outside ``BASE_DIR`` (symlink-safe) or any non-existent
    file. Returns the resolved absolute path on success, ``None`` otherwise.
    """
    if not rel_path or "\x00" in rel_path or ".." in rel_path.split("/"):
        return None
    try:
        full = (BASE_DIR / rel_path).resolve(strict=True)
        full.relative_to(BASE_DIR.resolve())
    except (OSError, ValueError):
        return None
    return full if full.is_file() else None


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
