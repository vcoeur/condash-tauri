"""Render-layer tests for the inline dev-server runner UI.

Covers:
  - Run button appears on the repo row when ``run:`` is configured.
  - Fingerprint for the repo block changes when runner state flips
    (off → running → exited).
  - ``/fragment`` returns a ``.git-repo`` block for a code-node id.
"""

from __future__ import annotations

import asyncio
import subprocess as sp
from pathlib import Path

from fastapi.testclient import TestClient
from nicegui import app as _ng_app

from condash import app as app_mod
from condash import runners as runners_mod
from condash.config import CondashConfig, RepoRunCommand
from condash.context import build_ctx
from condash.git_scan import compute_git_node_fingerprints
from condash.render import render_git_repo_fragment


def _init_repo(path: Path, home: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    sp.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
        "HOME": str(home),
        "PATH": "/usr/bin:/bin",
    }
    sp.run(
        ["git", "-C", str(path), "commit", "--allow-empty", "-q", "-m", "init"],
        check=True,
        env=env,
    )


def _cfg(tmp_path: Path, tmp_conception: Path, run_template: str) -> CondashConfig:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _init_repo(workspace / "demo", tmp_path)
    return CondashConfig(
        conception_path=tmp_conception,
        workspace_path=workspace,
        port=0,
        native=False,
        repositories_primary=["demo"],
        repo_run={"demo": RepoRunCommand(template=run_template)},
    )


def test_render_includes_run_button(tmp_path: Path, tmp_conception: Path) -> None:
    cfg = _cfg(tmp_path, tmp_conception, "make dev")
    ctx = build_ctx(cfg)
    html = render_git_repo_fragment(ctx, "code/Primary/demo")
    assert html is not None
    assert "git-action-runner-run" in html
    assert "runnerStart(event," in html


def test_fragment_endpoint_serves_repo_block(tmp_path: Path, tmp_conception: Path) -> None:
    cfg = _cfg(tmp_path, tmp_conception, "make dev")
    app_mod._RUNTIME_CFG = cfg
    app_mod._RUNTIME_CTX = build_ctx(cfg)
    app_mod._register_routes()
    client = TestClient(_ng_app)
    res = client.get("/fragment", params={"id": "code/Primary/demo"})
    assert res.status_code == 200, res.text
    assert 'data-node-id="code/Primary/demo"' in res.text
    assert "git-action-runner-run" in res.text


def test_fingerprint_changes_on_runner_start(tmp_path: Path, tmp_conception: Path) -> None:
    """Repo-block fingerprint flips when a runner starts and again when it exits."""
    cfg = _cfg(tmp_path, tmp_conception, "echo hi")
    ctx = build_ctx(cfg)
    node_id = "code/Primary/demo"

    async def _body():
        before = compute_git_node_fingerprints(ctx)
        assert node_id in before

        session = await runners_mod.start(
            key="demo",
            checkout_key="main",
            path=str(cfg.workspace_path / "demo"),
            template="echo hi",
            shell="/bin/sh",
        )
        try:
            mid = compute_git_node_fingerprints(ctx)
            assert mid[node_id] != before[node_id]

            # Drain until the echo exits.
            import asyncio as _aio

            deadline = _aio.get_event_loop().time() + 3.0
            while session.exit_code is None:
                if _aio.get_event_loop().time() > deadline:
                    raise AssertionError("runner did not exit")
                await _aio.sleep(0.05)

            after_exit = compute_git_node_fingerprints(ctx)
            assert after_exit[node_id] != before[node_id]
            assert after_exit[node_id] != mid[node_id]
        finally:
            runners_mod.clear_exited("demo")

        cleared = compute_git_node_fingerprints(ctx)
        assert cleared[node_id] == before[node_id]

    asyncio.run(_body())
