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
    # Split-pane modal needs raw YAML bodies alongside the parsed form data.
    assert "repositories_yaml_body" in body
    assert "preferences_yaml_body" in body


def test_config_yaml_post_writes_repositories(cfg: CondashConfig):
    """POST /config/yaml applies a raw YAML body and rewrites the file."""
    client = _client(cfg)
    # Seed a minimal repositories.yml so the loader has something to overlay.
    (cfg.conception_path / "config").mkdir(parents=True, exist_ok=True)
    body = (
        "workspace_path: /tmp/ws\n"
        "repositories:\n"
        "  primary:\n"
        "    - alpha\n"
        "    - beta\n"
        "  secondary: []\n"
        "open_with:\n"
        "  main_ide: {label: 'Open in main IDE', commands: ['idea {path}']}\n"
        "  secondary_ide: {label: 'Open in secondary IDE', commands: ['code {path}']}\n"
        "  terminal: {label: 'Open terminal here', commands: ['xterm']}\n"
    )
    response = client.post("/config/yaml", json={"file": "repositories", "body": body})
    assert response.status_code == 200, response.text
    assert response.json()["ok"] is True
    on_disk = (cfg.conception_path / "config" / "repositories.yml").read_text(encoding="utf-8")
    assert "- alpha" in on_disk
    assert "- beta" in on_disk


def test_config_yaml_post_rejects_malformed_yaml(cfg: CondashConfig):
    client = _client(cfg)
    response = client.post(
        "/config/yaml", json={"file": "repositories", "body": "foo: [unterminated"}
    )
    assert response.status_code == 400
    assert "malformed" in response.json()["error"].lower()


def test_config_yaml_post_rejects_unknown_file(cfg: CondashConfig):
    client = _client(cfg)
    response = client.post("/config/yaml", json={"file": "bogus", "body": "a: 1"})
    assert response.status_code == 400


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


def test_api_items_creates_project_and_renders_in_dashboard(cfg: CondashConfig):
    """POST /api/items writes the folder; the next GET / sees the new
    card alongside the seed item. Closes the loop between the backend
    scaffolder and the round-trip the UI depends on."""
    client = _client(cfg)
    response = client.post(
        "/api/items",
        json={
            "title": "Dashboard-created item",
            "slug": "dashboard-created-item",
            "kind": "project",
            "status": "now",
            "apps": "condash",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["slug"] == "dashboard-created-item"

    root_response = client.get("/")
    assert root_response.status_code == 200
    assert "dashboard-created-item" in root_response.text


def test_api_items_rejects_bad_slug(cfg: CondashConfig):
    client = _client(cfg)
    response = client.post(
        "/api/items",
        json={
            "title": "x",
            "slug": "Has Capital",
            "kind": "project",
            "status": "now",
        },
    )
    assert response.status_code == 400
    assert response.json()["ok"] is False


def test_api_items_returns_409_on_collision(cfg: CondashConfig):
    client = _client(cfg)
    payload = {
        "title": "x",
        "slug": "duplicate-on-same-day",
        "kind": "project",
        "status": "now",
    }
    first = client.post("/api/items", json=payload)
    assert first.status_code == 200
    second = client.post("/api/items", json=payload)
    assert second.status_code == 409
    assert second.json()["ok"] is False


def test_note_serves_knowledge_files_at_any_subdir_depth(cfg: CondashConfig):
    """Knowledge files live at variable depth (root, one subdir, two subdirs after
    the 2026-04 topics/ restructure). ``validate_note_path`` must accept all of
    them — the previous regex capped depth at one subdir and 403'd everything
    under ``topics/ops/``, ``topics/security/``, ``topics/testing/``."""
    base = cfg.conception_path / "knowledge"
    (base / "topics" / "ops").mkdir(parents=True)
    (base / "conventions.md").write_text("# conventions\n\nroot body\n", encoding="utf-8")
    (base / "topics" / "index.md").write_text("# topics\n\nindex body\n", encoding="utf-8")
    (base / "topics" / "ops" / "dev-ports.md").write_text(
        "# dev-ports\n\nnested body\n", encoding="utf-8"
    )

    client = _client(cfg)
    for rel in (
        "knowledge/conventions.md",
        "knowledge/topics/index.md",
        "knowledge/topics/ops/dev-ports.md",
    ):
        res = client.get(f"/note?path={rel}")
        assert res.status_code == 200, f"{rel} → {res.status_code}: {res.text[:200]}"
        res_raw = client.get(f"/note-raw?path={rel}")
        assert res_raw.status_code == 200, (
            f"{rel} raw → {res_raw.status_code}: {res_raw.text[:200]}"
        )
