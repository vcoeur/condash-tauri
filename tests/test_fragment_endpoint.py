"""Tests for /fragment — the scoped-reload endpoint.

Contract:
  - Returns the HTML for one card / knowledge card / knowledge dir matching
    the given node id.
  - Returns 404 for anything the client should fall back on the global
    reload for (tab roots, priority groups, code nodes, unknown ids).
  - The returned HTML carries the matching ``data-node-id`` so the client
    can drop it straight into place.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from nicegui import app as _ng_app

from condash import app as app_mod
from condash.config import CondashConfig
from condash.context import build_ctx


def _client(cfg: CondashConfig) -> TestClient:
    app_mod._RUNTIME_CFG = cfg
    app_mod._RUNTIME_CTX = build_ctx(cfg)
    app_mod._register_routes()
    return TestClient(_ng_app)


def _write_knowledge(root: Path, rel_path: str, body: str = "body"):
    p = root / "knowledge" / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"# {p.stem}\n\n{body}\n", encoding="utf-8")
    return p


def test_fragment_missing_id(cfg: CondashConfig):
    client = _client(cfg)
    res = client.get("/fragment")
    assert res.status_code == 400


def test_fragment_unknown_prefix(cfg: CondashConfig):
    client = _client(cfg)
    res = client.get("/fragment", params={"id": "foo/bar"})
    assert res.status_code == 404


def test_fragment_project_card(cfg: CondashConfig):
    client = _client(cfg)
    # The conftest fixture writes one project at
    # projects/2026-01/2026-01-01-hello with priority 'now'.
    res = client.get("/fragment", params={"id": "projects/now/2026-01-01-hello"})
    assert res.status_code == 200, res.text
    assert 'data-node-id="projects/now/2026-01-01-hello"' in res.text
    assert 'class="card' in res.text


def test_fragment_project_card_not_found(cfg: CondashConfig):
    client = _client(cfg)
    res = client.get("/fragment", params={"id": "projects/now/does-not-exist"})
    assert res.status_code == 404


def test_fragment_project_group_returns_404(cfg: CondashConfig):
    # Groups fall back to the global reload — no fragment for them.
    client = _client(cfg)
    res = client.get("/fragment", params={"id": "projects/now"})
    assert res.status_code == 404


def test_fragment_projects_tab_returns_404(cfg: CondashConfig):
    client = _client(cfg)
    res = client.get("/fragment", params={"id": "projects"})
    assert res.status_code == 404


def test_fragment_knowledge_root_returns_404(cfg: CondashConfig, tmp_conception: Path):
    _write_knowledge(tmp_conception, "topics/foo.md")
    client = _client(cfg)
    res = client.get("/fragment", params={"id": "knowledge"})
    assert res.status_code == 404


def test_fragment_knowledge_directory(cfg: CondashConfig, tmp_conception: Path):
    _write_knowledge(tmp_conception, "topics/foo.md")
    client = _client(cfg)
    res = client.get("/fragment", params={"id": "knowledge/topics"})
    assert res.status_code == 200, res.text
    assert 'data-node-id="knowledge/topics"' in res.text
    assert "<details" in res.text


def test_fragment_knowledge_card(cfg: CondashConfig, tmp_conception: Path):
    _write_knowledge(tmp_conception, "topics/foo.md")
    client = _client(cfg)
    res = client.get("/fragment", params={"id": "knowledge/topics/foo.md"})
    assert res.status_code == 200, res.text
    assert 'data-node-id="knowledge/topics/foo.md"' in res.text
    assert "knowledge-card" in res.text


def test_fragment_knowledge_dir_not_found(cfg: CondashConfig, tmp_conception: Path):
    _write_knowledge(tmp_conception, "topics/foo.md")
    client = _client(cfg)
    res = client.get("/fragment", params={"id": "knowledge/does-not-exist"})
    assert res.status_code == 404


def test_fragment_code_tab_returns_404(cfg: CondashConfig):
    # Whole-tab / group ids still fall back to the global reload.
    client = _client(cfg)
    assert client.get("/fragment", params={"id": "code"}).status_code == 404
    assert client.get("/fragment", params={"id": "code/Primary"}).status_code == 404


def test_fragment_code_repo_unknown_returns_404(cfg: CondashConfig):
    client = _client(cfg)
    res = client.get("/fragment", params={"id": "code/Primary/missing-repo"})
    assert res.status_code == 404


def test_fragment_code_repo_returns_block(tmp_path: Path, tmp_conception: Path):
    """A workspace containing a repo surfaces a ``.git-repo`` fragment."""
    import subprocess as sp

    workspace = tmp_path / "workspace"
    repo = workspace / "demo"
    repo.mkdir(parents=True)
    sp.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    sp.run(
        ["git", "-C", str(repo), "commit", "--allow-empty", "-q", "-m", "init"],
        check=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
            "HOME": str(tmp_path),
            "PATH": "/usr/bin:/bin",
        },
    )
    cfg_with_ws = CondashConfig(
        conception_path=tmp_conception,
        workspace_path=workspace,
        port=0,
        native=False,
        repositories_primary=["demo"],
    )
    client = _client(cfg_with_ws)
    res = client.get("/fragment", params={"id": "code/Primary/demo"})
    assert res.status_code == 200, res.text
    assert 'data-node-id="code/Primary/demo"' in res.text
    assert 'class="git-repo' in res.text


def test_check_updates_returns_nodes_map(cfg: CondashConfig):
    client = _client(cfg)
    res = client.get("/check-updates")
    assert res.status_code == 200
    body = res.json()
    assert "nodes" in body
    assert "projects" in body["nodes"]
    assert "projects/now" in body["nodes"]
    assert "projects/now/2026-01-01-hello" in body["nodes"]
