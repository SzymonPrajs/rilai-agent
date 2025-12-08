# Document 10: Brain Daemon

**Purpose:** Implement background tick loop with modulator decay and proactive nudges
**Execution:** One Claude Code session
**Dependencies:** 01-contracts, 02-event-store, 04-workspace

---

## Implementation Checklist

> **Instructions:** Mark items with `[x]` when complete. After completing items here,
> also update the master checklist in `00-overview.md`.

### Files to Create
- [x] `src/rilai/daemon/__init__.py`
- [x] `src/rilai/daemon/brain.py` - BrainDaemon class
- [x] `src/rilai/daemon/nudges.py` - NudgeChecker class
- [x] `src/rilai/daemon/decay.py` - ModulatorDecay class

### BrainDaemon Features
- [x] start() / stop() methods
- [x] _tick_loop() with configurable interval
- [x] _tick() applies decay and checks nudges
- [x] Emit DAEMON_TICK events
- [x] is_running property
- [x] get_status() for diagnostics

### NudgeChecker Features
- [x] check_all() returns nudge dict or None
- [x] Cooldown tracking per condition
- [x] high_stress_silence condition
- [x] deadline_approaching condition
- [x] rupture_unresolved condition
- [x] session_break condition
- [x] idle_checkin condition

### ModulatorDecay Features
- [x] BASELINES for each modulator
- [x] DECAY_RATES for each modulator
- [x] apply_decay() returns DecayResult
- [x] apply_spike() for external events
- [x] get_decay_forecast() for debugging

### TUI Integration
- [ ] Start daemon on app mount (pending TUI integration)
- [ ] Stop daemon on app unmount (pending TUI integration)
- [ ] Handle nudge callback (pending TUI integration)

### Verification
- [x] Daemon starts and ticks
- [x] Modulators decay correctly
- [x] Nudges fire under correct conditions
- [x] Write and run unit tests

### Notes
_Add any implementation notes, issues, or decisions here:_

---

## Overview

The Brain Daemon runs in the background, independent of user interaction. It:
1. Decays modulators toward baseline over time
2. Checks conditions for proactive nudges
3. Maintains awareness of open threads and deadlines
4. Emits events to the event log for observability

---

## Files to Create

```
src/rilai/daemon/
├── __init__.py
├── brain.py            # Main daemon loop
├── nudges.py           # Proactive nudge conditions
└── decay.py            # Modulator decay logic
```

---

## File: `src/rilai/daemon/__init__.py`

```python
"""Rilai v3 Brain Daemon - Background processing."""

from rilai.daemon.brain import BrainDaemon
from rilai.daemon.nudges import NudgeChecker
from rilai.daemon.decay import ModulatorDecay

__all__ = ["BrainDaemon", "NudgeChecker", "ModulatorDecay"]
```

---

## File: `src/rilai/daemon/brain.py`

