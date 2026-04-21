"""NiceGUI bootstrap for condash.

Holds the runtime :class:`AppState` (config, ctx, event bus + observer,
PTY registry), wires the route subpackage onto NiceGUI's embedded
FastAPI app via :func:`_register_routes`, and launches the native (or
browser) window via :func:`run`.

Each HTTP / WebSocket route lives under :mod:`condash.routes.*`; this
module deliberately stays small enough to read top-to-bottom.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
from importlib.resources import files as _package_files

from nicegui import app as _ng_app
from nicegui import ui

from . import config as config_mod
from . import events as events_mod
from . import pty as pty_mod
from . import routes as routes_pkg
from . import runners as runners_mod
from .cache import WorkspaceCache
from .clipboard import ClipboardBridge
from .config import CondashConfig
from .context import RenderCtx, build_ctx
from .state import AppState

log = logging.getLogger(__name__)

# Runtime state container. Created at import time; :func:`run` (or test
# bootstrap) populates ``cfg`` / ``ctx`` before :func:`_register_routes`
# is called. Module-level so routes (defined inside the routes package)
# can close over it, and tests can poke ``state.cfg`` / ``state.ctx``
# directly.
state = AppState(event_bus=events_mod.EventBus(), cache=WorkspaceCache())


def _ctx() -> RenderCtx:
    """Return the live RenderCtx or raise if uninitialised."""
    return state.get_ctx()


def _stop_event_observer() -> None:
    """NiceGUI shutdown hook: halt the watchdog observer cleanly."""
    obs = state.event_observer
    state.event_observer = None
    if obs is None:
        return
    try:
        obs.stop()
        obs.join(timeout=2.0)
    except Exception:
        log.exception("failed to stop watchdog observer")


def _reload_runtime_config_from_disk(leaf: str) -> None:
    """Reload the live :class:`CondashConfig` after an external YAML edit.

    Runs on the asyncio event loop (scheduled by the watchdog worker via
    ``loop.call_soon_threadsafe``). Drops the event when the write was
    initiated by this process itself — POST ``/config`` stamps the leaf
    via :meth:`AppState.stamp_config_self_write` right before saving so
    the watcher's echo is suppressed exactly once.

    Rebuilds ``state.cfg`` + ``state.ctx`` atomically (pointer swap) so
    concurrent readers see either the previous config or the new one,
    never a half-initialised state. Errors are logged and dropped — a
    malformed hand edit leaves the running config intact.
    """
    if state.is_config_self_write(leaf):
        return
    current_cfg = state.cfg
    if current_cfg is None:
        return
    try:
        new_cfg = config_mod.load(
            port_override=current_cfg.port,
            native_override=current_cfg.native,
        )
    except (config_mod.ConfigNotFoundError, config_mod.ConfigIncompleteError) as exc:
        log.warning("live config reload failed (%s): %s", leaf, exc)
        return
    new_ctx = build_ctx(new_cfg)
    state.cfg = new_cfg
    state.ctx = new_ctx
    if state.cache is not None:
        state.cache.invalidate_all()
    log.info("live config reload: %s applied", leaf)


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
    falls back to the executable name pywebview happens to pass to
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


def _reap_all_pty_sessions() -> None:
    """SIGTERM every live pty. Called on server shutdown."""
    pty_mod.reap_all(state)


def _reap_and_exit() -> None:
    """Native-close handler: SIGTERM every child before ``os._exit``.

    ``os._exit`` skips FastAPI's ``on_shutdown`` hooks, so without this
    every runner (``make dev`` + friends) and every terminal-tab shell
    would be reparented to init and keep its ports bound across the next
    launch. Best-effort: swallow everything so a stuck reap can't block
    the exit — the whole point is to leave cleanly.
    """
    for reap in (_reap_all_pty_sessions, runners_mod.reap_all):
        try:
            reap()
        except Exception as exc:  # noqa: BLE001
            log.debug("reap on close: %s failed: %s", reap.__name__, exc)
    os._exit(0)


def _register_routes() -> None:
    """Attach all HTTP + WebSocket routes to NiceGUI's FastAPI instance."""
    _ng_app.on_shutdown(_reap_all_pty_sessions)
    _ng_app.on_shutdown(runners_mod.reap_all)
    routes_pkg.register_all(_ng_app, state)


# NiceGUI's own find_open_port scans 8000-8999, which regularly collides
# with Django/uvicorn/http.server defaults. Scan a less-contested window
# instead. 11111-12111 is in the IANA registered range but near-empty in
# practice; memcached (11211) and OpenPGP HKP (11371) are skipped
# naturally by the bind-and-try.
_FREE_PORT_RANGE = (11111, 12111)


def _pick_free_port() -> int:
    """Return a free TCP port in ``_FREE_PORT_RANGE`` (inclusive)."""
    start, end = _FREE_PORT_RANGE
    for port in range(start, end + 1):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind(("localhost", port))
                return port
        except OSError:
            continue
    raise OSError(f"No open port found in {start}-{end}")


def run(cfg: CondashConfig) -> None:
    """Launch the condash dashboard (native window or browser, per config)."""
    state.cfg = cfg
    state.ctx = build_ctx(cfg)
    if state.cache is None:
        state.cache = WorkspaceCache()
    else:
        state.cache.invalidate_all()
    # Wire the cache as a sync subscriber on the event bus before the
    # watcher starts — this way cache slices flip to stale in the same
    # asyncio tick as the SSE fanout, so the client's follow-up
    # ``/check-updates`` call reads from the refreshed cache rather than
    # a racing stale snapshot.
    state.event_bus.subscribe_sync(state.cache.on_event)
    _register_routes()
    # Filesystem → SSE bridge. The observer runs on its own worker
    # thread and publishes to the bus on state; /events streams from
    # there. Stopped on NiceGUI shutdown.
    state.event_observer = events_mod.start_watcher(
        state.ctx, state.event_bus, on_config_reload=_reload_runtime_config_from_disk
    )
    if state.event_observer is not None:
        _ng_app.on_shutdown(_stop_event_observer)
        # Bind the asyncio loop to the event bus as soon as it's spinning so
        # the first filesystem event doesn't lose its reload callback just
        # because no SSE client has connected yet.
        _ng_app.on_startup(lambda: state.event_bus.bind_loop(asyncio.get_running_loop()))
    port = _pick_free_port() if cfg.port == 0 else cfg.port
    kwargs: dict = {
        "native": cfg.native,
        "title": "Conception Dashboard",
        "reload": False,
        "show": not cfg.native,
        "port": port,
    }
    if cfg.native:
        kwargs["window_size"] = (1400, 900)
        # Force the Qt backend so we don't print a noisy GTK traceback on
        # systems missing python3-gi. PyQt6 is a hard runtime dependency
        # (pywebview[qt] in pyproject), so this is always available.
        _ng_app.native.start_args["gui"] = "qt"
        # Expose a Python→JS clipboard bridge. pywebview invokes js_api
        # methods on its main Qt thread, so QClipboard works without
        # tripping navigator.clipboard's permission callback (which
        # crashes on PyQt6 6.x — see qt.py::onFeaturePermissionRequested).
        _ng_app.native.window_args["js_api"] = ClipboardBridge()
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
        # native window emits its `closed` event. `os._exit` bypasses
        # FastAPI's shutdown hooks, so we have to SIGTERM every pty + inline
        # runner child ourselves — otherwise `make dev` servers survive as
        # orphans and keep ports bound across relaunches.
        _ng_app.native.on("closed", _reap_and_exit)
    ui.run(**kwargs)
