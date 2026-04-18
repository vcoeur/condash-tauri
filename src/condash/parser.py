"""Markdown parsing for conception items and the knowledge tree.

Entry points:
  - :func:`parse_readme` — read one item's ``README.md`` into the dict shape
    the rest of the package consumes.
  - :func:`collect_items` — walk every item folder under ``ctx.base_dir``.
  - :func:`collect_knowledge` — walk ``knowledge/`` recursively.
  - :func:`_compute_fingerprint` — cheap hash the ``/check-updates`` route
    runs to decide whether clients must re-fetch.
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


def _list_item_tree(ctx: RenderCtx, item_dir, max_depth: int = 3):
    """Recursive tree of files under ``item_dir`` grouped per subdirectory.

    Returns ``{"files": [FileEntry, ...], "groups": [GroupEntry, ...]}`` where
    ``GroupEntry`` is ``{"rel_dir", "label", "files", "groups"}``. Walks up
    to ``max_depth`` levels so deeply-nested layouts (``notes/drafts/…``)
    show as nested groups. Hidden entries (``.…``) and the item's
    top-level ``README.md`` are skipped — the README has its own preview
    link on the card. Empty subdirectories are kept so a freshly-created
    folder shows up immediately as an empty group.
    """
    if not item_dir.is_dir():
        return {"files": [], "groups": []}

    def walk(current: Path, depth: int) -> dict:
        files: list[dict[str, str]] = []
        groups: list[dict] = []
        for entry in sorted(current.iterdir()):
            if entry.name.startswith("."):
                continue
            if entry.is_dir():
                if depth >= max_depth:
                    continue
                child = walk(entry, depth + 1)
                rel_dir = str(entry.relative_to(item_dir))
                groups.append(
                    {
                        "rel_dir": rel_dir,
                        "label": entry.name,
                        "files": child["files"],
                        "groups": child["groups"],
                    }
                )
                continue
            if not entry.is_file():
                continue
            if depth == 1 and entry.name == "README.md":
                continue
            files.append(
                {
                    "name": entry.name,
                    "path": str(entry.relative_to(ctx.base_dir)),
                    "kind": _note_kind(entry),
                }
            )
        return {"files": files, "groups": groups}

    return walk(item_dir, 1)


def _flatten_tree_paths(tree: dict) -> list[str]:
    """Collect every file path in the tree, in stable depth-first order.
    Used by the fingerprint helpers — the tree's own ordering is the
    sort key, no need for a second sort."""
    paths: list[str] = [n["path"] for n in tree.get("files", [])]
    for g in tree.get("groups", []):
        paths.extend(_flatten_tree_paths(g))
    return paths


def parse_readme(ctx: RenderCtx, path, kind: str | None = None):
    """Parse a single item README.

    Kind is read from the ``**Kind**`` metadata field. The ``kind`` argument is
    a fallback used by tests and callers that already know the kind; it is
    overridden by the README header whenever present.
    """
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

    files = _list_item_tree(ctx, path.parent)

    done = sum(it["done"] for s in sections for it in s["items"])
    total = sum(len(s["items"]) for s in sections)

    priority = meta.get("status", "backlog").lower()
    if priority not in PRIORITIES:
        priority = "backlog"

    resolved_kind = meta.get("kind", "").lower() or kind or "project"

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
        "files": files,
        "done": done,
        "total": total,
        "path": str(path.relative_to(ctx.base_dir)),
        "kind": resolved_kind,
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
    return collect_tree(ctx, "knowledge", root_label="Knowledge")


def collect_tree(ctx: RenderCtx, root_name: str, root_label: str) -> dict | None:
    """Generic tree walker shared by the knowledge and code explorers.

    ``root_name`` is the directory under ``ctx.base_dir`` (``"knowledge"`` or
    ``"code"``). ``root_label`` is the human-readable label used at the root
    node only. The returned shape is:

    ``{name, label, rel_dir, index?, body[], children[], count}``

    matching the long-standing knowledge-tree contract. Non-markdown files
    are skipped; dot-files are skipped; empty subtrees are pruned.
    """
    root = ctx.base_dir / root_name
    if not root.is_dir():
        return None
    return _tree_node(ctx, root, root_dir=root, root_label=root_label)


def _tree_node(ctx: RenderCtx, d: Path, *, root_dir: Path, root_label: str) -> dict:
    """Build one tree node for directory ``d``."""
    is_root = d == root_dir
    label = root_label if is_root else d.name.replace("_", " ").replace("-", " ").title()
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
            child = _tree_node(ctx, entry, root_dir=root_dir, root_label=root_label)
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
    """Find and parse every item README under ``projects/``.

    Every item lives at ``projects/YYYY-MM/YYYY-MM-DD-slug/README.md`` and carries
    its kind (``project``/``incident``/``document``) in the ``**Kind**`` header.
    """
    items = []
    base = ctx.base_dir / "projects"
    if not base.is_dir():
        return items
    for readme in sorted(base.glob("*/*/README.md")):
        item = parse_readme(ctx, readme)
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
        files = tuple(_flatten_tree_paths(item.get("files") or {}))
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
                files,
            )
        )
    return hashlib.md5(repr(data).encode()).hexdigest()[:16]


def _hash(data) -> str:
    """MD5 of ``repr(data)`` truncated to 16 hex chars — the fingerprint pattern used everywhere."""
    return hashlib.md5(repr(data).encode()).hexdigest()[:16]


def _card_content_data(item):
    """Deterministic content tuple for one project card — changes iff the
    card's user-visible content changes. Priority is *not* included here so a
    priority change only re-keys the id (card moves groups), it doesn't also
    content-dirty the card itself."""
    sections = tuple(
        (s["heading"], tuple((it["text"], it["status"]) for it in s["items"]))
        for s in item["sections"]
    )
    deliverables = tuple((d["label"], d["path"]) for d in item.get("deliverables", []))
    files = tuple(_flatten_tree_paths(item.get("files") or {}))
    return (
        item["slug"],
        item["title"],
        item["kind"],
        tuple(item["apps"]),
        item["summary"],
        sections,
        deliverables,
        files,
    )


def compute_project_node_fingerprints(items) -> dict[str, str]:
    """Return ``{node_id: hash}`` for the Projects tab hierarchy.

    Node-id scheme (slash-separated, prefix-matchable for ancestor checks):

      - ``projects`` — whole Projects tab. Hash = set of (priority, slug) pairs.
        Changes iff cards are added, removed, or moved between priorities.
      - ``projects/<priority>`` — priority group. Hash = set of slugs in that
        group. Changes iff cards are added or removed from that group.
      - ``projects/<priority>/<slug>`` — a single card. Hash = card content.
        Changes iff the card's visible fields change.

    The group hash deliberately ignores child content so a card edit
    dirty-marks only the card, not its enclosing group or tab. Cards added,
    removed, or moved bubble up naturally because they change group
    membership (which the group and tab hashes track).
    """
    out: dict[str, str] = {}

    by_priority: dict[str, list] = {}
    for item in items:
        by_priority.setdefault(item["priority"], []).append(item)

    # Per-card content hashes.
    for item in items:
        node_id = f"projects/{item['priority']}/{item['slug']}"
        out[node_id] = _hash(_card_content_data(item))

    # Per-group membership hashes.
    for priority, group in by_priority.items():
        slugs = tuple(sorted(i["slug"] for i in group))
        out[f"projects/{priority}"] = _hash(("group", priority, slugs))

    # Whole-tab membership hash.
    tab_data = tuple(sorted((i["priority"], i["slug"]) for i in items))
    out["projects"] = _hash(("tab", "projects", tab_data))

    return out


def _knowledge_card_content(entry: dict) -> tuple:
    """Fingerprint data for one knowledge card — title + desc + path."""
    return (entry.get("path"), entry.get("title"), entry.get("desc"))


def _walk_knowledge_nodes(node: dict, out: dict[str, str], parent_id: str | None = None) -> str:
    """Recursively emit fingerprints for a knowledge tree node and return
    this node's id so the parent can reference it in its children list."""
    rel_dir = node["rel_dir"]  # e.g. "knowledge" or "knowledge/topics"
    node_id = rel_dir  # directories use their rel_dir verbatim as the id

    child_ids: list[str] = []

    if node.get("index"):
        idx = node["index"]
        card_id = idx["path"]  # e.g. "knowledge/topics/index.md"
        out[card_id] = _hash(_knowledge_card_content(idx))
        child_ids.append(card_id)

    for entry in node.get("body", []):
        card_id = entry["path"]
        out[card_id] = _hash(_knowledge_card_content(entry))
        child_ids.append(card_id)

    for child in node.get("children", []):
        child_id = _walk_knowledge_nodes(child, out, parent_id=node_id)
        child_ids.append(child_id)

    # Directory membership hash — list of direct child ids, sorted.
    out[node_id] = _hash(("dir", node_id, tuple(sorted(child_ids))))
    return node_id


