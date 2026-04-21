"""Runtime state container for the condash process.

Holds the live :class:`CondashConfig`, its derived :class:`RenderCtx`, the
filesystem event bus + observer, and the per-process PTY session registry
that was previously spread across ``app.py`` as module-level globals.
Bundling them into one dataclass makes the lifecycle explicit:

- initialized once in :func:`condash.app.run` (or by tests via
  :func:`condash.app.state.reset_for_test`),
- mutated by config reloads (POST ``/config``, ``/config/yaml``, and the
  filesystem-watcher reload callback),
- torn down on shutdown (watchdog observer stopped, PTY sessions reaped).

The ``_CONFIG_SELF_WRITE`` TTL map suppresses the watchdog's echo of this
process's own config saves — see :meth:`stamp_config_self_write` /
:meth:`is_config_self_write`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .cache import WorkspaceCache
    from .config import CondashConfig
    from .context import RenderCtx
    from .events import EventBus
    from .pty import PtySession


_CONFIG_SELF_WRITE_TTL = 2.0


@dataclass
class AppState:
    """Mutable runtime state shared across routes and lifecycle hooks."""

    cfg: CondashConfig | None = None
    ctx: RenderCtx | None = None
    event_bus: EventBus | None = None
    event_observer: object = None
    cache: WorkspaceCache | None = None
    pty_sessions: dict[str, PtySession] = field(default_factory=dict)
    # leaf → expiry timestamp. A stamped leaf suppresses the next
    # watchdog-driven reload so POST /config doesn't echo its own save back.
    config_self_write: dict[str, float] = field(default_factory=dict)

    def get_ctx(self) -> RenderCtx:
        """Return the live :class:`RenderCtx` or raise if uninitialised."""
        if self.ctx is None:
            raise RuntimeError("condash.state: ctx not initialised")
        return self.ctx

    def stamp_config_self_write(self, *leaves: str, ttl: float = _CONFIG_SELF_WRITE_TTL) -> None:
        """Mark ``leaves`` (config YAML filenames) as this-process writes.

        The watchdog callback consults :meth:`is_config_self_write` before
        reloading — the stamp survives for ``ttl`` seconds, enough to
        outlast the handler's 0.75 s debounce that can collapse two rapid
        saves into one event.
        """
        expiry = time.time() + ttl
        for leaf in leaves:
            self.config_self_write[leaf] = expiry

    def is_config_self_write(self, leaf: str, *, now: float | None = None) -> bool:
        """True if ``leaf`` was written by this process within the TTL window.

        Expired stamps are reaped on the way out so the dict doesn't leak.
        """
        current = time.time() if now is None else now
        expiry = self.config_self_write.get(leaf)
        is_self = expiry is not None and current < expiry
        # Reap stale stamps.
        for stale in [k for k, v in self.config_self_write.items() if v <= current]:
            self.config_self_write.pop(stale, None)
        return is_self
