"""NiceGUI-backed native window for condash.

The existing ``dashboard.html`` is served verbatim at ``/``; all the AJAX
endpoints the JS calls (``/toggle``, ``/add-step``, ``/tidy``, …) are
re-implemented here as FastAPI routes on top of NiceGUI's underlying
FastAPI instance.
"""

from __future__ import annotations

import os
from importlib.resources import files as _package_files
from pathlib import Path

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from nicegui import app as _ng_app
from nicegui import ui

from . import config as config_mod
from . import legacy
from .config import (
    OPEN_WITH_SLOT_KEYS,
    CondashConfig,
    OpenWithSlot,
)

# Holds the live runtime config so the in-app editor can mutate it after a
# successful POST /config without forcing a process restart. Initialized by
# `run` before NiceGUI starts.
_RUNTIME_CFG: CondashConfig | None = None


def icon_path() -> str:
    """Absolute path to the bundled app icon (SVG)."""
    return str(_package_files("condash") / "assets" / "favicon.svg")


def _set_qt_desktop_identity() -> None:
    """Advertise this process to Qt as "condash" so Wayland compositors can
    match the running window to ``condash.desktop``.

    On Wayland (default on modern GNOME/KDE), windows are matched to their
    ``.desktop`` file via the ``xdg_toplevel::set_app_id`` protocol. Qt's
    Wayland backend derives that app_id from
    ``QGuiApplication::desktopFileName()``. If it is not set, the app_id
    falls back to the executable name that pywebview happens to pass to
    ``QApplication(sys.argv)`` — which is not ``condash`` after pipx
    wrapping — so GNOME Shell cannot resolve the ``.desktop`` entry and
    the task switcher shows a generic icon.

    Setting this before ``ui.run()`` (which ends up creating the
    QApplication inside pywebview's Qt backend) makes the match succeed.
    """
    try:
        from qtpy.QtGui import QGuiApplication
    except ImportError:
        return
    QGuiApplication.setApplicationName("condash")
    QGuiApplication.setApplicationDisplayName("Condash")
    QGuiApplication.setDesktopFileName("condash")


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": message})


