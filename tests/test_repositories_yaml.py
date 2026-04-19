"""YAML migration + round-trip for ``<conception_path>/config/*.yml``.

Covers:

- TOML → ``config/repositories.yml`` migration (legacy ``[repositories]``
  / ``[open_with]`` sections).
- TOML → ``config/preferences.yml`` migration (legacy ``pdf_viewer`` +
  ``[terminal]``).
- YAML-overlay-wins-over-stale-TOML.
- Degraded mode when ``conception_path`` is unset.
- Malformed YAML raises ``ConfigIncompleteError``.

PR base branch is inferred by ``/pr`` from git at call time, not stored
here; there is no yaml field for it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from condash import config as cfg_mod


def _write_toml(path: Path, conception: Path, workspace: Path) -> None:
    path.write_text(
        f"""conception_path = "{conception}"
workspace_path = "{workspace}"
worktrees_path = "{workspace}/../worktrees"
port = 0
native = true
pdf_viewer = ["evince {{path}}"]

[repositories]
primary = ["alpha", {{ name = "mono", submodules = ["apps/web", "apps/api"] }}]
secondary = ["beta"]

[open_with.main_ide]
label = "Open in main IDE"
commands = ["idea {{path}}"]

[open_with.secondary_ide]
label = "Open in secondary IDE"
commands = ["code {{path}}"]

[open_with.terminal]
label = "Open terminal here"
commands = ["xterm"]

[terminal]
shortcut = "Ctrl+T"
launcher_command = "claude"
""",
        encoding="utf-8",
    )


def test_legacy_toml_loads_when_no_yaml(tmp_path: Path) -> None:
    conception = tmp_path / "conception"
    conception.mkdir()
    toml = tmp_path / "config.toml"
    _write_toml(toml, conception, tmp_path / "workspace")

    cfg = cfg_mod.load(toml)

    assert cfg.repositories_primary == ["alpha", "mono"]
    assert cfg.repositories_secondary == ["beta"]
    assert cfg.repo_submodules == {"mono": ["apps/web", "apps/api"]}
    assert cfg.open_with["main_ide"].commands == ["idea {path}"]
    assert cfg.pdf_viewer == ["evince {path}"]
    assert cfg.terminal.shortcut == "Ctrl+T"
    assert cfg.yaml_source is None
    assert cfg.preferences_source is None


def test_save_migrates_legacy_toml_to_both_yamls(tmp_path: Path) -> None:
    conception = tmp_path / "conception"
    conception.mkdir()
    toml = tmp_path / "config.toml"
    _write_toml(toml, conception, tmp_path / "workspace")

    cfg = cfg_mod.load(toml)
    cfg_mod.save(cfg, toml)

    repos_yml = conception / "config" / "repositories.yml"
    prefs_yml = conception / "config" / "preferences.yml"
    assert repos_yml.is_file(), "repositories.yml must be created on first save"
    assert prefs_yml.is_file(), "preferences.yml must be created on first save"

    repos_body = repos_yml.read_text(encoding="utf-8")
    assert repos_body.startswith("# Versioned workspace config"), "repositories header present"
    assert "alpha" in repos_body
    assert "apps/web" in repos_body

    prefs_body = prefs_yml.read_text(encoding="utf-8")
    assert prefs_body.startswith("# Versioned user preferences"), "preferences header present"
    assert "evince {path}" in prefs_body
    assert "Ctrl+T" in prefs_body

    # TOML: YAML-managed keys stripped; boot keys retained.
    toml_body = toml.read_text(encoding="utf-8")
    assert "[repositories]" not in toml_body
    assert "[open_with" not in toml_body
    assert "[terminal]" not in toml_body
    assert "workspace_path" not in toml_body
    assert "worktrees_path" not in toml_body
    assert "pdf_viewer" not in toml_body
    assert "conception_path" in toml_body
    assert "port = 0" in toml_body


def test_reload_after_migration_uses_yamls(tmp_path: Path) -> None:
    conception = tmp_path / "conception"
    conception.mkdir()
    toml = tmp_path / "config.toml"
    _write_toml(toml, conception, tmp_path / "workspace")

    cfg = cfg_mod.load(toml)
    cfg_mod.save(cfg, toml)

    reloaded = cfg_mod.load(toml)
    assert reloaded.yaml_source == conception / "config" / "repositories.yml"
    assert reloaded.preferences_source == conception / "config" / "preferences.yml"
    assert reloaded.repositories_primary == ["alpha", "mono"]
    assert reloaded.repo_submodules == {"mono": ["apps/web", "apps/api"]}
    assert reloaded.open_with["main_ide"].label == "Open in main IDE"
    assert reloaded.pdf_viewer == ["evince {path}"]
    assert reloaded.terminal.shortcut == "Ctrl+T"


def test_slashed_repo_names_for_depth_2_layouts(tmp_path: Path) -> None:
    """Repo entries accept ``"<org>/<repo>"`` for depth-2 workspace layouts."""
    conception = tmp_path / "conception"
    (conception / "config").mkdir(parents=True)
    yml = conception / "config" / "repositories.yml"
    yml.write_text(
        """workspace_path: /tmp/work
