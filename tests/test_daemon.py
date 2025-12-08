"""Tests for daemon module."""

import pytest
import asyncio
import time

from rilai.daemon.brain import BrainDaemon
from rilai.daemon.nudges import NudgeChecker
from rilai.daemon.decay import ModulatorDecay, DecayResult
from rilai.contracts.workspace import GlobalModulators


class MockStance:
    """Mock stance for testing."""
    def __init__(self):
        self.strain = 0.3
        self.valence = 0.0
        self.closeness = 0.5


class MockWorkspace:
    """Mock workspace for testing."""
    def __init__(self):
        self.modulators = GlobalModulators(
            arousal=0.8,
            fatigue=0.5,
            time_pressure=0.6,
            social_risk=0.3,
        )
        self.stance = MockStance()
        self.last_user_message_time = time.time()
        self.open_threads = []


class MockEventLog:
    """Mock event log for testing."""
    def __init__(self):
        self.events = []

    def append(self, event):
        self.events.append(event)

    def next_seq(self, session_id, turn_id):
        return len(self.events)


class TestModulatorDecay:
    def test_decay_toward_baseline(self):
        workspace = MockWorkspace()
        workspace.modulators.arousal = 0.8

        decay = ModulatorDecay(workspace)
        result = decay.apply_decay()

        assert result.any_changed
        assert workspace.modulators.arousal < 0.8
        assert workspace.modulators.arousal > 0.3  # Baseline

    def test_no_decay_at_baseline(self):
        workspace = MockWorkspace()
        workspace.modulators.arousal = 0.3  # At baseline
        workspace.modulators.fatigue = 0.0
        workspace.modulators.time_pressure = 0.0
        workspace.modulators.social_risk = 0.0

        decay = ModulatorDecay(workspace)
        result = decay.apply_decay()

        # Should have minimal/no changes
        assert not result.any_changed or all(
            abs(d) < 0.01 for d in result.deltas.values()
        )

    def test_decay_forecast(self):
        workspace = MockWorkspace()
        workspace.modulators.arousal = 1.0

        decay = ModulatorDecay(workspace)
        forecast = decay.get_decay_forecast(ticks=5)

        # Values should decrease toward baseline
        arousal_forecast = forecast["arousal"]
        assert arousal_forecast[0] < 1.0
        assert arousal_forecast[-1] < arousal_forecast[0]

    def test_apply_spike(self):
        workspace = MockWorkspace()
        workspace.modulators.arousal = 0.5

        decay = ModulatorDecay(workspace)
        decay.apply_spike("arousal", 0.3)

        assert workspace.modulators.arousal == 0.8

    def test_apply_spike_clamps_to_max(self):
        workspace = MockWorkspace()
        workspace.modulators.arousal = 0.9

        decay = ModulatorDecay(workspace)
        decay.apply_spike("arousal", 0.5)

        assert workspace.modulators.arousal == 1.0

    def test_apply_spike_clamps_to_min(self):
        workspace = MockWorkspace()
        workspace.modulators.arousal = 0.1

        decay = ModulatorDecay(workspace)
        decay.apply_spike("arousal", -0.5)

        assert workspace.modulators.arousal == 0.0

    def test_decay_result_contains_deltas(self):
        workspace = MockWorkspace()
        workspace.modulators.arousal = 0.8
        workspace.modulators.fatigue = 0.5

        decay = ModulatorDecay(workspace)
        result = decay.apply_decay()

        assert "arousal" in result.new_values
        assert result.any_changed


