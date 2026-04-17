"""CLI smoke tests — cover the three subcommands every user runs on first install."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from condash.cli import app

runner = CliRunner()


def test_version_flag():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0, result.output
    assert result.stdout.strip().startswith("condash ")


def test_init_creates_config(tmp_home: Path):
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.output
    cfg_path = tmp_home / ".config" / "condash" / "config.toml"
    assert cfg_path.is_file()
    assert "conception_path" in cfg_path.read_text(encoding="utf-8")


def test_config_path_prints_path(tmp_home: Path):
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["config", "path"])
    assert result.exit_code == 0, result.output
    assert "config.toml" in result.stdout


def test_config_path_json(tmp_home: Path):
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["config", "path", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["config_file"].endswith("config.toml")
    assert payload["exists"] is True


def test_config_show_json_is_valid(tmp_home: Path):
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["config", "show", "--json"])
    assert result.exit_code == 0, result.output
    parsed = json.loads(result.stdout)
    # A freshly-seeded config leaves every path field commented out — the
    # CLI still renders them as keys with null values.
    assert "conception_path" in parsed
    assert "port" in parsed
    assert "open_with" in parsed
