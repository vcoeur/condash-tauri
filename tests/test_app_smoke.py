"""Integration smoke — FastAPI routes behave against a throwaway conception tree."""

from __future__ import annotations

from fastapi.testclient import TestClient
from nicegui import app as _ng_app

from condash import app as app_mod
from condash.config import CondashConfig
from condash.context import build_ctx


def _client(cfg: CondashConfig) -> TestClient:
    """Wire up the FastAPI routes against ``cfg`` and return a TestClient."""
    app_mod._RUNTIME_CFG = cfg
    app_mod._RUNTIME_CTX = build_ctx(cfg)
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
    target = cfg.conception_path / "projects" / "2026-01" / "2026-01-01-hello" / "README.md"
    lines = target.read_text(encoding="utf-8").splitlines()
    step_line_index = lines.index("- [ ] first task")  # 0-based; matches legacy._toggle_checkbox

    response = client.post(
        "/toggle",
        json={
            "file": "projects/2026-01/2026-01-01-hello/README.md",
            "line": step_line_index,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["ok"] is True
    assert "- [x] first task" in target.read_text(encoding="utf-8")


def test_recent_screenshot_missing_dir(cfg: CondashConfig, tmp_path):
    cfg.terminal.screenshot_dir = str(tmp_path / "does-not-exist")
    client = _client(cfg)
    response = client.get("/recent-screenshot")
    assert response.status_code == 200
    body = response.json()
    assert body["path"] is None
    assert "does not exist" in body["reason"]


def test_recent_screenshot_empty_dir(cfg: CondashConfig, tmp_path):
    shots = tmp_path / "shots"
    shots.mkdir()
    cfg.terminal.screenshot_dir = str(shots)
    client = _client(cfg)
    response = client.get("/recent-screenshot")
    assert response.status_code == 200
    body = response.json()
    assert body["path"] is None
    assert body["dir"] == str(shots)
    assert "no image" in body["reason"]


def test_recent_screenshot_picks_newest(cfg: CondashConfig, tmp_path):
    import os
    import time

    shots = tmp_path / "shots"
    shots.mkdir()
    older = shots / "old.png"
    newer = shots / "new.jpg"
    other = shots / "notes.txt"
    older.write_bytes(b"a")
    newer.write_bytes(b"b")
    other.write_bytes(b"c")
    now = time.time()
    os.utime(older, (now - 100, now - 100))
    os.utime(newer, (now, now))
    os.utime(other, (now + 100, now + 100))  # newest, but not an image
    cfg.terminal.screenshot_dir = str(shots)
    client = _client(cfg)
    response = client.get("/recent-screenshot")
    assert response.status_code == 200
    assert response.json()["path"] == str(newer)


def test_download_rejects_traversal(cfg: CondashConfig):
    client = _client(cfg)
    # Path matches the /download/{rel_path:path} route so the handler runs
    # and exercises its `..` + regex + resolve guard. A raw `../../etc/...`
    # URL gets normalised before the router, so wedge the dot-dot inside a
    # plausible-looking prefix to reach the handler.
    response = client.get("/download/projects/2026-01/2026-01-01-hello/../../../etc/passwd")
    assert response.status_code == 403


def test_pdfjs_asset_serves_bundled_library(cfg: CondashConfig):
    """The vendored PDF.js library is reachable at /vendor/pdfjs/..."""
    client = _client(cfg)
    response = client.get("/vendor/pdfjs/build/pdf.mjs")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")
    # Non-empty JS payload — we shipped the real file, not an empty stub.
    assert len(response.content) > 1000


def test_pdfjs_asset_rejects_traversal(cfg: CondashConfig):
    client = _client(cfg)
    # URL-encode the dot-dot so the client doesn't normalise it away before
    # the request reaches the route — the handler's own `..` guard is what
    # we're asserting here.
    response = client.get("/vendor/pdfjs/%2e%2e/%2e%2e/%2e%2e/etc/passwd")
    assert response.status_code == 403


def test_pdfjs_asset_404_for_missing_file(cfg: CondashConfig):
    client = _client(cfg)
    response = client.get("/vendor/pdfjs/build/does-not-exist.mjs")
    assert response.status_code == 404


def test_pdf_note_emits_mount_point_not_iframe(cfg: CondashConfig):
    """`.pdf` notes render as a .note-pdf-host div so the in-dashboard
    PDF.js viewer can pick them up — not an <iframe> (that used to rely
    on Chromium's built-in PDF viewer, which is disabled in QtWebEngine)."""
    pdf_path = (
        cfg.conception_path / "projects" / "2026-01" / "2026-01-01-hello" / "notes" / "sample.pdf"
    )
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(b"%PDF-1.4\n%fake-pdf\n%%EOF\n")

    client = _client(cfg)
    response = client.get("/note?path=projects/2026-01/2026-01-01-hello/notes/sample.pdf")
    assert response.status_code == 200
    body = response.text
    assert "note-pdf-host" in body
    assert 'data-pdf-src="/file/' in body
    assert 'data-pdf-filename="sample.pdf"' in body
    assert "<iframe" not in body
