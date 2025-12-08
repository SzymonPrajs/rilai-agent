"""DebugProjection - agent traces and timing for debugging."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from rilai.contracts.events import EngineEvent, EventKind
from rilai.store.projections.base import Projection


@dataclass
class AgentTrace:
    """Trace of a single agent execution."""

    agent_id: str
    turn_id: int
    started_at: datetime | None = None
    completed_at: datetime | None = None
    observation: str = ""
    claims: list[dict] = field(default_factory=list)
    urgency: int = 0
    confidence: int = 0
    salience: float = 0.0
    error: str | None = None
    processing_time_ms: int = 0


@dataclass
class DebugProjection(Projection):
    """Tracks agent traces and timing for debugging.

    Useful for understanding what agents did and why.
    """

    # Per-turn agent traces
    turn_traces: dict[int, list[AgentTrace]] = field(default_factory=dict)

    # Pending traces (started but not completed)
    pending_traces: dict[str, AgentTrace] = field(default_factory=dict)

    # Stage timing
    stage_timing: dict[int, dict[str, float]] = field(default_factory=dict)

    # Error history
    errors: list[dict] = field(default_factory=list)

    def reset(self) -> None:
        """Reset to initial state."""
        self.turn_traces.clear()
        self.pending_traces.clear()
        self.stage_timing.clear()
        self.errors.clear()

    def apply(self, event: EngineEvent) -> None:
        """Apply event to update debug state."""
        turn_id = event.turn_id

        match event.kind:
            case EventKind.TURN_STARTED:
                self.turn_traces[turn_id] = []
                self.stage_timing[turn_id] = {}

            case EventKind.TURN_STAGE_CHANGED:
                stage = event.payload.get("stage", "unknown")
                if turn_id in self.stage_timing:
                    self.stage_timing[turn_id][stage] = event.ts_monotonic

            case EventKind.AGENT_STARTED:
                agent_id = event.payload.get("agent_id", "?")
                trace = AgentTrace(
                    agent_id=agent_id,
                    turn_id=turn_id,
                    started_at=event.ts_wall,
                )
                self.pending_traces[agent_id] = trace

            case EventKind.AGENT_COMPLETED:
                agent_id = event.payload.get("agent_id", "?")
                trace = self.pending_traces.pop(agent_id, None)
                if trace is None:
                    trace = AgentTrace(agent_id=agent_id, turn_id=turn_id)

                trace.completed_at = event.ts_wall
                trace.observation = event.payload.get("observation", "")
                trace.claims = event.payload.get("claims", [])
                trace.urgency = event.payload.get("urgency", 0)
                trace.confidence = event.payload.get("confidence", 0)
                trace.salience = event.payload.get("salience", 0.0)
                trace.processing_time_ms = event.payload.get("processing_time_ms", 0)

                if turn_id in self.turn_traces:
                    self.turn_traces[turn_id].append(trace)

            case EventKind.AGENT_FAILED:
                agent_id = event.payload.get("agent_id", "?")
                error = event.payload.get("error", "Unknown error")
                trace = self.pending_traces.pop(agent_id, None)
                if trace is None:
                    trace = AgentTrace(agent_id=agent_id, turn_id=turn_id)

                trace.completed_at = event.ts_wall
                trace.error = error

                if turn_id in self.turn_traces:
                    self.turn_traces[turn_id].append(trace)

            case EventKind.ERROR:
                self.errors.append({
                    "turn_id": turn_id,
                    "error": event.payload.get("error", "Unknown"),
                    "traceback": event.payload.get("traceback"),
                    "timestamp": event.ts_wall.isoformat(),
                })

    def get_turn_summary(self, turn_id: int) -> dict[str, Any]:
        """Get summary of a turn for debugging."""
        traces = self.turn_traces.get(turn_id, [])
        timing = self.stage_timing.get(turn_id, {})

        return {
            "turn_id": turn_id,
            "agent_count": len(traces),
            "agents": [
                {
                    "agent_id": t.agent_id,
                    "observation": t.observation[:100] if t.observation else "",
                    "urgency": t.urgency,
                    "confidence": t.confidence,
                    "salience": t.salience,
                    "error": t.error,
                    "processing_time_ms": t.processing_time_ms,
                }
                for t in traces
            ],
            "stages": list(timing.keys()),
            "errors": [e for e in self.errors if e["turn_id"] == turn_id],
        }
