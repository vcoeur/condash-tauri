"""Integration smoke — FastAPI routes behave against a throwaway conception tree."""

from __future__ import annotations

from fastapi.testclient import TestClient
from nicegui import app as _ng_app

from condash import app as app_mod
from condash import legacy
from condash.config import CondashConfig


def _client(cfg: CondashConfig) -> TestClient:
    """Wire up the FastAPI routes against ``cfg`` and return a TestClient."""
    app_mod._RUNTIME_CFG = cfg
    legacy.init(cfg)
    app_mod._register_routes()
    return TestClient(_ng_app)


def test_root_renders(cfg: CondashConfig):
    client = _client(cfg)
    response = client.get("/")
    assert response.status_code == 200
    assert "2026-01-01-hello" in response.text


def test_config_get(cfg: CondashConfig):
    client = _client(cfg)
    response = client.get("/config")
    assert response.status_code == 200
    body = response.json()
    assert body["conception_path"] == str(cfg.conception_path)
    assert body["port"] == 0
    assert body["native"] is False


def test_toggle_flips_checkbox(cfg: CondashConfig):
    client = _client(cfg)
    target = cfg.conception_path / "projects" / "2026-01-01-hello" / "README.md"
    lines = target.read_text(encoding="utf-8").splitlines()
    step_line_index = lines.index("- [ ] first task")  # 0-based; matches legacy._toggle_checkbox

    response = client.post(
        "/toggle",
        json={
            "file": "projects/2026-01-01-hello/README.md",
            "line": step_line_index,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["ok"] is True
    assert "- [x] first task" in target.read_text(encoding="utf-8")


def test_download_rejects_traversal(cfg: CondashConfig):
    client = _client(cfg)
    # Path matches the /download/{rel_path:path} route so the handler runs
    # and exercises its `..` + regex + resolve guard. A raw `../../etc/...`
    # URL gets normalised before the router, so wedge the dot-dot inside a
    # plausible-looking prefix to reach the handler.
    response = client.get("/download/projects/2026-01-01-hello/../../etc/passwd")
    assert response.status_code == 403
