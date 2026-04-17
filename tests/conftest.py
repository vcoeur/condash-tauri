"""Shared fixtures for the condash smoke tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from condash.config import CondashConfig, OpenWithSlot


@pytest.fixture
def tmp_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect $HOME and $XDG_CONFIG_HOME to a clean temp dir."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    return tmp_path


@pytest.fixture
def tmp_conception(tmp_path: Path) -> Path:
    """Create a minimal conception tree with one project containing one checkbox step."""
    root = tmp_path / "conception"
    project = root / "projects" / "2026-01-01-hello"
    project.mkdir(parents=True)
    (project / "README.md").write_text(
        "# Hello\n\n**Date**: 2026-01-01\n**Status**: now\n\n## Steps\n\n- [ ] first task\n",
        encoding="utf-8",
    )
    (root / "incidents").mkdir()
    (root / "documents").mkdir()
    return root


@pytest.fixture
def cfg(tmp_home: Path, tmp_conception: Path) -> CondashConfig:
    """A CondashConfig pointing at the throwaway conception tree."""
    return CondashConfig(
        conception_path=tmp_conception,
        port=0,
        native=False,
        open_with={
            "main_ide": OpenWithSlot(label="Open in main IDE", commands=["idea {path}"]),
            "secondary_ide": OpenWithSlot(label="Open in secondary IDE", commands=["code {path}"]),
            "terminal": OpenWithSlot(label="Open terminal here", commands=["xterm"]),
        },
    )
