"""TurnRunner - orchestrates a single turn, yielding ordered events."""

import time
from typing import AsyncIterator, TYPE_CHECKING

from rilai.contracts.events import EngineEvent, EventKind
from rilai.store.event_log import EventLogWriter

if TYPE_CHECKING:
    from rilai.runtime.workspace import Workspace
    from rilai.runtime.scheduler import Scheduler


class TurnRunner:
    """Orchestrates a single turn, yielding ordered events.

    This is the main entry point for processing user messages.
    It yields events as an async iterator, which the TUI consumes.
    """

    def __init__(
        self,
        event_log: EventLogWriter,
        workspace: "Workspace",
        scheduler: "Scheduler",
    ):
        self.event_log = event_log
        self.workspace = workspace
        self.scheduler = scheduler
        self.session_id: str = ""
        self.turn_id: int = 0
        self._start_monotonic: float = 0.0

    def set_session(self, session_id: str) -> None:
        """Set the current session ID."""
        self.session_id = session_id
        self.turn_id = self.event_log.get_last_turn_id(session_id)

    def _emit(self, kind: EventKind, payload: dict) -> EngineEvent:
        """Create, persist, and return an event."""
        event = EngineEvent(
            session_id=self.session_id,
            turn_id=self.turn_id,
            seq=self.event_log.next_seq(self.session_id, self.turn_id),
            ts_monotonic=time.monotonic(),
            kind=kind,
            payload=payload,
        )
        self.event_log.append(event)
        return event

    async def run_turn(self, user_input: str) -> AsyncIterator[EngineEvent]:
        """Execute turn pipeline, yielding events as they occur.

        This is the main method called by the TUI/shell.

        Args:
            user_input: The user's message

        Yields:
            EngineEvent objects in order
        """
        self.turn_id += 1
        self._start_monotonic = time.monotonic()

        # ─────────────────────────────────────────────────────────────────
        # Stage 0: Ingest & Normalize
        # ─────────────────────────────────────────────────────────────────
        yield self._emit(
            EventKind.TURN_STARTED,
            {"user_input": user_input, "turn_id": self.turn_id},
        )
        yield self._emit(EventKind.TURN_STAGE_CHANGED, {"stage": "ingest"})

        self.workspace.set_user_message(user_input)
        self.workspace.turn_id = self.turn_id

        # ─────────────────────────────────────────────────────────────────
        # Stage 1: Fast Sensors
        # ─────────────────────────────────────────────────────────────────
        yield self._emit(EventKind.TURN_STAGE_CHANGED, {"stage": "sensing_fast"})

        sensors = self._run_fast_sensors(user_input)
        self.workspace.sensors = sensors
        yield self._emit(EventKind.SENSORS_FAST_UPDATED, {"sensors": sensors})

        # Safety early-exit check
        if sensors.get("safety_risk", 0) > 0.8:
            yield self._emit(
                EventKind.SAFETY_INTERRUPT,
                {"reason": "high_safety_risk", "sensor": "safety_risk", "value": sensors["safety_risk"]},
            )
            async for event in self._run_safety_council():
                yield event
            yield self._complete_turn()
            return

        # ─────────────────────────────────────────────────────────────────
        # Stage 2: Context Build (Memory Retrieval)
        # ─────────────────────────────────────────────────────────────────
        yield self._emit(EventKind.TURN_STAGE_CHANGED, {"stage": "context"})

        async for event in self._run_memory_retrieval():
            yield event

        # ─────────────────────────────────────────────────────────────────
        # Stage 3-4: Agent Waves
        # ─────────────────────────────────────────────────────────────────
        yield self._emit(EventKind.TURN_STAGE_CHANGED, {"stage": "agents"})

        async for event in self._run_agent_waves():
            yield event

        # ─────────────────────────────────────────────────────────────────
        # Stage 5: Deliberation
        # ─────────────────────────────────────────────────────────────────
        yield self._emit(EventKind.TURN_STAGE_CHANGED, {"stage": "deliberation"})

        async for event in self._run_deliberation():
            yield event

        # ─────────────────────────────────────────────────────────────────
        # Stage 6: Council + Voice
        # ─────────────────────────────────────────────────────────────────
        yield self._emit(EventKind.TURN_STAGE_CHANGED, {"stage": "council"})

        async for event in self._run_council():
            yield event

        # ─────────────────────────────────────────────────────────────────
        # Stage 7: Critics
        # ─────────────────────────────────────────────────────────────────
        yield self._emit(EventKind.TURN_STAGE_CHANGED, {"stage": "critics"})

        async for event in self._run_critics():
            yield event

        # ─────────────────────────────────────────────────────────────────
        # Stage 8: Memory Commit
        # ─────────────────────────────────────────────────────────────────
        yield self._emit(EventKind.TURN_STAGE_CHANGED, {"stage": "memory_commit"})

        async for event in self._run_memory_commit():
            yield event

        # ─────────────────────────────────────────────────────────────────
        # Done
        # ─────────────────────────────────────────────────────────────────
        yield self._complete_turn()

    def _complete_turn(self) -> EngineEvent:
        """Create turn completion event."""
        total_time_ms = int((time.monotonic() - self._start_monotonic) * 1000)
        return self._emit(
            EventKind.TURN_COMPLETED,
            {
                "total_time_ms": total_time_ms,
                "response": self.workspace.current_response,
            },
        )

    # ─────────────────────────────────────────────────────────────────────
    # Stage Implementations (delegate to stages module)
    # ─────────────────────────────────────────────────────────────────────

    def _run_fast_sensors(self, text: str) -> dict[str, float]:
        """Stage 1: Deterministic sensor extraction.

        No LLM calls - pure keyword/pattern matching.
        """
        from rilai.runtime.stages import run_fast_sensors
        return run_fast_sensors(text)

    async def _run_memory_retrieval(self) -> AsyncIterator[EngineEvent]:
        """Stage 2: Retrieve episodic events, user facts, open threads."""
        from rilai.runtime.stages import run_memory_retrieval
        async for event in run_memory_retrieval(self, self.workspace):
            yield event

    async def _run_agent_waves(self) -> AsyncIterator[EngineEvent]:
        """Stage 3-4: Run scheduled agents in waves."""
        from rilai.runtime.stages import run_agent_waves
        async for event in run_agent_waves(self, self.workspace, self.scheduler):
            yield event

    async def _run_deliberation(self) -> AsyncIterator[EngineEvent]:
        """Stage 5: Claim-based deliberation."""
        from rilai.runtime.stages import run_deliberation
        async for event in run_deliberation(self, self.workspace):
            yield event

    async def _run_council(self) -> AsyncIterator[EngineEvent]:
        """Stage 6: Council decision + voice rendering."""
        from rilai.runtime.stages import run_council
        async for event in run_council(self, self.workspace):
            yield event

    async def _run_safety_council(self) -> AsyncIterator[EngineEvent]:
        """Safety-interrupt council (minimal)."""
        from rilai.runtime.stages import run_safety_council
        async for event in run_safety_council(self, self.workspace):
            yield event

    async def _run_critics(self) -> AsyncIterator[EngineEvent]:
        """Stage 7: Post-generation validation."""
        from rilai.runtime.stages import run_critics
        async for event in run_critics(self, self.workspace):
            yield event

    async def _run_memory_commit(self) -> AsyncIterator[EngineEvent]:
        """Stage 8: Commit durable memory updates."""
        from rilai.runtime.stages import run_memory_commit
        async for event in run_memory_commit(self, self.workspace):
            yield event
