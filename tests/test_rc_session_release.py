"""Tests for releasing REMOTE_CONTROL sessions the panel needs back.

An IDS-CAN REMOTE_CONTROL session belongs to whoever opened it until it is
explicitly closed, and the device keeps it even when the BLE link drops.  Every
COMMAND (relay, queued replay, cover) therefore has to be followed by a release,
or the coach's physical panel stays locked out of that device until the gateway
is power-cycled.

The release is deliberately NOT on the command path: closing immediately after a
relay write produced session terminations (reason 0x0E), unconfirmed COMMANDs and
state that reverted a few seconds later.  These tests pin the janitor's rules:

* an idle session is released after the grace period;
* a session owned by a cover movement is left alone;
* a session owed from before a disconnect is still closed afterwards;
* releasing a stale device does not cancel the heartbeat of the live session.

The coordinator is built with ``object.__new__``; only the collaborators these
methods touch are replaced.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from custom_components.ha_onecontrol import coordinator as coordinator_module
from custom_components.ha_onecontrol.coordinator import OneControlCoordinator

IDLE_DEVICE = 0x86
LIVE_DEVICE = 0x91
# Cover tasks are keyed by the "tt:dd" cover key the covers map uses.
IDLE_COVER_KEY = f"00:{IDLE_DEVICE:02x}"
LIVE_COVER_KEY = f"00:{LIVE_DEVICE:02x}"


class _FakeHass:
    def __init__(self) -> None:
        self.tasks: list[asyncio.Task[Any]] = []

    def async_create_background_task(
        self, coro: Any, name: str | None = None
    ) -> asyncio.Task[Any]:
        task = asyncio.ensure_future(coro)
        self.tasks.append(task)
        return task


class SessionHarness:
    def __init__(self, *, connected: bool = True) -> None:
        self.coordinator = object.__new__(OneControlCoordinator)
        c = self.coordinator
        c._client = object()
        c._connected = connected
        c._can_read_subscribed = connected
        c._gateway_can_address = 0x11
        c._rc_session_lock = asyncio.Lock()
        c._rc_session_open = True
        c._rc_session_target = IDLE_DEVICE
        c._rc_session_sid_bytes = bytes([0x00, 0x04])
        c._rc_session_dirty = {IDLE_DEVICE: time.monotonic()}
        c._rc_janitor_task = None
        c._rc_heartbeat_task = None
        c._cover_command_tasks = {}
        c.hass = _FakeHass()
        self.frames: list[tuple[str, int, int]] = []  # (label, target, message_data)

    @property
    def c(self) -> Any:
        return self.coordinator

    async def _write_can_frame(self, client: Any, frame: Any, *, label: str = "") -> None:
        # IDS-CAN wire frame: [dlc][id(4)][payload...]; message_data is payload[0]
        payload = bytes(frame)
        self.frames.append((label, payload[5] if len(payload) > 5 else -1, len(payload)))

    def install(self, **covers: Any) -> None:
        self.c._write_can_frame = self._write_can_frame

    def closes(self) -> list[str]:
        return [label for label, _payload, _len in self.frames if "SESSION_CLOSE" in label]


def _install_writer(harness: SessionHarness) -> None:
    """Capture the CAN target address of each frame, not just the label."""

    async def _write(client: Any, frame: Any, *, label: str = "") -> None:
        raw = bytes(frame)
        # 29-bit extended frame: dlc, id[4] (target in the low byte), payload
        target = raw[5] if len(raw) > 5 else -1
        harness.frames.append((label, target, len(raw)))

    harness.c._write_can_frame = _write


@pytest.fixture(autouse=True)
def fast_release(monkeypatch: pytest.MonkeyPatch) -> None:
    """Shrink the grace period and janitor interval for the tests."""
    monkeypatch.setattr(coordinator_module, "RC_SESSION_IDLE_RELEASE_S", 0.2)
    monkeypatch.setattr(coordinator_module, "RC_SESSION_JANITOR_INTERVAL_S", 0.05)


def test_idle_session_is_released() -> None:
    """A relay session goes quiet; the janitor hands the device back."""

    async def scenario() -> SessionHarness:
        harness = SessionHarness()
        _install_writer(harness)
        harness.c._rc_session_dirty = {IDLE_DEVICE: time.monotonic() - 1.0}
        await harness.c._async_reap_idle_rc_sessions()
        return harness

    harness = asyncio.run(scenario())

    assert harness.closes() == ["SESSION_CLOSE"]
    assert harness.c._rc_session_dirty == {}
    assert harness.c._rc_session_open is False
    assert harness.c._rc_session_target is None


def test_cover_movement_keeps_its_session() -> None:
    """A moving cover owns the session: the janitor must not close it."""

    async def scenario() -> SessionHarness:
        harness = SessionHarness()
        _install_writer(harness)
        harness.c._rc_session_dirty = {IDLE_DEVICE: time.monotonic() - 60.0}
        harness.c._cover_command_tasks = {IDLE_COVER_KEY: object()}
        await harness.c._async_reap_idle_rc_sessions()
        return harness

    harness = asyncio.run(scenario())

    assert harness.closes() == []
    assert harness.c._rc_session_open is True


def test_recent_command_keeps_its_session() -> None:
    """The grace period protects the confirmation window after a write."""

    async def scenario() -> SessionHarness:
        harness = SessionHarness()
        _install_writer(harness)
        harness.c._note_rc_session_command(IDLE_DEVICE)
        await harness.c._async_reap_idle_rc_sessions()
        return harness

    harness = asyncio.run(scenario())

    assert harness.closes() == []
    assert harness.c._rc_session_open is True


def test_session_owed_from_before_a_disconnect_is_released_after_it() -> None:
    """The device keeps the session across a link drop, so we still owe a close."""

    async def scenario() -> SessionHarness:
        harness = SessionHarness()
        _install_writer(harness)
        # Connected again, but this coordinator holds no live session: the map
        # is what remembers the session opened before the disconnect.
        harness.c._rc_session_open = False
        harness.c._rc_session_target = None
        harness.c._rc_session_dirty = {IDLE_DEVICE: time.monotonic() - 1.0}
        await harness.c._async_reap_idle_rc_sessions()
        return harness

    harness = asyncio.run(scenario())

    assert harness.closes() == ["SESSION_CLOSE"]
    assert harness.c._rc_session_dirty == {}


def test_releasing_a_stale_device_leaves_the_live_session_alone() -> None:
    """Closing device A must not cancel the heartbeat holding device B."""

    async def scenario() -> tuple[SessionHarness, bool]:
        harness = SessionHarness()
        _install_writer(harness)

        class _Heartbeat:
            cancelled = False

            def done(self) -> bool:
                return False

            def cancel(self) -> None:
                self.cancelled = True

        heartbeat = _Heartbeat()
        harness.c._rc_heartbeat_task = heartbeat
        harness.c._rc_session_target = LIVE_DEVICE
        harness.c._rc_session_dirty = {
            IDLE_DEVICE: time.monotonic() - 60.0,
            LIVE_DEVICE: time.monotonic(),
        }
        harness.c._cover_command_tasks = {LIVE_COVER_KEY: object()}

        await harness.c._async_reap_idle_rc_sessions()
        return harness, heartbeat.cancelled

    harness, cancelled = asyncio.run(scenario())

    assert harness.closes() == ["SESSION_CLOSE"]
    assert cancelled is False, "the live session's heartbeat was cancelled"
    assert harness.c._rc_session_open is True
    assert IDLE_DEVICE not in harness.c._rc_session_dirty
    assert LIVE_DEVICE in harness.c._rc_session_dirty


def test_janitor_runs_while_connected_and_stops_when_not() -> None:
    """The janitor loop closes idle sessions on its own, and exits on disconnect."""

    async def scenario() -> SessionHarness:
        harness = SessionHarness()
        _install_writer(harness)
        harness.c._rc_session_dirty = {IDLE_DEVICE: time.monotonic() - 1.0}
        harness.c._start_rc_session_janitor()
        await asyncio.sleep(0.2)
        harness.c._connected = False
        await asyncio.sleep(0.15)
        return harness

    harness = asyncio.run(scenario())

    assert harness.closes() == ["SESSION_CLOSE"]
    assert harness.c._rc_session_dirty == {}


def test_release_all_sessions_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    """Teardown must not hang on a wedged write."""
    monkeypatch.setattr(coordinator_module, "RC_SESSION_RELEASE_TIMEOUT_S", 0.2)

    async def scenario() -> tuple[SessionHarness, float]:
        harness = SessionHarness()

        async def _hang(client: Any, frame: Any, *, label: str = "") -> None:
            await asyncio.sleep(3600)

        harness.c._write_can_frame = _hang
        harness.c._rc_session_dirty = {IDLE_DEVICE: time.monotonic()}
        began = time.monotonic()
        await harness.c._async_release_all_rc_sessions("coordinator shutting down")
        return harness, time.monotonic() - began

    harness, elapsed = asyncio.run(scenario())

    assert elapsed < 1.0, f"teardown blocked for {elapsed:.2f}s"
    # The write never went out, so the debt is kept and re-stamped — retried on
    # a later pass rather than abandoned (the panel is still locked out).
    assert IDLE_DEVICE in harness.c._rc_session_dirty
    assert harness.c._rc_session_dirty[IDLE_DEVICE] > 0


def test_failed_release_is_retried_after_another_grace_period() -> None:
    """A close that fails must not spin, and must not be forgotten."""

    async def scenario() -> tuple[SessionHarness, float]:
        harness = SessionHarness()

        async def _fail(client: Any, frame: Any, *, label: str = "") -> None:
            raise RuntimeError("BLE write failed")

        harness.c._write_can_frame = _fail
        harness.c._rc_session_dirty = {IDLE_DEVICE: time.monotonic() - 60.0}
        began = time.monotonic()
        # Two janitor passes back to back: the second must skip the device
        # because the failure re-stamped it.
        await harness.c._async_reap_idle_rc_sessions()
        await harness.c._async_reap_idle_rc_sessions()
        return harness, time.monotonic() - began

    harness, _elapsed = asyncio.run(scenario())

    assert IDLE_DEVICE in harness.c._rc_session_dirty
    assert time.monotonic() - harness.c._rc_session_dirty[IDLE_DEVICE] < 5.0
