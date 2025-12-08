"""Event definitions - the backbone of v3 event sourcing."""

from enum import Enum
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class EventKind(str, Enum):
    """All event kinds in the system.

    Organized by lifecycle stage for clarity.
    """

    # ─────────────────────────────────────────────────────────────────────
    # Turn Lifecycle
    # ─────────────────────────────────────────────────────────────────────
    TURN_STARTED = "turn_started"
    TURN_STAGE_CHANGED = "turn_stage_changed"
    TURN_COMPLETED = "turn_completed"

    # ─────────────────────────────────────────────────────────────────────
    # Sensors
    # ─────────────────────────────────────────────────────────────────────
    SENSORS_FAST_UPDATED = "sensors_fast_updated"
    SENSORS_ENSEMBLE_UPDATED = "sensors_ensemble_updated"

    # ─────────────────────────────────────────────────────────────────────
    # Agents / Agencies
    # ─────────────────────────────────────────────────────────────────────
    AGENT_STARTED = "agent_started"
    AGENT_COMPLETED = "agent_completed"
    AGENT_FAILED = "agent_failed"
    WAVE_STARTED = "wave_started"
    WAVE_COMPLETED = "wave_completed"

    # ─────────────────────────────────────────────────────────────────────
    # Workspace
    # ─────────────────────────────────────────────────────────────────────
    WORKSPACE_PATCHED = "workspace_patched"
    STANCE_UPDATED = "stance_updated"
    MODULATORS_UPDATED = "modulators_updated"

    # ─────────────────────────────────────────────────────────────────────
    # Deliberation
    # ─────────────────────────────────────────────────────────────────────
    DELIB_ROUND_STARTED = "delib_round_started"
    DELIB_ROUND_COMPLETED = "delib_round_completed"
    CONSENSUS_UPDATED = "consensus_updated"

    # ─────────────────────────────────────────────────────────────────────
    # Council + Voice
    # ─────────────────────────────────────────────────────────────────────
    COUNCIL_DECISION_MADE = "council_decision_made"
    VOICE_RENDERED = "voice_rendered"

    # ─────────────────────────────────────────────────────────────────────
    # Critics + Safety
    # ─────────────────────────────────────────────────────────────────────
    CRITICS_UPDATED = "critics_updated"
    SAFETY_INTERRUPT = "safety_interrupt"

    # ─────────────────────────────────────────────────────────────────────
    # Memory
    # ─────────────────────────────────────────────────────────────────────
    MEMORY_RETRIEVED = "memory_retrieved"
    MEMORY_CANDIDATES_PROPOSED = "memory_candidates_proposed"
    MEMORY_COMMITTED = "memory_committed"

    # ─────────────────────────────────────────────────────────────────────
    # Observability
    # ─────────────────────────────────────────────────────────────────────
    MODEL_CALL_STARTED = "model_call_started"
    MODEL_CALL_COMPLETED = "model_call_completed"
    TIMING_CHECKPOINT = "timing_checkpoint"

    # ─────────────────────────────────────────────────────────────────────
    # Daemon
    # ─────────────────────────────────────────────────────────────────────
    DAEMON_TICK = "daemon_tick"
    PROACTIVE_NUDGE = "proactive_nudge"
    MODULATORS_DECAYED = "modulators_decayed"

    # ─────────────────────────────────────────────────────────────────────
    # Session
    # ─────────────────────────────────────────────────────────────────────
    SESSION_STARTED = "session_started"
    SESSION_ENDED = "session_ended"

    # ─────────────────────────────────────────────────────────────────────
    # Error
    # ─────────────────────────────────────────────────────────────────────
    ERROR = "error"


class EngineEvent(BaseModel):
    """Immutable event envelope - the atomic unit of the system.

    Every event has:
    - session_id: Which session this belongs to
    - turn_id: Which turn (0 for daemon events)
    - seq: Monotonically increasing within turn
    - ts_monotonic: time.monotonic() for duration calculations
    - ts_wall: Wall clock time for display
    - kind: Event type from EventKind enum
    - payload: Typed data specific to event kind
    - schema_version: For forward compatibility

    Events are immutable once created (frozen=True).
    Events are ordered by (session_id, turn_id, seq).
    """

    session_id: str = Field(description="Session identifier (UUID)")
    turn_id: int = Field(ge=0, description="Turn number (0 for daemon events)")
    seq: int = Field(ge=0, description="Sequence number within turn")
    ts_monotonic: float = Field(description="time.monotonic() timestamp")
    ts_wall: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Wall clock timestamp"
    )
    kind: EventKind = Field(description="Event type")
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Event-specific data"
    )
    schema_version: int = Field(default=1, description="Schema version for migrations")

    model_config = {"frozen": True}


# ─────────────────────────────────────────────────────────────────────────────
# Payload Type Hints (for documentation, not runtime enforcement)
# ─────────────────────────────────────────────────────────────────────────────

"""
Payload schemas by event kind:

TURN_STARTED:
    user_input: str
    turn_id: int

TURN_STAGE_CHANGED:
    stage: str  # "ingest", "sensing_fast", "context", "agents", "deliberation", "council", "critics", "memory_commit"

TURN_COMPLETED:
    total_time_ms: int
    response: str | None

SENSORS_FAST_UPDATED:
    sensors: dict[str, float]  # sensor_name -> probability

AGENT_STARTED:
    agent_id: str

AGENT_COMPLETED:
    agent_id: str
    observation: str
    salience: float
    urgency: int
    confidence: int
    claims: list[dict]
    stance_delta: dict[str, float] | None
    processing_time_ms: int

AGENT_FAILED:
    agent_id: str
    error: str

WORKSPACE_PATCHED:
    patch: dict[str, Any]

STANCE_UPDATED:
    delta: dict[str, float]
    current: dict[str, float]

DELIB_ROUND_STARTED:
    round: int

DELIB_ROUND_COMPLETED:
    round: int
    consensus: float
    active_claims: int

CONSENSUS_UPDATED:
    level: float
    by_type: dict[str, float]  # claim_type -> consensus

COUNCIL_DECISION_MADE:
    speak: bool
    urgency: str
    intent: str
    key_points: list[str]
    thinking: str | None

VOICE_RENDERED:
    text: str

CRITICS_UPDATED:
    results: list[dict]  # [{critic: str, passed: bool, reason: str}]

SAFETY_INTERRUPT:
    reason: str
    sensor: str | None
    value: float | None

MEMORY_RETRIEVED:
    episodes: list[dict]
    user_facts: list[dict]
    open_threads: list[dict]

MEMORY_COMMITTED:
    summary: dict

MODEL_CALL_COMPLETED:
    model: str
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int | None
    latency_ms: int

DAEMON_TICK:
    timestamp: float

PROACTIVE_NUDGE:
    reason: str
    suggestion: str
    context: dict

ERROR:
    error: str
    traceback: str | None
"""