```python
"""Brain Daemon - background tick loop for proactive behavior."""

import asyncio
import time
from datetime import datetime
from typing import Callable, Optional, Any

from rilai.contracts.events import EngineEvent, EventKind
from rilai.store.event_log import EventLogWriter


class BrainDaemon:
    """Background daemon for proactive behavior.

    Runs independently of user interaction to:
    - Decay modulators toward baseline
    - Check for proactive nudge conditions
    - Monitor open goals and deadlines
    """

    DEFAULT_TICK_INTERVAL = 30.0  # seconds
    DAEMON_TURN_ID = 0  # Daemon events use turn_id=0

    def __init__(
        self,
        event_log: EventLogWriter,
        workspace: "Workspace",
        tick_interval: float = DEFAULT_TICK_INTERVAL,
        nudge_callback: Optional[Callable[[dict], Any]] = None,
    ):
        """Initialize the daemon.

        Args:
            event_log: Event log for persistence
            workspace: Shared workspace state
            tick_interval: Seconds between ticks
            nudge_callback: Optional callback when nudge triggers
        """
        self.event_log = event_log
        self.workspace = workspace
        self.tick_interval = tick_interval
        self.nudge_callback = nudge_callback

        self.session_id: str = ""
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._seq = 0
        self._tick_count = 0

        # Initialize helpers
        from rilai.daemon.nudges import NudgeChecker
        from rilai.daemon.decay import ModulatorDecay

        self.nudge_checker = NudgeChecker(workspace)
        self.decay = ModulatorDecay(workspace)

    def _emit(self, kind: EventKind, payload: dict) -> EngineEvent:
        """Create and persist a daemon event."""
        self._seq += 1
        event = EngineEvent(
            session_id=self.session_id,
            turn_id=self.DAEMON_TURN_ID,
            seq=self._seq,
            ts_monotonic=time.monotonic(),
            kind=kind,
            payload=payload,
        )
        self.event_log.append(event)
        return event

    async def start(self, session_id: str) -> None:
        """Start the background tick loop.

        Args:
            session_id: Session ID for events
        """
        if self._running:
            return

        self.session_id = session_id
        self._running = True
        self._tick_count = 0
        self._task = asyncio.create_task(self._tick_loop())

    async def stop(self) -> None:
        """Stop the background tick loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _tick_loop(self) -> None:
        """Main daemon loop."""
        while self._running:
            try:
                await asyncio.sleep(self.tick_interval)
                if not self._running:
                    break
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as e:
                # Log error but keep running
                self._emit(
                    EventKind.DAEMON_TICK,
                    {"error": str(e), "tick": self._tick_count},
                )

    async def _tick(self) -> None:
        """Execute a single daemon tick."""
        self._tick_count += 1
        tick_start = time.monotonic()

        # Emit tick event
        self._emit(
            EventKind.DAEMON_TICK,
            {
                "tick": self._tick_count,
                "timestamp": datetime.now().isoformat(),
            },
        )

        # 1. Decay modulators
        decay_result = self.decay.apply_decay()
        if decay_result.any_changed:
            self._emit(
                EventKind.WORKSPACE_PATCHED,
                {
                    "source": "daemon_decay",
                    "modulators": decay_result.new_values,
                    "deltas": decay_result.deltas,
                },
            )

        # 2. Check nudge conditions
        nudge = await self.nudge_checker.check_all()
        if nudge:
            self._emit(EventKind.PROACTIVE_NUDGE, nudge)

            # Call callback if provided
            if self.nudge_callback:
                try:
                    await self._call_callback(nudge)
                except Exception as e:
                    self._emit(
                        EventKind.DAEMON_TICK,
                        {"nudge_callback_error": str(e)},
                    )

        # Record tick duration
        tick_duration = time.monotonic() - tick_start
        if tick_duration > 1.0:  # Log slow ticks
            self._emit(
                EventKind.DAEMON_TICK,
                {"slow_tick": True, "duration_ms": int(tick_duration * 1000)},
            )

    async def _call_callback(self, nudge: dict) -> None:
        """Call the nudge callback, handling sync and async."""
        if asyncio.iscoroutinefunction(self.nudge_callback):
            await self.nudge_callback(nudge)
        else:
            self.nudge_callback(nudge)

    @property
    def is_running(self) -> bool:
        """Check if daemon is running."""
        return self._running and self._task is not None

    def get_status(self) -> dict:
        """Get daemon status for diagnostics."""
        return {
            "running": self.is_running,
            "tick_count": self._tick_count,
            "tick_interval": self.tick_interval,
            "session_id": self.session_id,
        }
```

---

## File: `src/rilai/daemon/nudges.py`