def find_knowledge_node(tree: dict | None, rel_dir: str) -> dict | None:
    """Return the knowledge tree node at ``rel_dir`` (e.g. ``knowledge/topics``) or None."""
    if tree is None:
        return None
    if tree["rel_dir"] == rel_dir:
        return tree
    for child in tree.get("children", []):
        found = find_knowledge_node(child, rel_dir)
        if found is not None:
            return found
    return None


def find_knowledge_card(tree: dict | None, path: str) -> dict | None:
    """Return the card entry (index or body) at file ``path`` or None."""
    if tree is None:
        return None
    idx = tree.get("index")
    if idx and idx["path"] == path:
        return idx
    for entry in tree.get("body", []):
        if entry["path"] == path:
            return entry
    for child in tree.get("children", []):
        found = find_knowledge_card(child, path)
        if found is not None:
            return found
    return None


def compute_knowledge_node_fingerprints(tree: dict | None) -> dict[str, str]:
    """Return ``{node_id: hash}`` for the Knowledge tree.

    Node-id scheme:

      - ``knowledge`` — root directory (tab level).
      - ``knowledge/<sub-path>`` — any nested directory.
      - ``knowledge/<sub-path>/<file>.md`` — a leaf card (including
        ``index.md`` badges).

    Directory hashes depend only on the set of direct child ids, so a card
    edit dirty-marks only that card. Adds/removes at a directory level
    dirty-mark just that directory.
    """
    if tree is None:
        return {}
    out: dict[str, str] = {}
    _walk_knowledge_nodes(tree, out)
    return out
