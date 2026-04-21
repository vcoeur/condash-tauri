"""Playwright e2e fixtures.

Launches a real condash subprocess per test against a throwaway conception
tree, drives it from headless Chrome via Playwright, and tears it down on
exit. Keeps the in-process pytest smoke suite (``tests/test_*.py``) fast
by keeping the browser work isolated here behind ``make test-e2e``.

The recipe mirrors ``conception/knowledge/internal/condash.md`` — everything
happens in one process tree so the sandbox sees the listening socket, and
we pick a free port up-front rather than parsing NiceGUI's stdout.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

try:
    from playwright.sync_api import Browser, Page, Playwright, sync_playwright
except ImportError:  # pragma: no cover — the e2e extra is optional.
    pytest.skip(
        "playwright not installed — run `make dev-install-e2e` to enable the e2e suite.",
        allow_module_level=True,
    )


REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class CondashServer:
    """Handle for a running condash subprocess."""

    url: str
    port: int
    conception_path: Path
    process: subprocess.Popen


def _pick_free_port() -> int:
    """Bind-and-release to find a port nobody else is listening on right now."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _seed_conception(root: Path) -> None:
    """Write a minimal but realistic conception tree — one project with a Steps section."""
    project = root / "projects" / "2026-01" / "2026-01-01-e2e-demo"
    project.mkdir(parents=True)
    (project / "README.md").write_text(
        "# E2E demo project\n"
        "\n"
        "**Date**: 2026-01-01\n"
        "**Kind**: project\n"
        "**Status**: now\n"
        "**Apps**: `condash`\n"
        "\n"
        "## Goal\n"
        "\n"
        "Seed project used by Playwright smoke tests.\n"
        "\n"
        "## Steps\n"
        "\n"
        "- [ ] existing step\n",
        encoding="utf-8",
    )
    (project / "notes").mkdir()
    # A month index keeps condash's parser quiet.
    (root / "projects" / "2026-01" / "index.md").write_text(
        "# 2026-01\n\n- [E2E demo project](2026-01-01-e2e-demo/) — *smoke fixture*\n",
        encoding="utf-8",
    )
    (root / "projects" / "index.md").write_text(
        "# projects\n\nSmoke fixture.\n\n- [2026-01/](2026-01/index.md)\n",
        encoding="utf-8",
    )


def _wait_for_ready(host: str, port: int, timeout_s: float = 30.0) -> None:
    """Poll the TCP socket until the listener accepts connections.

    We deliberately avoid httpx / requests here: the host env advertises
    ALL_PROXY=socks5h://... which those libraries honour even for localhost
    (NO_PROXY only kicks in for HTTP proxies, not SOCKS), so a proxy-aware
    client would fail with a socksio missing-package error instead of
    actually probing the listener.
    """
    deadline = time.monotonic() + timeout_s
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return
        except OSError as err:
            last_err = err
        time.sleep(0.2)
    raise RuntimeError(
        f"condash did not accept connections on {host}:{port} within {timeout_s}s: {last_err}"
    )


@pytest.fixture
def condash_server(tmp_path: Path) -> Iterator[CondashServer]:
    """Start a fresh condash process for the test, yield its URL, kill on teardown."""
    conception = tmp_path / "conception"
    conception.mkdir()
    _seed_conception(conception)

    xdg_home = tmp_path / "xdg"
    (xdg_home / "condash").mkdir(parents=True)

    port = _pick_free_port()
    env = os.environ.copy()
    env["XDG_CONFIG_HOME"] = str(xdg_home)
    # Silence the browser.open the CLI triggers when --no-native is set.
    env["BROWSER"] = "true"
    # NiceGUI auto-activates its pytest-integration mode when it sees
    # PYTEST_CURRENT_TEST in the env, which requires a NICEGUI_SCREEN_TEST_PORT
    # we don't set. The child is a real user-facing process — strip the marker.
    env.pop("PYTEST_CURRENT_TEST", None)

    cmd = [
        "uv",
        "run",
        "condash",
        "--conception-path",
        str(conception),
        "--port",
        str(port),
        "--no-native",
    ]
    log_path = tmp_path / "condash.log"
    log_handle = log_path.open("wb")
    proc = subprocess.Popen(
        cmd,
        cwd=REPO_ROOT,
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,  # Own process group so we can kill cleanly.
    )

    url = f"http://127.0.0.1:{port}"
    try:
        _wait_for_ready("127.0.0.1", port)
    except Exception as err:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        log_handle.close()
        log = log_path.read_text(errors="replace")
        pytest.fail(f"condash failed to become ready at {url}: {err}\n---subprocess log---\n{log}")

    try:
        yield CondashServer(url=url, port=port, conception_path=conception, process=proc)
    finally:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


@pytest.fixture(scope="session")
def playwright() -> Iterator[Playwright]:
    with sync_playwright() as pw:
        yield pw


@pytest.fixture(scope="session")
def browser(playwright: Playwright) -> Iterator[Browser]:
    # System Chrome matches the sandbox recipe — no browser download needed.
    # Override via CONDASH_E2E_CHANNEL=chromium if the host has Playwright's own
    # bundled Chromium installed instead.
    channel = os.environ.get("CONDASH_E2E_CHANNEL", "chrome")
    launch_kwargs: dict = {"headless": True}
    if channel and channel != "chromium":
        launch_kwargs["channel"] = channel
    browser = playwright.chromium.launch(**launch_kwargs)
    try:
        yield browser
    finally:
        browser.close()


@pytest.fixture
def page(browser: Browser) -> Iterator[Page]:
    context = browser.new_context(viewport={"width": 1400, "height": 900})
    page = context.new_page()
    try:
        yield page
    finally:
        context.close()