def _register_routes() -> None:
    """Attach all API routes to NiceGUI's FastAPI instance."""

    @_ng_app.get("/", response_class=HTMLResponse)
    def index():
        items = legacy.collect_items()
        return HTMLResponse(content=legacy.render_page(items))

    @_ng_app.get("/favicon.svg")
    def favicon_svg():
        data = legacy._favicon_bytes()
        if data is None:
            return Response(status_code=404)
        return Response(
            content=data,
            media_type="image/svg+xml",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    @_ng_app.get("/favicon.ico")
    def favicon_ico():
        data = legacy._favicon_bytes()
        if data is None:
            return Response(status_code=404)
        return Response(content=data, media_type="image/svg+xml")

    @_ng_app.get("/check-updates")
    def check_updates():
        items = legacy.collect_items()
        return {
            "fingerprint": legacy._compute_fingerprint(items),
            "tidy_needed": legacy._tidy_needed(items),
            "git_fingerprint": legacy._git_fingerprint(),
        }

    @_ng_app.get("/note")
    def get_note(path: str = ""):
        full = legacy.validate_note_path(path)
        if full is None:
            return Response(status_code=403)
        return HTMLResponse(content=legacy._render_note(full))

    @_ng_app.get("/download/{rel_path:path}")
    def download(rel_path: str):
        full = legacy.validate_download_path(rel_path)
        if full is None:
            return Response(status_code=403)
        return Response(
            content=full.read_bytes(),
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{full.name}"'},
        )

    @_ng_app.get("/asset/{rel_path:path}")
    def asset(rel_path: str):
        result = legacy.validate_asset_path(rel_path)
        if result is None:
            return Response(status_code=403)
        full, ctype = result
        return Response(
            content=full.read_bytes(),
            media_type=ctype,
            headers={"Cache-Control": "public, max-age=300"},
        )

    @_ng_app.post("/toggle")
    async def toggle(req: Request):
        data = await req.json()
        full = legacy._validate_path(data.get("file", ""))
        if not full:
            return _error(400, "invalid path")
        status = legacy._toggle_checkbox(full, data.get("line", -1))
        if status is None:
            return _error(400, "not a checkbox line")
        return {"ok": True, "status": status}

    @_ng_app.post("/remove-step")
    async def remove_step(req: Request):
        data = await req.json()
        full = legacy._validate_path(data.get("file", ""))
        if not full:
            return _error(400, "invalid path")
        if legacy._remove_step(full, data.get("line", -1)):
            return {"ok": True}
        return _error(400, "cannot remove")

    @_ng_app.post("/edit-step")
    async def edit_step(req: Request):
        data = await req.json()
        text = (data.get("text") or "").strip()
        if not text:
            return _error(400, "empty text")
        full = legacy._validate_path(data.get("file", ""))
        if not full:
            return _error(400, "invalid path")
        if legacy._edit_step(full, data.get("line", -1), text):
            return {"ok": True}
        return _error(400, "cannot edit")

    @_ng_app.post("/add-step")
    async def add_step(req: Request):
        data = await req.json()
        text = (data.get("text") or "").strip()
        if not text:
            return _error(400, "empty text")
        full = legacy._validate_path(data.get("file", ""))
        if not full:
            return _error(400, "invalid path")
        line = legacy._add_step(full, text, data.get("section"))
        return {"ok": True, "line": line}

    @_ng_app.post("/set-priority")
    async def set_priority(req: Request):
        data = await req.json()
        full = legacy._validate_path(data.get("file", ""))
        if not full:
            return _error(400, "invalid path")
        priority = data.get("priority", "")
        if legacy._set_priority(full, priority):
            moves = legacy._tidy()
            return {"ok": True, "priority": priority, "moved": bool(moves)}
        return _error(400, "invalid priority")

    @_ng_app.post("/reorder-all")
    async def reorder_all(req: Request):
        data = await req.json()
        full = legacy._validate_path(data.get("file", ""))
        if not full:
            return _error(400, "invalid path")
        order = data.get("order") or []
        if legacy._reorder_all(full, order):
            return {"ok": True}
        return _error(400, "cannot reorder")

    @_ng_app.post("/open")
    async def open_path(req: Request):
        data = await req.json()
        resolved = legacy._validate_open_path(data.get("path", ""))
        if not resolved:
            return _error(400, "invalid path")
        tool = data.get("tool", "")
        if legacy._open_path(tool, resolved):
            return {"ok": True}
        return _error(500, f"could not launch {tool}")

    @_ng_app.post("/tidy")
    async def tidy(_req: Request):
        moves = legacy._tidy()
        return {
            "ok": True,
            "moves": [{"from": f, "to": t} for f, t in moves],
        }

    @_ng_app.get("/config")
    def get_config():
        cfg = _RUNTIME_CFG
        if cfg is None:
            return _error(500, "config not initialised")
        return _config_to_payload(cfg)

    @_ng_app.post("/config")
    async def post_config(req: Request):
        global _RUNTIME_CFG
        if _RUNTIME_CFG is None:
            return _error(500, "config not initialised")
        data = await req.json()
        try:
            new_cfg = _payload_to_config(data)
        except (ValueError, KeyError, TypeError) as exc:
            return _error(400, f"invalid config: {exc}")
        # The config form only exposes repo names (one per line). Carry
        # over any submodule declarations from the live config so saving
        # from the form doesn't wipe structured entries authored via
        # `condash config edit`.
        new_cfg.repo_submodules = dict(_RUNTIME_CFG.repo_submodules)
        config_mod.save(new_cfg)
        # Re-init module-level state so paths / repos / open-with changes
        # take effect on the next request without needing a process restart.
        legacy.init(new_cfg)
        # Surface which fields require a restart to actually take effect.
        restart_required = []
        old = _RUNTIME_CFG
        if old.port != new_cfg.port:
            restart_required.append("port")
        if old.native != new_cfg.native:
            restart_required.append("native")
        _RUNTIME_CFG = new_cfg
        return {
            "ok": True,
            "restart_required": restart_required,
            "config": _config_to_payload(new_cfg),
        }


def _config_to_payload(cfg: CondashConfig) -> dict:
    """Serialise the live config to JSON for ``GET /config``."""
    return {
        "conception_path": str(cfg.conception_path),
        "workspace_path": str(cfg.workspace_path) if cfg.workspace_path else "",
        "worktrees_path": str(cfg.worktrees_path) if cfg.worktrees_path else "",
        "port": int(cfg.port),
        "native": bool(cfg.native),
        "repositories_primary": list(cfg.repositories_primary),
        "repositories_secondary": list(cfg.repositories_secondary),
        "open_with": {
            slot_key: {
                "label": cfg.open_with[slot_key].label,
                "commands": list(cfg.open_with[slot_key].commands),
            }
            for slot_key in OPEN_WITH_SLOT_KEYS
            if slot_key in cfg.open_with
        },
    }


def _payload_to_config(data: dict) -> CondashConfig:
    """Build a validated CondashConfig from the in-app editor's JSON payload."""
    if not isinstance(data, dict):
        raise ValueError("payload must be an object")
    conception_raw = (data.get("conception_path") or "").strip()
    if not conception_raw:
        raise ValueError("conception_path is required")
    conception = Path(conception_raw).expanduser()

    workspace_raw = (data.get("workspace_path") or "").strip()
    workspace = Path(workspace_raw).expanduser() if workspace_raw else None
    worktrees_raw = (data.get("worktrees_path") or "").strip()
    worktrees = Path(worktrees_raw).expanduser() if worktrees_raw else None

    port_raw = data.get("port", 0)
    if isinstance(port_raw, str):
        port_raw = int(port_raw or 0)
    if not isinstance(port_raw, int) or not 0 <= port_raw <= 65535:
        raise ValueError("port must be an integer between 0 and 65535")

    native_raw = data.get("native", True)
    if not isinstance(native_raw, bool):
        raise ValueError("native must be a boolean")

    primary = [str(s).strip() for s in (data.get("repositories_primary") or []) if str(s).strip()]
    secondary = [
        str(s).strip() for s in (data.get("repositories_secondary") or []) if str(s).strip()
    ]

    open_with_raw = data.get("open_with") or {}
    if not isinstance(open_with_raw, dict):
        raise ValueError("open_with must be an object")
    open_with: dict[str, OpenWithSlot] = {}
    for slot_key in OPEN_WITH_SLOT_KEYS:
        defaults = config_mod.DEFAULT_OPEN_WITH[slot_key]
        slot_data = open_with_raw.get(slot_key) or {}
        if not isinstance(slot_data, dict):
            raise ValueError(f"open_with.{slot_key} must be an object")
        label = str(slot_data.get("label") or defaults["label"])
        commands_raw = slot_data.get("commands")
        if commands_raw is None:
            commands = list(defaults["commands"])
        elif isinstance(commands_raw, list):
            commands = [str(c) for c in commands_raw if str(c).strip()]
        else:
            raise ValueError(f"open_with.{slot_key}.commands must be a list")
        open_with[slot_key] = OpenWithSlot(label=label, commands=commands)

    return CondashConfig(
        conception_path=conception,
        workspace_path=workspace,
        worktrees_path=worktrees,
        repositories_primary=primary,
        repositories_secondary=secondary,
        port=port_raw,
        native=native_raw,
        open_with=open_with,
    )


def run(cfg: CondashConfig) -> None:
    """Launch the condash dashboard (native window or browser, per config)."""
    global _RUNTIME_CFG
    _RUNTIME_CFG = cfg
    legacy.init(cfg)
    _register_routes()
    kwargs: dict = {
        "native": cfg.native,
        "title": "condash",
        "reload": False,
        "show": not cfg.native,
        "port": cfg.port,
    }
    if cfg.native:
        kwargs["window_size"] = (1400, 900)
        # Force the Qt backend so we don't print a noisy GTK traceback on
        # systems missing python3-gi. PyQt6 is a hard runtime dependency
        # (pywebview[qt] in pyproject), so this is always available.
        _ng_app.native.start_args["gui"] = "qt"
        # Set the window icon so the OS task switcher shows it. pywebview 6.x
        # exposes `icon` on webview.start() (i.e. start_args), NOT on
        # create_window() — passing it via window_args raises TypeError on
        # launch.
        _ng_app.native.start_args["icon"] = icon_path()
        # Advertise the Qt desktop identity before pywebview creates the
        # QApplication, so the Wayland app_id matches condash.desktop and
        # GNOME/KDE task switchers can resolve the bundled icon.
        _set_qt_desktop_identity()
        # NiceGUI's check_shutdown thread sometimes fails to actually stop
        # uvicorn after the user closes the window — leaving the port bound
        # for the next launch. Force-exit the whole process when the
        # native window emits its `closed` event.
        _ng_app.native.on("closed", lambda: os._exit(0))
    ui.run(**kwargs)