worktrees_path: /tmp/wt
repositories:
  primary:
    - condash
    - name: myorg/backend
      submodules: [apps/web, apps/api]
  secondary: []
open_with:
  main_ide:
    label: Open in main IDE
    commands:
      - 'idea {path}'
  secondary_ide:
    label: Open in secondary IDE
    commands:
      - 'code {path}'
  terminal:
    label: Open terminal here
    commands:
      - xterm
""",
        encoding="utf-8",
    )
    toml = tmp_path / "config.toml"
    toml.write_text(
        f'conception_path = "{conception}"\nport = 0\nnative = true\n', encoding="utf-8"
    )

    cfg = cfg_mod.load(toml)
    assert cfg.repositories_primary == ["condash", "myorg/backend"]
    assert cfg.repo_submodules == {"myorg/backend": ["apps/web", "apps/api"]}

    cfg_mod.save(cfg, toml)
    body = yml.read_text(encoding="utf-8")
    assert "myorg/backend" in body
    assert "apps/web" in body


def test_yaml_overlay_beats_stale_toml_keys(tmp_path: Path) -> None:
    """Both files populated → YAML wins for its scope."""
    conception = tmp_path / "conception"
    conception.mkdir()
    toml = tmp_path / "config.toml"
    _write_toml(toml, conception, tmp_path / "workspace")

    (conception / "config").mkdir()
    (conception / "config" / "repositories.yml").write_text(
        """workspace_path: /tmp/from-yaml
worktrees_path: /tmp/from-yaml-wt
repositories:
  primary:
    - from-yaml
  secondary: []
open_with:
  main_ide:
    label: YAML IDE
    commands:
      - 'yaml-ide {path}'
  secondary_ide:
    label: YAML VS
    commands:
      - 'yaml-code {path}'
  terminal:
    label: YAML term
    commands:
      - yaml-term
""",
        encoding="utf-8",
    )
    (conception / "config" / "preferences.yml").write_text(
        """pdf_viewer:
  - 'yaml-pdf {path}'
terminal:
  shortcut: Ctrl+Shift+T
  screenshot_paste_shortcut: Ctrl+V
  launcher_command: claude
  move_tab_left_shortcut: Ctrl+Left
  move_tab_right_shortcut: Ctrl+Right
""",
        encoding="utf-8",
    )

    cfg = cfg_mod.load(toml)

    assert cfg.workspace_path == Path("/tmp/from-yaml")
    assert cfg.repositories_primary == ["from-yaml"]
    assert cfg.open_with["main_ide"].label == "YAML IDE"
    assert cfg.pdf_viewer == ["yaml-pdf {path}"]
    assert cfg.terminal.shortcut == "Ctrl+Shift+T"


def test_degraded_mode_without_conception_path(tmp_path: Path) -> None:
    """No conception_path → both yamls unreachable; TOML carries everything."""
    toml = tmp_path / "config.toml"
    toml.write_text(
        """port = 0
native = true
pdf_viewer = ["evince {path}"]

[repositories]
primary = ["alpha"]
secondary = []

[open_with.main_ide]
label = "Open"
commands = ["idea {path}"]

[open_with.secondary_ide]
label = "Secondary"
commands = ["code {path}"]

[open_with.terminal]
label = "Term"
commands = ["xterm"]

[terminal]
shortcut = "Ctrl+T"
launcher_command = "claude"
""",
        encoding="utf-8",
    )

    cfg = cfg_mod.load(toml)
    assert cfg.conception_path is None
    assert cfg.repositories_primary == ["alpha"]
    assert cfg.pdf_viewer == ["evince {path}"]

    cfg_mod.save(cfg, toml)
    body = toml.read_text(encoding="utf-8")
    assert "[repositories]" in body
    assert "[open_with.main_ide]" in body
    assert "[terminal]" in body
    assert "pdf_viewer" in body


def test_run_field_parses_on_repo_and_submodule(tmp_path: Path) -> None:
    """``run:`` on top-level and sub-repo entries populates ``cfg.repo_run``."""
    conception = tmp_path / "conception"
    (conception / "config").mkdir(parents=True)
    (conception / "config" / "repositories.yml").write_text(
        """workspace_path: /tmp/work
worktrees_path: /tmp/wt
repositories:
  primary:
    - name: notes.vcoeur.com
      run: make dev
    - name: alicepeintures.com
      run: make dev
      submodules:
        - name: PaintingManager
          run: uv run python -m painting_manager
        - docs
    - plain-repo
  secondary: []
