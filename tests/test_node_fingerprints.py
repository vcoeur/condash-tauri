"""Tests for per-node fingerprint maps used by the localized-refresh feature.

Contract:
  - Editing one card dirty-marks only that card; its priority group and the
    projects tab stay stable.
  - Adding/removing/moving a card dirty-marks the affected group(s) and the
    projects tab, not sibling cards that didn't change.
  - Knowledge and git tab hierarchies follow the same contract.
"""

from __future__ import annotations

from pathlib import Path

from condash.context import build_ctx
from condash.parser import (
    collect_items,
    collect_knowledge,
    compute_knowledge_node_fingerprints,
    compute_project_node_fingerprints,
)


def _write_item(
    root: Path,
    slug: str,
    priority: str = "now",
    title: str = "",
    step: str = "first task",
):
    project = root / "projects" / "2026-01" / f"2026-01-01-{slug}"
    project.mkdir(parents=True, exist_ok=True)
    (project / "README.md").write_text(
        f"# {title or slug}\n\n"
        f"**Date**: 2026-01-01\n**Kind**: project\n**Status**: {priority}\n\n"
        f"## Steps\n\n- [ ] {step}\n",
        encoding="utf-8",
    )
    return project


# ------------------- projects -------------------


def test_project_fingerprints_node_ids(cfg, tmp_conception):
    """The map should contain ids at every level."""
    _write_item(tmp_conception, "alpha", "now")
    ctx = build_ctx(cfg)
    items = collect_items(ctx)
    fps = compute_project_node_fingerprints(items)
    assert "projects" in fps
    assert "projects/now" in fps
    assert "projects/now/2026-01-01-alpha" in fps


def test_editing_card_content_only_dirties_card(cfg, tmp_conception):
    """Changing a step should dirty only the card, not the group or tab."""
    _write_item(tmp_conception, "alpha", "now", step="before")
    _write_item(tmp_conception, "beta", "now")
    ctx = build_ctx(cfg)
    before = compute_project_node_fingerprints(collect_items(ctx))

    _write_item(tmp_conception, "alpha", "now", step="after")
    after = compute_project_node_fingerprints(collect_items(ctx))

    assert before["projects/now/2026-01-01-alpha"] != after["projects/now/2026-01-01-alpha"]
    # Group membership and tab membership are unchanged.
    assert before["projects/now"] == after["projects/now"]
    assert before["projects"] == after["projects"]
    # Sibling card is untouched.
    assert before["projects/now/2026-01-01-beta"] == after["projects/now/2026-01-01-beta"]


def test_adding_card_dirties_group_and_tab_not_siblings(cfg, tmp_conception):
    _write_item(tmp_conception, "alpha", "now")
    ctx = build_ctx(cfg)
    before = compute_project_node_fingerprints(collect_items(ctx))

    _write_item(tmp_conception, "beta", "now")
    after = compute_project_node_fingerprints(collect_items(ctx))

    assert before["projects/now"] != after["projects/now"]
    assert before["projects"] != after["projects"]
    assert before["projects/now/2026-01-01-alpha"] == after["projects/now/2026-01-01-alpha"]
    assert "projects/now/2026-01-01-beta" in after
    assert "projects/now/2026-01-01-beta" not in before


def test_moving_card_between_priorities_dirties_both_groups_and_tab(cfg, tmp_conception):
    _write_item(tmp_conception, "alpha", "now")
    _write_item(tmp_conception, "beta", "later")
    ctx = build_ctx(cfg)
    before = compute_project_node_fingerprints(collect_items(ctx))

    _write_item(tmp_conception, "alpha", "later")
    after = compute_project_node_fingerprints(collect_items(ctx))

    assert before["projects/now"] != after["projects/now"]
    assert before["projects/later"] != after["projects/later"]
    assert before["projects"] != after["projects"]
    # Card id changed because priority is part of the id.
    assert "projects/now/2026-01-01-alpha" not in after
    assert "projects/later/2026-01-01-alpha" in after
    # Sibling in the destination group is untouched.
    assert before["projects/later/2026-01-01-beta"] == after["projects/later/2026-01-01-beta"]


# ------------------- knowledge -------------------


def _write_knowledge(root: Path, rel_path: str, body: str = "body"):
    p = root / "knowledge" / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"# {p.stem}\n\n{body}\n", encoding="utf-8")
    return p


def test_knowledge_fingerprints_empty_tree(cfg):
    assert compute_knowledge_node_fingerprints(None) == {}


def test_knowledge_fingerprints_node_ids(cfg, tmp_conception):
    _write_knowledge(tmp_conception, "topics/foo.md")
    ctx = build_ctx(cfg)
    fps = compute_knowledge_node_fingerprints(collect_knowledge(ctx))
    assert "knowledge" in fps
    assert "knowledge/topics" in fps
    assert "knowledge/topics/foo.md" in fps


def test_knowledge_edit_only_dirties_card(cfg, tmp_conception):
    _write_knowledge(tmp_conception, "topics/foo.md", "first body")
    _write_knowledge(tmp_conception, "topics/bar.md")
    ctx = build_ctx(cfg)
    before = compute_knowledge_node_fingerprints(collect_knowledge(ctx))

    _write_knowledge(tmp_conception, "topics/foo.md", "changed body")
    after = compute_knowledge_node_fingerprints(collect_knowledge(ctx))

    assert before["knowledge/topics/foo.md"] != after["knowledge/topics/foo.md"]
    assert before["knowledge/topics"] == after["knowledge/topics"]
    assert before["knowledge"] == after["knowledge"]
    assert before["knowledge/topics/bar.md"] == after["knowledge/topics/bar.md"]


def test_knowledge_adding_card_dirties_only_parent_dir(cfg, tmp_conception):
    _write_knowledge(tmp_conception, "topics/foo.md")
    _write_knowledge(tmp_conception, "internal/apps.md")
    ctx = build_ctx(cfg)
    before = compute_knowledge_node_fingerprints(collect_knowledge(ctx))

    _write_knowledge(tmp_conception, "topics/baz.md")
    after = compute_knowledge_node_fingerprints(collect_knowledge(ctx))

    assert before["knowledge/topics"] != after["knowledge/topics"]
    # Sibling directory untouched.
    assert before["knowledge/internal"] == after["knowledge/internal"]
    # Root directory's direct children set didn't change.
    assert before["knowledge"] == after["knowledge"]
    # Existing card hash is unchanged.
    assert before["knowledge/topics/foo.md"] == after["knowledge/topics/foo.md"]


def test_knowledge_adding_top_level_dir_dirties_root(cfg, tmp_conception):
    _write_knowledge(tmp_conception, "topics/foo.md")
    ctx = build_ctx(cfg)
    before = compute_knowledge_node_fingerprints(collect_knowledge(ctx))

    _write_knowledge(tmp_conception, "newdir/entry.md")
    after = compute_knowledge_node_fingerprints(collect_knowledge(ctx))

    assert before["knowledge"] != after["knowledge"]
    assert before["knowledge/topics"] == after["knowledge/topics"]
