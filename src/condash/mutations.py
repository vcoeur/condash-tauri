"""File-mutation helpers — the write side of the dashboard.

Every handler here mutates a Markdown file in place under ``ctx.base_dir``:
flipping checkboxes, inserting new steps, renaming notes, moving done
items into ``YYYY-MM/`` archives. Paths must already be validated (via
:mod:`condash.paths`) before these functions see them — they do not
re-check the sandbox.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .context import RenderCtx
from .parser import (
    _ITEM_DIR_RE,
    _MONTH_DIR_RE,
    CHECKBOX_RE,
    HEADING2_RE,
    HEADING3_RE,
    METADATA_RE,
    PRIORITIES,
    STATUS_RE,
    parse_readme,
)
from .paths import _VALID_ITEM_FILE_RE, _VALID_NOTE_FILENAME_RE, _validate_path, validate_note_path

_KIND_MAP = {"incidents": "incident", "projects": "project", "documents": "document"}


def read_note_raw(ctx: RenderCtx, full_path: Path) -> dict[str, Any]:
    """Return the plain bytes + mtime for the edit surface."""
    stat_res = full_path.stat()
    content = full_path.read_text(encoding="utf-8", errors="replace")
    return {
        "path": str(full_path.relative_to(ctx.base_dir)),
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


def rename_note(ctx: RenderCtx, rel_path: str, new_stem: str) -> dict[str, Any]:
    """Rename a file under ``<item>/notes/`` while preserving its extension."""
    full = validate_note_path(ctx, rel_path)
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
        "path": str(new_path.relative_to(ctx.base_dir)),
        "mtime": new_path.stat().st_mtime,
    }


def create_note(ctx: RenderCtx, item_readme_rel: str, filename: str) -> dict[str, Any]:
    """Create an empty note file under the item's ``notes/`` directory."""
    item = _validate_path(ctx, item_readme_rel)
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
        "path": str(target.relative_to(ctx.base_dir)),
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


def _tidy(ctx: RenderCtx):
    moves = []
    for folder in ("incidents", "projects", "documents"):
        base = ctx.base_dir / folder
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
                item = parse_readme(ctx, readme, kind)
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
                    item = parse_readme(ctx, readme, kind)
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


def run_tidy(ctx: RenderCtx):
    """Public alias used by the CLI entry point."""
    return _tidy(ctx)


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
