"""Smoke tests for the inline dev-server runner registry.

Covers spawn + output capture, the single-session-per-key lock, stop →
exit_code capture, and the shutdown reaper. Runs on Linux/macOS only
since ``pty.fork`` has no Windows equivalent.
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

from condash import runners as runners_mod


pytestmark = pytest.mark.skipif(
    sys.platform not in ("linux", "darwin"), reason="runners use pty.fork"
)


@pytest.fixture(autouse=True)
def _clear_registry():
    """Make sure tests don't leak live sessions into each other."""
    yield
    for key in list(runners_mod.registry().keys()):
        session = runners_mod.get(key)
        if session is None:
            continue
        if session.exit_code is None:
            try:
                os.kill(session.pid, 9)
            except OSError:
                pass
        try:
            os.close(session.fd)
        except OSError:
            pass
        runners_mod.registry().pop(key, None)


def _drain_until_exit(session, timeout: float = 3.0) -> None:
    """Pump the asyncio loop until the session records an exit code."""

    async def _wait():
        deadline = asyncio.get_event_loop().time() + timeout
        while session.exit_code is None:
            if asyncio.get_event_loop().time() > deadline:
                raise AssertionError("runner did not exit in time")
            await asyncio.sleep(0.05)

    asyncio.run(_wait())


def test_start_captures_output_and_exit(tmp_path) -> None:
    """A short-lived ``echo`` run populates the ring buffer and records exit 0."""

    async def _body():
        session = await runners_mod.start(
            key="echo-repo",
            checkout_key="main",
            path=str(tmp_path),
            template="echo hello-runner",
            shell="/bin/sh",
        )
        # Drain the pump within the same loop.
        deadline = asyncio.get_event_loop().time() + 3.0
        while session.exit_code is None:
            if asyncio.get_event_loop().time() > deadline:
                raise AssertionError("runner did not exit in time")
            await asyncio.sleep(0.05)
        assert session.exit_code == 0
        assert b"hello-runner" in bytes(session.buffer)
        assert runners_mod.get("echo-repo") is session  # registry holds exited sessions

    asyncio.run(_body())


def test_start_rejects_concurrent_key(tmp_path) -> None:
    """A second ``start`` on the same live key raises ``RuntimeError``."""

    async def _body():
        first = await runners_mod.start(
            key="busy",
            checkout_key="main",
            path=str(tmp_path),
            template="sleep 1",
            shell="/bin/sh",
        )
        try:
            with pytest.raises(RuntimeError):
                await runners_mod.start(
                    key="busy",
                    checkout_key="wt-a",
                    path=str(tmp_path),
                    template="sleep 1",
                    shell="/bin/sh",
                )
        finally:
            await runners_mod.stop("busy", grace=0.2)
            runners_mod.clear_exited("busy")
        assert first.exit_code is not None

    asyncio.run(_body())


def test_stop_terminates_live_child(tmp_path) -> None:
    """``stop`` SIGTERMs a live child and records its exit code."""

    async def _body():
        session = await runners_mod.start(
            key="sleeper",
            checkout_key="main",
            path=str(tmp_path),
            template="sleep 30",
            shell="/bin/sh",
        )
        assert session.exit_code is None
        await runners_mod.stop("sleeper", grace=1.0)
        # After stop, exit_code is recorded (either SIGTERM → negative
        # signal code, or 0 if the shell ate it).
        assert session.exit_code is not None
        runners_mod.clear_exited("sleeper")
        assert runners_mod.get("sleeper") is None

    asyncio.run(_body())


def test_fingerprint_changes_on_lifecycle(tmp_path) -> None:
    """``fingerprint_token`` reflects off → running → exited transitions."""

    async def _body():
        assert runners_mod.fingerprint_token("fp-key") == "off"
        session = await runners_mod.start(
            key="fp-key",
            checkout_key="main",
            path=str(tmp_path),
            template="echo done",
            shell="/bin/sh",
        )
        running_token = runners_mod.fingerprint_token("fp-key")
        assert running_token.startswith("run:")
        deadline = asyncio.get_event_loop().time() + 3.0
        while session.exit_code is None:
            if asyncio.get_event_loop().time() > deadline:
                raise AssertionError("runner did not exit in time")
            await asyncio.sleep(0.05)
        exit_token = runners_mod.fingerprint_token("fp-key")
        assert exit_token.startswith("exit:")
        assert exit_token != running_token
        runners_mod.clear_exited("fp-key")
        assert runners_mod.fingerprint_token("fp-key") == "off"

    asyncio.run(_body())


def test_reap_all_sends_sigterm(tmp_path) -> None:
    """``reap_all`` SIGTERMs every live session (shutdown hook path)."""

    async def _body():
        session = await runners_mod.start(
            key="to-reap",
            checkout_key="main",
            path=str(tmp_path),
            template="sleep 30",
            shell="/bin/sh",
        )
        runners_mod.reap_all()
        deadline = asyncio.get_event_loop().time() + 3.0
        while session.exit_code is None:
            if asyncio.get_event_loop().time() > deadline:
                raise AssertionError("runner did not exit after reap")
            await asyncio.sleep(0.05)
        assert session.exit_code is not None
        runners_mod.clear_exited("to-reap")

    asyncio.run(_body())
