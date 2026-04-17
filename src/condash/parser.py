"""Markdown parsing for conception items and the knowledge tree.

Entry points:
  - :func:`parse_readme` — read one item's ``README.md`` into the dict shape
    the rest of the package consumes.
  - :func:`collect_items` — walk every item folder under ``ctx.base_dir``.
  - :func:`collect_knowledge` — walk ``knowledge/`` recursively.
  - :func:`_compute_fingerprint` / :func:`_tidy_needed` — cheap checks the
    ``/check-updates`` route runs to decide whether clients must re-fetch.
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path

from .context import RenderCtx

log = logging.getLogger(__name__)

METADATA_RE = re.compile(r"^\*\*(.+?)\*\*\s*:\s*(.+)$")
CHECKBOX_RE = re.compile(r"^(\s*)-\s*\[([ xX~\-])\]\s+(.+)$")
HEADING2_RE = re.compile(r"^##\s+(.+)$")
HEADING3_RE = re.compile(r"^###\s+(.+)$")
STATUS_RE = re.compile(r"^\*\*Status\*\*\s*:\s*.*$", re.IGNORECASE)
DELIVERABLE_RE = re.compile(r"-\s+\[([^\]]+)\]\(([^)]+\.pdf)\)(?:\s*[—–-]\s*(.+))?$")

PRIORITIES = ("now", "soon", "later", "backlog", "review", "done")
PRI_ORDER = {p: i for i, p in enumerate(PRIORITIES)}

_MONTH_DIR_RE = re.compile(r"^\d{4}-\d{2}$")
_ITEM_DIR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-.+$")

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


def _list_notes(ctx: RenderCtx, item_dir, max_depth: int = 2):
    """List every file under ``<item_dir>/notes/`` with its detected kind.

    Walks up to ``max_depth`` levels of subdirectories so items can group
    related files (e.g. ``notes/drafts/…``) without the dashboard flattening
    the structure. Hidden files and dirs (``.…``) are skipped.
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
                    "path": str(entry.relative_to(ctx.base_dir)),
                    "kind": _note_kind(entry),
                }
            )

    walk(notes_dir, 1)
    return out


def parse_readme(ctx: RenderCtx, path, kind):
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
    item_dir = str(path.parent.relative_to(ctx.base_dir))
    for d in deliverables:
        d["full_path"] = f"{item_dir}/{d['path']}"

    notes = _list_notes(ctx, path.parent)

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
        "path": str(path.relative_to(ctx.base_dir)),
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


def collect_knowledge(ctx: RenderCtx) -> dict | None:
    """Scan ``knowledge/`` recursively and return a tree for the explorer tab.

    Returns ``None`` if ``knowledge/`` doesn't exist under ``ctx.base_dir``.
    """
    root = ctx.base_dir / "knowledge"
    if not root.is_dir():
        return None
    return _knowledge_node(ctx, root)


def _knowledge_node(ctx: RenderCtx, d: Path) -> dict:
    """Build one tree node for directory ``d``."""
    is_root = d == ctx.base_dir / "knowledge"
    label = "Knowledge" if is_root else d.name.replace("_", " ").replace("-", " ").title()
    index: dict[str, str] | None = None
    body: list[dict[str, str]] = []
    children: list[dict] = []
    for entry in sorted(d.iterdir()):
        if entry.name.startswith("."):
            continue
        if entry.is_file() and entry.suffix.lower() == ".md":
            title, desc = _knowledge_title_and_desc(entry)
            item = {"path": str(entry.relative_to(ctx.base_dir)), "title": title, "desc": desc}
            if entry.name == "index.md":
                index = item
            else:
                body.append(item)
        elif entry.is_dir():
            child = _knowledge_node(ctx, entry)
            # Drop empty subtrees so the UI doesn't render lone headings.
            if child["count"] > 0:
                children.append(child)
    count = len(body) + (1 if index else 0) + sum(c["count"] for c in children)
    return {
        "name": "" if is_root else d.name,
        "label": label,
        "rel_dir": str(d.relative_to(ctx.base_dir)),
        "index": index,
        "body": body,
        "children": children,
        "count": count,
    }


def collect_items(ctx: RenderCtx):
    """Find and parse all incident/project/document READMEs."""
    items = []
    for kind, folder in [
        ("incident", "incidents"),
        ("project", "projects"),
        ("document", "documents"),
    ]:
        base = ctx.base_dir / folder
        if not base.is_dir():
            continue
        readmes = set(base.glob("*/README.md")) | set(base.glob("*/*/README.md"))
        for readme in sorted(readmes):
            item = parse_readme(ctx, readme, kind)
            if item:
                items.append(item)

    return items


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