```python
"""Proactive nudge condition checking."""

import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, List


@dataclass
class NudgeCondition:
    """A condition that can trigger a proactive nudge."""
    id: str
    reason: str
    priority: int  # Higher = more important
    cooldown: float  # Seconds before can trigger again


class NudgeChecker:
    """Checks conditions for proactive nudges.

    Nudge conditions:
    1. High stress + user silent for extended time
    2. Open goal with approaching deadline
    3. Unresolved rupture in relationship
    4. Scheduled check-in time
    5. Long session without break reminder
    """

    # Thresholds
    SILENCE_THRESHOLD_STRESS = 300  # 5 minutes
    SILENCE_THRESHOLD_NORMAL = 1800  # 30 minutes
    DEADLINE_WARNING_HOURS = 1
    SESSION_BREAK_REMINDER = 3600  # 1 hour

    def __init__(self, workspace: "Workspace"):
        self.workspace = workspace
        self._last_nudge_times: dict[str, float] = {}
        self._session_start = time.time()

    async def check_all(self) -> Optional[dict]:
        """Check all nudge conditions.

        Returns:
            Nudge dict if condition met, None otherwise
        """
        now = time.time()

        # Check each condition in priority order
        conditions = [
            self._check_high_stress_silence,
            self._check_deadline_approaching,
            self._check_rupture_unresolved,
            self._check_session_break,
            self._check_idle_checkin,
        ]

        for check_fn in conditions:
            result = await check_fn(now)
            if result and self._can_nudge(result["condition_id"], now):
                self._last_nudge_times[result["condition_id"]] = now
                return result

        return None

    def _can_nudge(self, condition_id: str, now: float) -> bool:
        """Check if enough time has passed since last nudge."""
        last_time = self._last_nudge_times.get(condition_id, 0)
        cooldowns = {
            "high_stress_silence": 600,  # 10 min
            "deadline_approaching": 1800,  # 30 min
            "rupture_unresolved": 900,  # 15 min
            "session_break": 3600,  # 1 hour
            "idle_checkin": 1800,  # 30 min
        }
        cooldown = cooldowns.get(condition_id, 300)
        return now - last_time >= cooldown

    async def _check_high_stress_silence(self, now: float) -> Optional[dict]:
        """Check for high stress with user silence."""
        # Check strain level
        if self.workspace.stance.strain < 0.6:
            return None

        # Check silence duration
        last_msg_time = self.workspace.last_user_message_time
        if not last_msg_time:
            return None

        silence_duration = now - last_msg_time
        if silence_duration < self.SILENCE_THRESHOLD_STRESS:
            return None

        return {
            "condition_id": "high_stress_silence",
            "reason": "high_stress_silence",
            "suggestion": "gentle_checkin",
            "priority": 3,
            "context": {
                "strain": self.workspace.stance.strain,
                "silence_minutes": int(silence_duration / 60),
            },
            "message_hint": "I noticed you might be going through something. No pressure to share, but I'm here if you want to talk.",
        }

    async def _check_deadline_approaching(self, now: float) -> Optional[dict]:
        """Check for goals with approaching deadlines."""
        for goal in self.workspace.open_threads:
            if not goal.deadline:
                continue

            # Check if deadline is within warning window
            deadline_ts = goal.deadline.timestamp() if isinstance(goal.deadline, datetime) else goal.deadline
            hours_until = (deadline_ts - now) / 3600

            if 0 < hours_until <= self.DEADLINE_WARNING_HOURS:
                return {
                    "condition_id": "deadline_approaching",
                    "reason": "deadline_approaching",
                    "suggestion": "deadline_reminder",
                    "priority": 2,
                    "context": {
                        "goal": goal.text,
                        "hours_until": round(hours_until, 1),
                        "progress": goal.progress,
                    },
                    "message_hint": f"Quick heads up - your goal '{goal.text[:50]}' has a deadline coming up soon.",
                }

        return None

    async def _check_rupture_unresolved(self, now: float) -> Optional[dict]:
        """Check for unresolved relationship rupture."""
        # Check for recent negative valence + high strain combination
        if self.workspace.stance.valence > -0.3:
            return None
        if self.workspace.stance.strain < 0.5:
            return None
        if self.workspace.stance.closeness > 0.4:
            return None

        # Check if last message was recent (rupture context still relevant)
        last_msg_time = self.workspace.last_user_message_time
        if not last_msg_time:
            return None

        time_since = now - last_msg_time
        if time_since > 1800:  # 30 min - rupture context expired
            return None

        return {
            "condition_id": "rupture_unresolved",
            "reason": "rupture_unresolved",
            "suggestion": "repair_attempt",
            "priority": 4,  # High priority
            "context": {
                "valence": self.workspace.stance.valence,
                "strain": self.workspace.stance.strain,
                "closeness": self.workspace.stance.closeness,
            },
            "message_hint": "I sense things might have gotten tense. I want to understand better - can we talk about what happened?",
        }

    async def _check_session_break(self, now: float) -> Optional[dict]:
        """Check if user should take a break."""
        session_duration = now - self._session_start

        if session_duration < self.SESSION_BREAK_REMINDER:
            return None

        # Only suggest break if signs of fatigue
        if self.workspace.modulators.fatigue < 0.4:
            return None

        return {
            "condition_id": "session_break",
            "reason": "session_break",
            "suggestion": "break_reminder",
            "priority": 1,  # Low priority
            "context": {
                "session_minutes": int(session_duration / 60),
                "fatigue": self.workspace.modulators.fatigue,
            },
            "message_hint": "We've been chatting for a while. Maybe a good time for a short break?",
        }

    async def _check_idle_checkin(self, now: float) -> Optional[dict]:
        """Check for general idle check-in."""
        last_msg_time = self.workspace.last_user_message_time
        if not last_msg_time:
            return None

        silence_duration = now - last_msg_time
        if silence_duration < self.SILENCE_THRESHOLD_NORMAL:
            return None

        # Only check in if there's something to check in about
        if not self.workspace.open_threads and self.workspace.stance.strain < 0.3:
            return None

        return {
            "condition_id": "idle_checkin",
            "reason": "idle_checkin",
            "suggestion": "casual_checkin",
            "priority": 0,  # Lowest priority
            "context": {
                "silence_minutes": int(silence_duration / 60),
                "open_threads": len(self.workspace.open_threads),
            },
            "message_hint": "Hey, just checking in. How are things going?",
        }

    def reset_session(self) -> None:
        """Reset session start time (for new session)."""
        self._session_start = time.time()
        self._last_nudge_times.clear()
```

