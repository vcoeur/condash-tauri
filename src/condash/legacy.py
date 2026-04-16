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
import os
import re
import stat
import subprocess
import sys
import time
from datetime import datetime
from importlib.resources import files as _package_files
from itertools import groupby
from pathlib import Path
from typing import Any

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


def init(cfg) -> None:
    """Wire runtime configuration into this module.

    Must be called exactly once before any other function. Accepts a
    :class:`condash.config.CondashConfig` (typed as ``Any`` here to avoid
    a circular import at module load).
    """
    global BASE_DIR, _WORKSPACE, _WORKTREES, _REPO_STRUCTURE, _OPEN_WITH
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


def _list_notes(item_dir):
    """List ``notes/*.md`` files inside an item dir."""
    notes_dir = item_dir / "notes"
    if not notes_dir.is_dir():
        return []
    out = []
    for f in sorted(notes_dir.iterdir()):
        if not f.is_file() or f.name.startswith("."):
            continue
        if f.suffix.lower() != ".md":
            continue
        out.append(
            {
                "name": f.name,
                "path": str(f.relative_to(BASE_DIR)),
            }
        )
    return out


def parse_readme(path, kind):
    """Parse a single incident/project README."""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
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


def _render_notes(notes):
    if not notes:
        return ""
    items_html = ""
    for n in notes:
        js_path = json.dumps(n["path"]).replace("'", "\\'").replace('"', "'")
        label = n["name"][:-3] if n["name"].endswith(".md") else n["name"]
        items_html += (
            f'<div class="note-item" onclick="openNotePreview({js_path},'
            f"'{h(n['name'])}')\">{h(label)}</div>"
        )
    count = len(notes)
    return (
        f'<div class="notes-block">'
        f'<div class="notes-heading" onclick="toggleNotes(this)">'
        f'Notes <span class="notes-count">({count})</span></div>'
        f'<div class="notes-list" style="display:none">{items_html}</div>'
        f"</div>"
    )


def _render_deliverables(deliverables):
    if not deliverables:
        return ""
    links = []
    for d in deliverables:
        href = f"/download/{d['full_path']}"
        title = f' title="{h(d["desc"])}"' if d["desc"] else ""
        desc = f' <span class="dlv-desc">— {h(d["desc"])}</span>' if d["desc"] else ""
        links.append(
            f'<a class="dlv-link" href="{h(href)}" target="_blank"{title}>'
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
    notes_html = _render_notes(item.get("notes", []))

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
    except Exception:
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
    except Exception:
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
    return f'<div class="git-actions">{"".join(items_html)}</div>'


def _render_submodule_rows(submodules, worktree=False):
    if not submodules:
        return ""
    extra = " git-submodule-of-worktree" if worktree else ""
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
            f'<div class="git-row git-submodule{extra}{dirty_cls}" title="{h(sub["path"])}">'
            f"{sub_actions}"
            f'<span class="git-name">\u2514 {h(sub["name"])}</span>'
            f'<span class="git-branch"></span>'
            f'<span class="git-status">{badge}</span>'
            f'<span class="git-spacer"></span></div>'
        )
    inner = "\n".join(rows)
    return f'<div class="git-submodules collapsed">\n{inner}\n</div>'


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

    template = _template_path().read_text(encoding="utf-8")
    template = template.replace("{{CARDS}}", cards)
    template = template.replace("{{GIT_REPOS}}", git_html)
    return (
        template.replace("{{TIMESTAMP}}", now)
        .replace("{{COUNT_CURRENT}}", str(count_current))
        .replace("{{COUNT_NEXT}}", str(count_next))
        .replace("{{COUNT_BACKLOG}}", str(count_backlog))
        .replace("{{COUNT_DONE}}", str(count_done))
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


def _render_note(full_path):
    try:
        text = full_path.read_text(encoding="utf-8")
    except Exception:
        return '<p class="note-error">Unable to read note.</p>'
    note_dir_rel = str(full_path.parent.relative_to(BASE_DIR))
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
    except Exception:
        pass
    return f'<pre class="note-raw">{h(text)}</pre>'


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
    """Public: validate a note/README path for the /note endpoint."""
    if ".." in rel_path or not _VALID_NOTE_RE.match(rel_path):
        return None
    full = (BASE_DIR / rel_path).resolve()
    try:
        full.relative_to(BASE_DIR.resolve())
    except ValueError:
        return None
    return full if full.is_file() else None


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
            except Exception:
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
    except Exception:
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
        print(f"[open] unknown slot: {slot_key!r}", file=sys.stderr)
        return False
    candidates = slot.resolve(path_str)
    if not candidates:
        print(f"[open] {slot_key}: no commands configured", file=sys.stderr)
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
            print(f"[open] {slot_key}: launched {cmd[0]}", file=sys.stderr)
            return True
        except FileNotFoundError as exc:
            last_err = exc
            continue
        except Exception as exc:
            print(f"[open] {slot_key}: {cmd[0]} failed: {exc}", file=sys.stderr)
            return False
    print(
        f"[open] {slot_key}: no launcher found (last error: {last_err})",
        file=sys.stderr,
    )
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