open_with:
  main_ide:
    label: M
    commands: ['idea {path}']
  secondary_ide:
    label: S
    commands: ['code {path}']
  terminal:
    label: T
    commands: [xterm]
""",
        encoding="utf-8",
    )
    toml = tmp_path / "config.toml"
    toml.write_text(
        f'conception_path = "{conception}"\nport = 0\nnative = true\n', encoding="utf-8"
    )

    cfg = cfg_mod.load(toml)
    assert cfg.repositories_primary == ["notes.vcoeur.com", "alicepeintures.com", "plain-repo"]
    assert cfg.repo_submodules == {"alicepeintures.com": ["PaintingManager", "docs"]}
    assert set(cfg.repo_run.keys()) == {
        "notes.vcoeur.com",
        "alicepeintures.com",
        "alicepeintures.com--PaintingManager",
    }
    assert cfg.repo_run["notes.vcoeur.com"].template == "make dev"
    assert (
        cfg.repo_run["alicepeintures.com--PaintingManager"].template
        == "uv run python -m painting_manager"
    )
    # {path} substitution is identity without a {path} token.
    assert cfg.repo_run["notes.vcoeur.com"].resolve("/tmp/work/notes.vcoeur.com") == "make dev"


def test_run_field_round_trips_through_save(tmp_path: Path) -> None:
    """A save → reload cycle keeps ``run:`` on both repo and sub-repo entries."""
    conception = tmp_path / "conception"
    (conception / "config").mkdir(parents=True)
    (conception / "config" / "repositories.yml").write_text(
        """workspace_path: /tmp/work
worktrees_path: /tmp/wt
repositories:
  primary:
    - name: app
      run: make dev
      submodules:
        - name: worker
          run: python -m worker
        - static
  secondary: []
open_with:
  main_ide: {label: M, commands: ['idea {path}']}
  secondary_ide: {label: S, commands: ['code {path}']}
  terminal: {label: T, commands: [xterm]}
""",
        encoding="utf-8",
    )
    toml = tmp_path / "config.toml"
    toml.write_text(
        f'conception_path = "{conception}"\nport = 0\nnative = true\n', encoding="utf-8"
    )

    cfg = cfg_mod.load(toml)
    cfg_mod.save(cfg, toml)

    body = (conception / "config" / "repositories.yml").read_text(encoding="utf-8")
    assert "run: make dev" in body
    assert "run: python -m worker" in body

    reloaded = cfg_mod.load(toml)
    assert reloaded.repo_run["app"].template == "make dev"
    assert reloaded.repo_run["app--worker"].template == "python -m worker"
    assert reloaded.repo_submodules["app"] == ["worker", "static"]


def test_run_field_rejects_empty_string(tmp_path: Path) -> None:
    """Explicit empty ``run:`` is a schema error so typos surface loudly."""
    conception = tmp_path / "conception"
    (conception / "config").mkdir(parents=True)
    (conception / "config" / "repositories.yml").write_text(
        """workspace_path: /tmp/work
worktrees_path: /tmp/wt
repositories:
  primary:
    - name: app
      run: '   '
  secondary: []
open_with:
  main_ide: {label: M, commands: ['idea {path}']}
  secondary_ide: {label: S, commands: ['code {path}']}
  terminal: {label: T, commands: [xterm]}
""",
        encoding="utf-8",
    )
    toml = tmp_path / "config.toml"
    toml.write_text(
        f'conception_path = "{conception}"\nport = 0\nnative = true\n', encoding="utf-8"
    )

    with pytest.raises(cfg_mod.ConfigIncompleteError):
        cfg_mod.load(toml)


def test_malformed_repositories_yaml_raises(tmp_path: Path) -> None:
    conception = tmp_path / "conception"
    (conception / "config").mkdir(parents=True)
    (conception / "config" / "repositories.yml").write_text(
        "workspace_path: [unclosed\n", encoding="utf-8"
    )
    toml = tmp_path / "config.toml"
    toml.write_text(f'conception_path = "{conception}"\nport = 0\n', encoding="utf-8")

    with pytest.raises(cfg_mod.ConfigIncompleteError):
        cfg_mod.load(toml)


def test_malformed_preferences_yaml_raises(tmp_path: Path) -> None:
    conception = tmp_path / "conception"
    (conception / "config").mkdir(parents=True)
    (conception / "config" / "preferences.yml").write_text(
        "pdf_viewer: [unclosed\n", encoding="utf-8"
    )
    toml = tmp_path / "config.toml"
    toml.write_text(f'conception_path = "{conception}"\nport = 0\n', encoding="utf-8")

    with pytest.raises(cfg_mod.ConfigIncompleteError):
        cfg_mod.load(toml)