---

## File: `src/rilai/daemon/decay.py`

```python
"""Modulator decay logic."""

from dataclasses import dataclass
from typing import Dict

from rilai.contracts.workspace import GlobalModulators


@dataclass
class DecayResult:
    """Result of decay application."""
    any_changed: bool
    new_values: Dict[str, float]
    deltas: Dict[str, float]


class ModulatorDecay:
    """Applies decay to modulators over time.

    Modulators drift toward baseline values between interactions.
    Different modulators have different decay rates and baselines.
    """

    # Baseline values (what modulators drift toward)
    BASELINES = {
        "arousal": 0.3,
        "fatigue": 0.0,
        "time_pressure": 0.0,
        "social_risk": 0.0,
    }

    # Decay rates (proportion of distance to baseline per tick)
    DECAY_RATES = {
        "arousal": 0.1,      # Moderate decay
        "fatigue": 0.05,     # Slow decay (fatigue persists)
        "time_pressure": 0.15,  # Fast decay
        "social_risk": 0.1,  # Moderate decay
    }

    # Minimum change to report
    MIN_CHANGE = 0.005

    def __init__(self, workspace: "Workspace"):
        self.workspace = workspace

    def apply_decay(self) -> DecayResult:
        """Apply decay to all modulators.

        Returns:
            DecayResult with changes
        """
        modulators = self.workspace.modulators
        new_values = {}
        deltas = {}
        any_changed = False

        for modulator, baseline in self.BASELINES.items():
            current = getattr(modulators, modulator, baseline)
            rate = self.DECAY_RATES.get(modulator, 0.1)

            # Calculate decay toward baseline
            distance = current - baseline
            decay_amount = distance * rate
            new_value = current - decay_amount

            # Check if change is significant
            if abs(decay_amount) >= self.MIN_CHANGE:
                new_values[modulator] = new_value
                deltas[modulator] = -decay_amount
                setattr(modulators, modulator, new_value)
                any_changed = True
            else:
                new_values[modulator] = current

        return DecayResult(
            any_changed=any_changed,
            new_values=new_values,
            deltas=deltas,
        )

    def apply_spike(self, modulator: str, amount: float) -> None:
        """Apply an immediate spike to a modulator.

        Used when external events (not agent outputs) affect modulators.
        """
        if modulator not in self.BASELINES:
            return

        current = getattr(self.workspace.modulators, modulator, 0.0)
        new_value = max(0.0, min(1.0, current + amount))
        setattr(self.workspace.modulators, modulator, new_value)

    def get_decay_forecast(self, ticks: int = 10) -> Dict[str, list]:
        """Forecast modulator values over future ticks.

        Useful for debugging/visualization.
        """
        forecast = {m: [] for m in self.BASELINES}

        for modulator, baseline in self.BASELINES.items():
            current = getattr(self.workspace.modulators, modulator, baseline)
            rate = self.DECAY_RATES.get(modulator, 0.1)

            value = current
            for _ in range(ticks):
                distance = value - baseline
                value = value - (distance * rate)
                forecast[modulator].append(round(value, 3))

        return forecast
```

