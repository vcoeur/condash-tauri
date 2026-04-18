"""Workspace scanning behaviour in ``git_scan._collect_git_repos``.

Covers:

- Depth-1: direct git repos under ``workspace_path``.
- Depth-2: org-grouped layout — ``workspace_path`` is a parent of org
  folders; repos inside an org folder get ``<org>/<repo>`` display names.
- Mixed (depth-1 and depth-2 repos under the same workspace).
- No recursion past depth 2.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from condash.config import CondashConfig, OpenWithSlot, TerminalConfig
from condash.context import build_ctx
from condash.git_scan import _collect_git_repos


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True, capture_output=True)
    # A commit keeps `git status --porcelain` clean and `rev-parse HEAD` valid.
    (path / ".gitkeep").write_text("", encoding="utf-8")
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    subprocess.run(["git", "-C", str(path), "add", "."], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "commit", "-q", "-m", "init"],
        check=True,
        capture_output=True,
        env={**{"HOME": str(path)}, **env},
    )


def _cfg(workspace: Path) -> CondashConfig:
    return CondashConfig(
        conception_path=workspace.parent,
        workspace_path=workspace,
        repositories_primary=[],
        repositories_secondary=[],
        open_with={
            "main_ide": OpenWithSlot(label="x", commands=["true"]),
            "secondary_ide": OpenWithSlot(label="x", commands=["true"]),
            "terminal": OpenWithSlot(label="x", commands=["true"]),
        },
        terminal=TerminalConfig(),
    )


def test_depth_1_flat_workspace(tmp_path: Path) -> None:
    ws = tmp_path / "workspace"
    _init_repo(ws / "alpha")
    _init_repo(ws / "beta")

    cfg = _cfg(ws)
    ctx = build_ctx(cfg)
    groups = _collect_git_repos(ctx)

    # No primary/secondary configured → everything in "Others".
    names = sorted(r["name"] for _, repos in groups for r in repos)
    assert names == ["alpha", "beta"]


def test_depth_2_org_grouped_workspace(tmp_path: Path) -> None:
    ws = tmp_path / "src"
    _init_repo(ws / "myorg" / "backend")
    _init_repo(ws / "myorg" / "frontend")
    _init_repo(ws / "vcoeur" / "condash")

    cfg = _cfg(ws)
    ctx = build_ctx(cfg)
    groups = _collect_git_repos(ctx)

    names = sorted(r["name"] for _, repos in groups for r in repos)
    assert names == ["myorg/backend", "myorg/frontend", "vcoeur/condash"]


def test_mixed_depth_1_and_depth_2(tmp_path: Path) -> None:
    ws = tmp_path / "src"
    _init_repo(ws / "myorg" / "backend")
    _init_repo(ws / "standalone")  # depth-1 hit alongside org folders

    cfg = _cfg(ws)
    ctx = build_ctx(cfg)
    groups = _collect_git_repos(ctx)

    names = sorted(r["name"] for _, repos in groups for r in repos)
    assert names == ["myorg/backend", "standalone"]


def test_no_recursion_past_depth_2(tmp_path: Path) -> None:
    ws = tmp_path / "src"
    _init_repo(ws / "myorg" / "subgroup" / "deep-repo")

    cfg = _cfg(ws)
    ctx = build_ctx(cfg)
    groups = _collect_git_repos(ctx)

    names = [r["name"] for _, repos in groups for r in repos]
    # The deep-repo is at depth 3 — not reachable.
    assert names == []


def test_missing_workspace_yields_no_groups(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path / "does-not-exist")
    ctx = build_ctx(cfg)
    assert _collect_git_repos(ctx) == []


@pytest.fixture(autouse=True)
def _isolate_git_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep git commits out of the user's global config / gpg signing."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", "/dev/null")
