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

import logging
import os
import re
import shlex
import subprocess
import sys
from importlib.resources import files as _package_files
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
from .render import (  # noqa: F401 — re-exported for backward compat during the Phase 1 split
    _ICON_SVGS,
    _IMG_SRC_RE,
    _render_card,
    _render_deliverables,
    _render_git_actions,
    _render_git_repos,
    _render_group,
    _render_index_badge,
    _render_knowledge,
    _render_knowledge_card,
    _render_knowledge_group,
    _render_markdown,
    _render_note,
    _render_notes,
    _render_readme_link,
    _render_step,
    _render_submodule_rows,
    _rewrite_img_src,
    h,
    render_page,
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


# ---------------------------------------------------------------------------
# Editing
# ---------------------------------------------------------------------------


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