---

## Integration with TUI

Update `src/rilai/ui/app.py` to start/stop daemon:

```python
class RilaiApp(App):
    # ... existing code ...

    def __init__(self, runtime: "TurnRunner" = None):
        super().__init__()
        self.runtime = runtime
        self.projection = TurnStateProjection()
        self._processing = False
        self._daemon: Optional[BrainDaemon] = None

    async def on_mount(self) -> None:
        """Handle app mount."""
        self.query_one("#input", Input).focus()

        # Start daemon
        if self.runtime:
            from rilai.daemon.brain import BrainDaemon

            self._daemon = BrainDaemon(
                event_log=self.runtime.event_log,
                workspace=self.runtime.workspace,
                nudge_callback=self._handle_nudge,
            )
            await self._daemon.start(self.runtime.session_id)

    async def on_unmount(self) -> None:
        """Handle app unmount."""
        if self._daemon:
            await self._daemon.stop()

    async def _handle_nudge(self, nudge: dict) -> None:
        """Handle proactive nudge from daemon."""
        # Show nudge in chat
        hint = nudge.get("message_hint", "")
        if hint:
            chat = self.query_one("#chat", ChatPanel)
            chat.add_message(role="system", content=f"[Nudge] {hint}")

            # Optionally trigger a turn to generate actual response
            # This would use a special "nudge" input type
```

---

## Daemon Events

The daemon emits these events:

```python
# Regular tick
EventKind.DAEMON_TICK
payload: {
    "tick": int,
    "timestamp": str (ISO),
}

# Modulator decay
EventKind.WORKSPACE_PATCHED
payload: {
    "source": "daemon_decay",
    "modulators": dict[str, float],
    "deltas": dict[str, float],
}

# Proactive nudge
EventKind.PROACTIVE_NUDGE
payload: {
    "condition_id": str,
    "reason": str,
    "suggestion": str,
    "priority": int,
    "context": dict,
    "message_hint": str,
}
```

---

## Tests

```python
"""Tests for daemon module."""

import pytest
import asyncio
import time

from rilai.daemon.brain import BrainDaemon
from rilai.daemon.nudges import NudgeChecker
from rilai.daemon.decay import ModulatorDecay, DecayResult
from rilai.contracts.workspace import GlobalModulators


class MockWorkspace:
    def __init__(self):
        self.modulators = GlobalModulators(
            arousal=0.8,
            fatigue=0.5,
            time_pressure=0.6,
            social_risk=0.3,
        )
        self.stance = type("Stance", (), {
            "strain": 0.3,
            "valence": 0.0,
            "closeness": 0.5,
        })()
        self.last_user_message_time = time.time()
        self.open_threads = []


class MockEventLog:
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
```

---

## Next Document

Proceed to `11-migration.md` after daemon is implemented.