class TestNudgeChecker:
    @pytest.mark.asyncio
    async def test_high_stress_silence_triggers(self):
        workspace = MockWorkspace()
        workspace.stance.strain = 0.8
        workspace.last_user_message_time = time.time() - 400  # 6+ minutes ago

        checker = NudgeChecker(workspace)
        nudge = await checker.check_all()

        assert nudge is not None
        assert nudge["reason"] == "high_stress_silence"

    @pytest.mark.asyncio
    async def test_no_nudge_when_recent_message(self):
        workspace = MockWorkspace()
        workspace.stance.strain = 0.8
        workspace.last_user_message_time = time.time() - 60  # 1 minute ago

        checker = NudgeChecker(workspace)
        nudge = await checker.check_all()

        # Should not trigger - too recent
        assert nudge is None or nudge["reason"] != "high_stress_silence"

    @pytest.mark.asyncio
    async def test_cooldown_prevents_repeat_nudge(self):
        workspace = MockWorkspace()
        workspace.stance.strain = 0.8
        workspace.last_user_message_time = time.time() - 400

        checker = NudgeChecker(workspace)

        # First nudge should trigger
        nudge1 = await checker.check_all()
        assert nudge1 is not None

        # Immediate second check should not trigger (cooldown)
        nudge2 = await checker.check_all()
        assert nudge2 is None

    @pytest.mark.asyncio
    async def test_no_nudge_when_low_stress(self):
        workspace = MockWorkspace()
        workspace.stance.strain = 0.3
        workspace.last_user_message_time = time.time() - 400

        checker = NudgeChecker(workspace)
        nudge = await checker.check_all()

        # Should not trigger high_stress_silence - stress is low
        assert nudge is None or nudge["reason"] != "high_stress_silence"

    @pytest.mark.asyncio
    async def test_rupture_unresolved_triggers(self):
        workspace = MockWorkspace()
        workspace.stance.valence = -0.5
        workspace.stance.strain = 0.55  # Below 0.6 (high_stress threshold) but >= 0.5 for rupture
        workspace.stance.closeness = 0.2
        workspace.last_user_message_time = time.time() - 600  # 10 min ago

        checker = NudgeChecker(workspace)
        nudge = await checker.check_all()

        assert nudge is not None
        assert nudge["reason"] == "rupture_unresolved"

    @pytest.mark.asyncio
    async def test_session_break_triggers(self):
        workspace = MockWorkspace()
        workspace.modulators.fatigue = 0.6

        checker = NudgeChecker(workspace)
        checker._session_start = time.time() - 4000  # 66+ minutes ago

        nudge = await checker.check_all()

        assert nudge is not None
        assert nudge["reason"] == "session_break"

    def test_reset_session(self):
        workspace = MockWorkspace()
        checker = NudgeChecker(workspace)
        checker._last_nudge_times["test"] = time.time()
        checker._session_start = 0

        checker.reset_session()

        assert len(checker._last_nudge_times) == 0
        assert checker._session_start > 0


class TestBrainDaemon:
    @pytest.mark.asyncio
    async def test_daemon_starts_and_stops(self):
        workspace = MockWorkspace()
        event_log = MockEventLog()

        daemon = BrainDaemon(
            event_log=event_log,
            workspace=workspace,
            tick_interval=0.1,  # Fast for testing
        )

        await daemon.start("test-session")
        assert daemon.is_running

        await asyncio.sleep(0.25)  # Allow 2 ticks
        await daemon.stop()

        assert not daemon.is_running
        assert daemon._tick_count >= 2

    @pytest.mark.asyncio
    async def test_daemon_emits_tick_events(self):
        workspace = MockWorkspace()
        event_log = MockEventLog()

        daemon = BrainDaemon(
            event_log=event_log,
            workspace=workspace,
            tick_interval=0.1,
        )

        await daemon.start("test-session")
        await asyncio.sleep(0.15)
        await daemon.stop()

        # Should have at least one tick event
        tick_events = [e for e in event_log.events if e.kind.value == "daemon_tick"]
        assert len(tick_events) >= 1

    @pytest.mark.asyncio
    async def test_daemon_does_not_start_twice(self):
        workspace = MockWorkspace()
        event_log = MockEventLog()

        daemon = BrainDaemon(
            event_log=event_log,
            workspace=workspace,
            tick_interval=0.1,
        )

        await daemon.start("test-session")
        task1 = daemon._task
        await daemon.start("test-session-2")
        task2 = daemon._task

        assert task1 is task2  # Same task, not restarted

        await daemon.stop()

    @pytest.mark.asyncio
    async def test_daemon_get_status(self):
        workspace = MockWorkspace()
        event_log = MockEventLog()

        daemon = BrainDaemon(
            event_log=event_log,
            workspace=workspace,
            tick_interval=0.5,
        )

        status = daemon.get_status()
        assert status["running"] is False
        assert status["tick_count"] == 0

        await daemon.start("test-session")
        status = daemon.get_status()
        assert status["running"] is True
        assert status["session_id"] == "test-session"

        await daemon.stop()

    @pytest.mark.asyncio
    async def test_daemon_calls_nudge_callback(self):
        workspace = MockWorkspace()
        workspace.stance.strain = 0.8
        workspace.last_user_message_time = time.time() - 400
        event_log = MockEventLog()

        callback_called = []

        async def callback(nudge):
            callback_called.append(nudge)

        daemon = BrainDaemon(
            event_log=event_log,
            workspace=workspace,
            tick_interval=0.05,
            nudge_callback=callback,
        )

        await daemon.start("test-session")
        await asyncio.sleep(0.1)
        await daemon.stop()

        # Callback should have been called with nudge
        assert len(callback_called) >= 1
        assert callback_called[0]["reason"] == "high_stress_silence"

    @pytest.mark.asyncio
    async def test_daemon_applies_decay(self):
        workspace = MockWorkspace()
        workspace.modulators.arousal = 0.9
        event_log = MockEventLog()

        daemon = BrainDaemon(
            event_log=event_log,
            workspace=workspace,
            tick_interval=0.05,
        )

        await daemon.start("test-session")
        await asyncio.sleep(0.1)
        await daemon.stop()

        # Arousal should have decayed
        assert workspace.modulators.arousal < 0.9
