"""Explicit runtime context — replaces :mod:`condash.core` module globals.

The Phase 1 split still stored ``BASE_DIR`` / ``_WORKSPACE`` / ``_OPEN_WITH``
/ ``_PDF_VIEWER`` / ``_REPO_STRUCTURE`` as module-level state populated by
``core.init(cfg)``. Phase 2 bundles them into a single frozen dataclass and
threads it through every helper that needs them. Module globals disappear.

Every public entry point (``render_page``, ``collect_items``, ``run_tidy``,
the path validators, the openers) now takes ``ctx`` as its first positional
argument. Pure helpers (parsers, serialisers, regex gates, rendering of
things that don't need config) do not take ``ctx``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib.resources import files as _package_files
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RenderCtx:
    """Immutable runtime context carried by every helper that needs config.

    Built once per effective config via :func:`build_ctx`. Rebuilt (and
    swapped into ``app._RUNTIME_CTX``) whenever the in-app config editor
    posts a new config to ``/config``.
    """

    base_dir: Path
    workspace: Path | None
    worktrees: Path | None
    repo_structure: list[tuple[str, list[tuple[str, list[str]]]]]
    open_with: dict[str, Any] = field(default_factory=dict)
    pdf_viewer: list[str] = field(default_factory=list)
    template: str = ""


def build_ctx(cfg) -> RenderCtx:
    """Build a fresh :class:`RenderCtx` from a :class:`CondashConfig`."""
    if cfg.conception_path is None:
        # Sentinel that .is_dir() returns False for — collect_items short
        # circuits and the dashboard renders the setup prompt.
        base_dir = Path("/nonexistent")
    else:
        base_dir = Path(cfg.conception_path).expanduser().resolve()
    workspace = (
        Path(cfg.workspace_path).expanduser().resolve() if cfg.workspace_path is not None else None
    )
    worktrees = (
        Path(cfg.worktrees_path).expanduser().resolve() if cfg.worktrees_path is not None else None
    )
    submodules = getattr(cfg, "repo_submodules", None) or {}
    repo_structure = [
        (
            "Primary",
            [(name, list(submodules.get(name) or [])) for name in cfg.repositories_primary],
        ),
        (
            "Secondary",
            [(name, list(submodules.get(name) or [])) for name in cfg.repositories_secondary],
        ),
    ]
    return RenderCtx(
        base_dir=base_dir,
        workspace=workspace,
        worktrees=worktrees,
        repo_structure=repo_structure,
        open_with=dict(cfg.open_with or {}),
        pdf_viewer=list(getattr(cfg, "pdf_viewer", None) or []),
        template=_load_template(),
    )


def _load_template() -> str:
    """Read the dashboard HTML template shipped with the wheel."""
    return (_package_files("condash") / "assets" / "dashboard.html").read_text(encoding="utf-8")


def favicon_bytes() -> bytes | None:
    """Return the bundled favicon bytes, or ``None`` if missing."""
    try:
        return (_package_files("condash") / "assets" / "favicon.svg").read_bytes()
    except FileNotFoundError:
        return None
