"""Tests for unknown-Status surfacing in parser + render.

Covers both surfacing paths added when the enum lint project closed:

- :func:`condash.parser.parse_readme` logs a warning and exposes the original
  value under ``invalid_status`` when the README's ``**Status**`` is not in
  the canonical enum.
- :func:`condash.render._render_card` emits a visible badge in the card
  header so a user spots the typo in the dashboard.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from condash.config import CondashConfig
from condash.context import build_ctx
from condash.parser import collect_items
from condash.render import _render_card


def _write_item(root: Path, slug: str, status: str) -> None:
    item = root / "projects" / "2026-04" / slug
    item.mkdir(parents=True)
    (item / "README.md").write_text(
        f"# {slug}\n\n"
        f"**Date**: 2026-04-18\n**Kind**: project\n**Status**: {status}\n\n"
        "## Steps\n\n- [ ] task\n",
        encoding="utf-8",
    )


def test_parser_flags_unknown_status_and_coerces_to_backlog(
    cfg: CondashConfig, tmp_conception: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _write_item(tmp_conception, "2026-04-18-typo", "active")

    with caplog.at_level(logging.WARNING, logger="condash.parser"):
        items = collect_items(build_ctx(cfg))

    bad = next(it for it in items if it["slug"] == "2026-04-18-typo")
    assert bad["priority"] == "backlog"
    assert bad["invalid_status"] == "active"

    messages = [r.getMessage() for r in caplog.records if r.name == "condash.parser"]
    assert any("unknown Status" in m and "active" in m and "backlog" in m for m in messages)


def test_parser_accepts_canonical_status_without_warning(
    cfg: CondashConfig, tmp_conception: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _write_item(tmp_conception, "2026-04-18-ok", "soon")

    with caplog.at_level(logging.WARNING, logger="condash.parser"):
        items = collect_items(build_ctx(cfg))

    ok = next(it for it in items if it["slug"] == "2026-04-18-ok")
    assert ok["priority"] == "soon"
    assert ok["invalid_status"] is None

    parser_warnings = [r for r in caplog.records if r.name == "condash.parser"]
    assert parser_warnings == []


def test_render_card_shows_invalid_badge() -> None:
    item = {
        "slug": "2026-04-18-typo",
        "title": "Typo project",
        "date": "2026-04-18",
        "priority": "backlog",
        "invalid_status": "active",
        "apps": [],
        "severity": None,
        "summary": "",
        "sections": [],
        "deliverables": [],
        "files": {"files": [], "groups": []},
        "done": 0,
        "total": 0,
        "path": "projects/2026-04/2026-04-18-typo/README.md",
        "kind": "project",
    }
    html = _render_card(item)
    assert "invalid-status-badge" in html
    assert "active" in html
    assert "treated as backlog" in html


def test_render_card_omits_badge_when_status_valid() -> None:
    item = {
        "slug": "2026-04-18-ok",
        "title": "Fine project",
        "date": "2026-04-18",
        "priority": "soon",
        "invalid_status": None,
        "apps": [],
        "severity": None,
        "summary": "",
        "sections": [],
        "deliverables": [],
        "files": {"files": [], "groups": []},
        "done": 0,
        "total": 0,
        "path": "projects/2026-04/2026-04-18-ok/README.md",
        "kind": "project",
    }
    html = _render_card(item)
    assert "invalid-status-badge" not in html
