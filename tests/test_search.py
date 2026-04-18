"""Tests for condash.search — history-tab search backend + /search-history."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from nicegui import app as _ng_app

from condash import app as app_mod
from condash.config import CondashConfig
from condash.context import build_ctx
from condash.parser import collect_items
from condash.search import _build_snippet, _tokenise, search_items


@pytest.fixture
def tree(tmp_conception: Path) -> Path:
    """Extend the minimal conception fixture with searchable content."""
    p1 = tmp_conception / "projects" / "2026-02" / "2026-02-01-soft-wrap"
    (p1 / "notes").mkdir(parents=True)
    (p1 / "README.md").write_text(
        "# Soft wrap long lines\n\n"
        "**Date**: 2026-02-01\n**Kind**: project\n**Status**: now\n\n"
        "## Goal\n\nMake long lines wrap in the terminal pane.\n\n"
        "## Steps\n\n- [ ] task\n",
        encoding="utf-8",
    )
    (p1 / "notes" / "plan.md").write_text(
        "# Plan\n\nUse xterm options for wrap behaviour; test with `tail -f`.\n",
        encoding="utf-8",
    )
    (p1 / "notes" / "raw-widths.md").write_text(
        "# Widths\n\nNothing relevant here.\n", encoding="utf-8"
    )
    (p1 / "notes" / "diagram.png").write_bytes(b"\x89PNG fake")

    p2 = tmp_conception / "projects" / "2026-03" / "2026-03-05-config-split"
    p2.mkdir(parents=True)
    (p2 / "README.md").write_text(
        "# Split config\n\n"
        "**Date**: 2026-03-05\n**Kind**: project\n**Status**: done\n\n"
        "## Goal\n\nSplit config into preferences and repositories.\n\n"
        "## Steps\n\n- [x] done\n",
        encoding="utf-8",
    )
    return tmp_conception


def _client(cfg: CondashConfig) -> TestClient:
    app_mod._RUNTIME_CFG = cfg
    app_mod._RUNTIME_CTX = build_ctx(cfg)
    app_mod._register_routes()
    return TestClient(_ng_app)


def test_tokenise_lowercases_and_dedupes():
    assert _tokenise("Foo  Bar foo") == ["foo", "bar"]
    assert _tokenise("") == []
    assert _tokenise("   ") == []


def test_build_snippet_marks_tokens():
    snip = _build_snippet("The quick brown fox jumps over", ["fox"], 10)
    assert "<mark>fox</mark>" in snip


def test_build_snippet_escapes_html():
    snip = _build_snippet("a <script>alert</script> foo bar", ["foo"], 40)
    assert "<script>" not in snip
    assert "&lt;script&gt;" in snip
    assert "<mark>foo</mark>" in snip


def test_build_snippet_empty_on_no_match():
    assert _build_snippet("no match here", ["zebra"], 10) == ""
    assert _build_snippet("", ["foo"], 10) == ""
    assert _build_snippet("text", [], 10) == ""


def test_search_empty_query_returns_empty(cfg: CondashConfig, tree: Path):
    ctx = build_ctx(cfg)
    items = collect_items(ctx)
    assert search_items(ctx, items, "") == []
    assert search_items(ctx, items, "   ") == []


def test_search_matches_note_body(cfg: CondashConfig, tree: Path):
    ctx = build_ctx(cfg)
    items = collect_items(ctx)
    results = search_items(ctx, items, "xterm")
    assert [r["slug"] for r in results] == ["2026-02-01-soft-wrap"]
    sources = {h["source"] for h in results[0]["hits"]}
    assert "note" in sources


def test_search_matches_readme_body(cfg: CondashConfig, tree: Path):
    ctx = build_ctx(cfg)
    items = collect_items(ctx)
    # "terminal" only appears in the README body (Goal section).
    results = search_items(ctx, items, "terminal")
    assert [r["slug"] for r in results] == ["2026-02-01-soft-wrap"]
    assert any(h["source"] == "readme" for h in results[0]["hits"])


def test_search_matches_filename_only(cfg: CondashConfig, tree: Path):
    ctx = build_ctx(cfg)
    items = collect_items(ctx)
    # The png is not content-indexed, so "diagram" can only hit on filename.
    results = search_items(ctx, items, "diagram")
    assert [r["slug"] for r in results] == ["2026-02-01-soft-wrap"]
    assert any(h["source"] == "filename" for h in results[0]["hits"])


def test_search_token_and(cfg: CondashConfig, tree: Path):
    ctx = build_ctx(cfg)
    items = collect_items(ctx)
    # Both tokens hit somewhere in the soft-wrap project's corpus.
    results = search_items(ctx, items, "wrap xterm")
    assert [r["slug"] for r in results] == ["2026-02-01-soft-wrap"]
    # "xterm" is only in soft-wrap, "preferences" is only in config-split —
    # no single project has both → zero matches.
    assert search_items(ctx, items, "xterm preferences") == []


def test_search_dedupes_filename_against_content(cfg: CondashConfig, tree: Path):
    ctx = build_ctx(cfg)
    items = collect_items(ctx)
    # "plan" matches notes/plan.md on filename AND on body — emit once,
    # with source "note" (content wins over filename).
    results = search_items(ctx, items, "plan")
    soft = next(r for r in results if r["slug"] == "2026-02-01-soft-wrap")
    plan_hits = [h for h in soft["hits"] if h["path"].endswith("notes/plan.md")]
    assert len(plan_hits) == 1
    assert plan_hits[0]["source"] == "note"


def test_search_header_match_alone(cfg: CondashConfig, tree: Path):
    ctx = build_ctx(cfg)
    items = collect_items(ctx)
    # "split" appears in the config-split project title + slug but not in any
    # file body — project still surfaces via the header corpus.
    results = search_items(ctx, items, "split")
    slugs = [r["slug"] for r in results]
    assert "2026-03-05-config-split" in slugs


def test_search_result_packs_subtab(cfg: CondashConfig, tree: Path):
    ctx = build_ctx(cfg)
    items = collect_items(ctx)
    results = search_items(ctx, items, "split")
    row = next(r for r in results if r["slug"] == "2026-03-05-config-split")
    assert row["status"] == "done"
    assert row["subtab"] == "done"
    assert row["month"] == "2026-03"


def test_search_history_route(cfg: CondashConfig, tree: Path):
    client = _client(cfg)
    res = client.get("/search-history", params={"q": "wrap"})
    assert res.status_code == 200
    body = res.json()
    assert isinstance(body, list)
    assert any(r["slug"] == "2026-02-01-soft-wrap" for r in body)


def test_search_history_route_empty_query(cfg: CondashConfig, tree: Path):
    client = _client(cfg)
    res = client.get("/search-history", params={"q": ""})
    assert res.status_code == 200
    assert res.json() == []
