"""Brain Daemon - background tick loop for proactive behavior."""

import asyncio
import time
from datetime import datetime
from typing import Callable, Optional, Any, TYPE_CHECKING

from rilai.contracts.events import EngineEvent, EventKind
from rilai.store.event_log import EventLogWriter

if TYPE_CHECKING:
    from rilai.runtime.workspace import Workspace


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
