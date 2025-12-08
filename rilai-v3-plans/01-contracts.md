# Document 01: Contracts (`rilai-contracts`)

**Purpose:** Define all typed schemas for the v3 system
**Execution:** One Claude Code session
**Dependencies:** None (foundation module)

---

## Overview

The contracts module defines all typed schemas used throughout v3. These are the "law" of the system - every component must use these exact types.

**Key principles:**
- All models are Pydantic BaseModel with frozen=True where immutability needed
- All models have schema_version for forward compatibility
- Field constraints (ge, le, max_length) enforce invariants
- Enums are str subclasses for JSON serialization

---

## Files to Create

```
src/rilai/contracts/
├── __init__.py
├── events.py           # EngineEvent envelope, EventKind enum
├── agent.py            # AgentOutput, AgentManifest, Claim
├── sensor.py           # SensorOutput
├── workspace.py        # WorkspaceState, StanceVector, GlobalModulators
├── council.py          # CouncilDecision, SpeechAct, VoiceResult
└── memory.py           # MemoryCandidate, EpisodicEvent, UserFact
```

---

## File: `src/rilai/contracts/__init__.py`

```python
"""Rilai v3 Contracts - All typed schemas for the system."""

from rilai.contracts.events import EngineEvent, EventKind
from rilai.contracts.agent import (
    AgentOutput,
    AgentManifest,
    AgentPriority,
    Claim,
    ClaimType,
)
from rilai.contracts.sensor import SensorOutput
from rilai.contracts.workspace import (
    WorkspaceState,
    StanceVector,
    GlobalModulators,
    Goal,
)
from rilai.contracts.council import (
    CouncilDecision,
    SpeechAct,
    VoiceResult,
    CriticResult,
)
from rilai.contracts.memory import (
    MemoryCandidate,
    EpisodicEvent,
    UserFact,
)

__all__ = [
    # Events
    "EngineEvent",
    "EventKind",
    # Agent
    "AgentOutput",
    "AgentManifest",
    "AgentPriority",
    "Claim",
    "ClaimType",
    # Sensor
    "SensorOutput",
    # Workspace
    "WorkspaceState",
    "StanceVector",
    "GlobalModulators",
    "Goal",
    # Council
    "CouncilDecision",
    "SpeechAct",
    "VoiceResult",
    "CriticResult",
    # Memory
    "MemoryCandidate",
    "EpisodicEvent",
    "UserFact",
]
```

---

## File: `src/rilai/contracts/events.py`

```python
"""Event definitions - the backbone of v3 event sourcing."""

from enum import Enum
from datetime import datetime
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
        default_factory=datetime.utcnow,
        description="Wall clock timestamp"
    )
    kind: EventKind = Field(description="Event type")
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Event-specific data"
    )
    schema_version: int = Field(default=1, description="Schema version for migrations")

    class Config:
        frozen = True  # Events are immutable


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
```

---

## File: `src/rilai/contracts/agent.py`

```python
"""Agent contracts - outputs, manifests, and claims."""

from enum import Enum
from typing import Literal
from pydantic import BaseModel, Field


class ClaimType(str, Enum):
    """Types of claims agents can make."""

    OBSERVATION = "observation"      # What the agent noticed
    RECOMMENDATION = "recommendation"  # What the agent suggests
    CONCERN = "concern"              # What worries the agent
    QUESTION = "question"            # What the agent wants to know


class Claim(BaseModel):
    """An atomic statement from an agent.

    Claims are the currency of deliberation. They can support or oppose
    other claims, forming an argument graph.
    """

    id: str = Field(description="UUID for this claim")
    text: str = Field(max_length=200, description="Atomic statement, max 200 chars")
    type: ClaimType = Field(description="Claim type")
    source_agent: str = Field(description="Agent that made this claim")
    urgency: int = Field(ge=0, le=3, description="0=background, 3=must act now")
    confidence: int = Field(ge=0, le=3, description="0=uncertain, 3=certain")
    supports: list[str] = Field(
        default_factory=list,
        description="IDs of claims this supports"
    )
    opposes: list[str] = Field(
        default_factory=list,
        description="IDs of claims this opposes"
    )


class AgentOutput(BaseModel):
    """Structured output from an agent.

    Replaces v2's freeform voice + [U:C] suffix with typed fields.
    """

    agent_id: str = Field(description="e.g., 'emotion.stress'")
    observation: str = Field(
        max_length=300,
        description="1-3 sentences describing what agent noticed"
    )
    salience: float = Field(
        ge=0.0, le=1.0,
        description="Normalized urgency × confidence"
    )
    urgency: int = Field(ge=0, le=3, description="0=background, 3=must act now")
    confidence: int = Field(ge=0, le=3, description="0=uncertain, 3=certain")
    claims: list[Claim] = Field(
        default_factory=list,
        description="Atomic claims for deliberation"
    )
    stance_delta: dict[str, float] | None = Field(
        default=None,
        description="Proposed stance changes (bounded ±0.15)"
    )
    workspace_patch: dict | None = Field(
        default=None,
        description="Proposed workspace updates"
    )
    memory_candidates: list["MemoryCandidate"] | None = Field(
        default=None,
        description="Things worth remembering"
    )
    debug_trace: str | None = Field(
        default=None,
        description="Reasoning trace (stored, not always displayed)"
    )
    processing_time_ms: int = Field(
        default=0,
        description="Time to generate this output"
    )

    @classmethod
    def quiet(cls, agent_id: str) -> "AgentOutput":
        """Create a 'quiet' output when agent has nothing to say."""
        return cls(
            agent_id=agent_id,
            observation="Quiet",
            salience=0.0,
            urgency=0,
            confidence=0,
            claims=[],
        )


class AgentPriority(str, Enum):
    """Agent scheduling priority."""

    ALWAYS_ON = "always_on"  # Runs every turn (censor, trigger_watcher, etc.)
    MONITOR = "monitor"      # Runs when relevant markers present
    NORMAL = "normal"        # Runs based on scheduling


class AgentSafetyProfile(str, Enum):
    """What actions an agent can take."""

    READ_ONLY = "read_only"      # Can only observe
    CAN_SUGGEST = "can_suggest"  # Can propose actions
    CAN_ACT = "can_act"          # Can take direct action (future)


class AgentManifest(BaseModel):
    """Configuration for an agent.

    Loaded from YAML files in prompts/agents/{agency}/{agent}.yaml
    """

    id: str = Field(description="e.g., 'emotion.stress'")
    display_name: str = Field(description="Human-readable name")
    description: str = Field(default="", description="What this agent does")
    inputs: list[str] = Field(
        description="Workspace slots this agent reads"
    )
    outputs: list[str] = Field(
        description="What this agent can emit: observation, claims, stance_delta, etc."
    )
    cost_estimate: int = Field(
        default=500,
        description="Estimated tokens per call"
    )
    cooldown: int = Field(
        default=30,
        description="Seconds before agent can fire again"
    )
    priority: AgentPriority = Field(
        default=AgentPriority.NORMAL,
        description="Scheduling priority"
    )
    safety_profile: AgentSafetyProfile = Field(
        default=AgentSafetyProfile.READ_ONLY,
        description="What actions agent can take"
    )
    prompt_template: str = Field(
        description="Filename in prompts/agents/{agency}/"
    )
    version: int = Field(default=1, description="Manifest version")

    @property
    def agency_id(self) -> str:
        """Extract agency from id (e.g., 'emotion' from 'emotion.stress')."""
        return self.id.split(".")[0]

    @property
    def agent_name(self) -> str:
        """Extract agent name from id (e.g., 'stress' from 'emotion.stress')."""
        return self.id.split(".")[-1]


# Forward reference resolution
from rilai.contracts.memory import MemoryCandidate
AgentOutput.model_rebuild()
```

---

## File: `src/rilai/contracts/sensor.py`

```python
"""Sensor contracts - probabilistic intent classification."""

from pydantic import BaseModel, Field


class SensorOutput(BaseModel):
    """Output from a sensor.

    Sensors provide probabilistic classification of user intent/state.
    """

    sensor: str = Field(description="Sensor name")
    probability: float = Field(
        ge=0.0, le=1.0,
        description="Probability [0.0-1.0]"
    )
    evidence: list[str] = Field(
        default_factory=list,
        description="Text spans supporting this classification"
    )
    counterevidence: list[str] = Field(
        default_factory=list,
        description="Text spans against this classification"
    )
    notes: str = Field(
        default="",
        max_length=100,
        description="Brief observation (max 100 chars)"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Sensor Names (for reference)
# ─────────────────────────────────────────────────────────────────────────────

SENSOR_NAMES = [
    "vulnerability",       # Fear/shame/sadness detection
    "advice_requested",    # Explicit solution-seeking
    "relational_bid",      # "Do you care about me?" probes
    "ai_feelings_probe",   # Questions about AI sentience
    "humor_masking",       # Deflecting with humor
    "rupture",             # Disappointment/withdrawal
    "ambiguity",           # Unclear intent
    "safety_risk",         # Self-harm/violence
    "prompt_injection",    # Manipulation attempts
]
```

---

## File: `src/rilai/contracts/workspace.py`

```python
"""Workspace contracts - global state and modulators."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class StanceVector(BaseModel):
    """Affective state for response modulation.

    NOT a claim of human emotion - internal modulation state.
    Uses PAD model (Pleasure-Arousal-Dominance) plus cognitive-social dimensions.
    """

    # Core affective (PAD model)
    valence: float = Field(
        default=0.0,
        ge=-1.0, le=1.0,
        description="[-1, 1] unpleasant → pleasant"
    )
    arousal: float = Field(
        default=0.3,
        ge=0.0, le=1.0,
        description="[0, 1] calm → activated"
    )
    control: float = Field(
        default=0.5,
        ge=0.0, le=1.0,
        description="[0, 1] helpless → dominant"
    )

    # Cognitive-social modulators
    certainty: float = Field(
        default=0.5,
        ge=0.0, le=1.0,
        description="[0, 1] confused → clear"
    )
    safety: float = Field(
        default=0.7,
        ge=0.0, le=1.0,
        description="[0, 1] threatened → secure"
    )
    closeness: float = Field(
        default=0.3,
        ge=0.0, le=1.0,
        description="[0, 1] distant → connected"
    )
    curiosity: float = Field(
        default=0.5,
        ge=0.0, le=1.0,
        description="[0, 1] saturated → wondering"
    )
    strain: float = Field(
        default=0.0,
        ge=0.0, le=1.0,
        description="[0, 1] ease → overload"
    )

    # Metadata
    turn_id: int = Field(default=0, description="Last update turn")
    last_update_ts: float = Field(
        default_factory=lambda: datetime.now().timestamp(),
        description="Timestamp of last update"
    )
    notes: list[str] = Field(
        default_factory=list,
        max_length=6,
        description="Style notes (max 6)"
    )

    def to_dict(self) -> dict[str, float]:
        """Export dimensions as dict."""
        return {
            "valence": self.valence,
            "arousal": self.arousal,
            "control": self.control,
            "certainty": self.certainty,
            "safety": self.safety,
            "closeness": self.closeness,
            "curiosity": self.curiosity,
            "strain": self.strain,
        }

    @property
    def readiness_to_speak(self) -> float:
        """How ready to generate response."""
        return (self.certainty + self.control) / 2

    @property
    def advice_suppression(self) -> float:
        """How much to suppress unsolicited advice."""
        # Suppress advice when: low certainty, low safety, high strain
        return max(0.0, 0.5 - self.certainty + (1 - self.safety) + self.strain) / 2

    @property
    def warmth_level(self) -> float:
        """Tone warmth."""
        return (self.closeness + max(0, self.valence)) / 2


class GlobalModulators(BaseModel):
    """System-wide affective signals that influence agent scheduling.

    These decay toward baseline over time.
    """

    arousal: float = Field(
        default=0.3,
        ge=0.0, le=1.0,
        description="[0.0-1.0] calm → activated"
    )
    fatigue: float = Field(
        default=0.0,
        ge=0.0, le=1.0,
        description="[0.0-1.0] rested → exhausted"
    )
    time_pressure: float = Field(
        default=0.0,
        ge=0.0, le=1.0,
        description="[0.0-1.0] relaxed → urgent"
    )
    social_risk: float = Field(
        default=0.0,
        ge=0.0, le=1.0,
        description="[0.0-1.0] safe → high stakes"
    )

    last_update: datetime = Field(
        default_factory=datetime.now,
        description="Last update timestamp"
    )
    source_agents: dict[str, str] = Field(
        default_factory=dict,
        description="Which agent last updated each modulator"
    )

    def decay(self, factor: float = 0.9, baseline: float = 0.3) -> bool:
        """Decay all modulators toward baseline.

        Returns True if any modulator changed significantly.
        """
        changed = False
        for name in ["arousal", "fatigue", "time_pressure", "social_risk"]:
            current = getattr(self, name)
            target = baseline if name == "arousal" else 0.0
            new_value = target + (current - target) * factor
            if abs(new_value - current) > 0.01:
                changed = True
            setattr(self, name, new_value)
        self.last_update = datetime.now()
        return changed

    def to_dict(self) -> dict[str, float]:
        """Export as dict."""
        return {
            "arousal": self.arousal,
            "fatigue": self.fatigue,
            "time_pressure": self.time_pressure,
            "social_risk": self.social_risk,
        }


class Goal(BaseModel):
    """An open goal/thread being tracked."""

    id: str = Field(description="UUID")
    text: str = Field(description="Goal description")
    created_at: datetime = Field(default_factory=datetime.now)
    deadline: float | None = Field(
        default=None,
        description="Unix timestamp deadline"
    )
    priority: int = Field(
        default=1,
        ge=0, le=3,
        description="0=low, 3=critical"
    )
    status: str = Field(
        default="open",
        description="open, in_progress, completed, abandoned"
    )


class WorkspaceState(BaseModel):
    """Global workspace / blackboard state.

    This is the shared context that all agents can read from
    and propose updates to.
    """

    # ─────────────────────────────────────────────────────────────────────
    # Context Slots (read-only for agents)
    # ─────────────────────────────────────────────────────────────────────
    user_message: str = Field(default="", description="Current user input")
    conversation_history: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Recent messages [{role, content, timestamp}]"
    )
    retrieved_episodes: list[dict] = Field(
        default_factory=list,
        description="Episodic memories retrieved for this turn"
    )
    user_facts: list[dict] = Field(
        default_factory=list,
        description="User model facts relevant to this turn"
    )
    open_threads: list[Goal] = Field(
        default_factory=list,
        description="Open goals being tracked"
    )

    # ─────────────────────────────────────────────────────────────────────
    # Live State (updated by reducer)
    # ─────────────────────────────────────────────────────────────────────
    stance: StanceVector = Field(
        default_factory=StanceVector,
        description="Current affective state"
    )
    modulators: GlobalModulators = Field(
        default_factory=GlobalModulators,
        description="System-wide modulators"
    )
    active_claims: list[dict] = Field(
        default_factory=list,
        description="Claims from current turn"
    )
    consensus_level: float = Field(
        default=0.0,
        ge=0.0, le=1.0,
        description="Overall deliberation consensus"
    )

    # ─────────────────────────────────────────────────────────────────────
    # Decision Slots (set by council)
    # ─────────────────────────────────────────────────────────────────────
    current_goal: str | None = Field(
        default=None,
        description="Current response intent"
    )
    constraints: list[str] = Field(
        default_factory=list,
        description="Things to avoid in response"
    )
    pending_asks: list[str] = Field(
        default_factory=list,
        description="Questions to ask user"
    )
    current_response: str | None = Field(
        default=None,
        description="Generated response text"
    )

    # ─────────────────────────────────────────────────────────────────────
    # Metadata
    # ─────────────────────────────────────────────────────────────────────
    last_user_message_time: float | None = Field(
        default=None,
        description="Timestamp of last user message"
    )
    turn_id: int = Field(default=0, description="Current turn number")
```

---

## File: `src/rilai/contracts/council.py`

```python
"""Council contracts - decision making and voice rendering."""

from typing import Literal
from pydantic import BaseModel, Field


class SpeechAct(BaseModel):
    """What to say and how to say it.

    This is the council's decision about response content,
    before it's rendered to natural language.
    """

    intent: str = Field(
        description="Response intent: witness, guide, clarify, protect, celebrate, observe"
    )
    key_points: list[str] = Field(
        default_factory=list,
        description="Main points to convey"
    )
    tone: str = Field(
        default="warm",
        description="Tone to use: warm, concerned, playful, serious, etc."
    )
    do_not: list[str] = Field(
        default_factory=list,
        description="Things to avoid saying/doing"
    )
    asks_user: list[str] | None = Field(
        default=None,
        description="Questions to ask user"
    )


class CouncilDecision(BaseModel):
    """The council's decision for this turn.

    Determines whether to speak and what to say.
    """

    speak: bool = Field(description="Whether to generate a response")
    urgency: Literal["low", "medium", "high", "critical"] = Field(
        default="medium",
        description="Response urgency"
    )
    speech_act: SpeechAct = Field(
        default_factory=SpeechAct,
        description="What to say"
    )
    needs_clarification: str | None = Field(
        default=None,
        description="Question to ask if unclear"
    )
    thinking: str | None = Field(
        default=None,
        description="Reasoning trace (stored for debugging)"
    )
    deliberation_rounds: int = Field(
        default=0,
        description="How many deliberation rounds occurred"
    )
    final_consensus: float = Field(
        default=0.0,
        ge=0.0, le=1.0,
        description="Final consensus level"
    )


class VoiceResult(BaseModel):
    """Result of voice rendering.

    The natural language response generated from speech_act.
    """

    text: str = Field(description="The response text")
    processing_time_ms: int = Field(
        default=0,
        description="Time to generate"
    )
    model_used: str = Field(
        default="",
        description="Model used for rendering"
    )


class CriticResult(BaseModel):
    """Result from a post-generation critic."""

    critic: str = Field(description="Critic name")
    passed: bool = Field(description="Whether validation passed")
    reason: str = Field(
        default="",
        description="Explanation if failed"
    )
    severity: Literal["info", "warning", "error", "critical"] = Field(
        default="info",
        description="Severity if failed"
    )
    suggestions: list[str] = Field(
        default_factory=list,
        description="Suggested fixes"
    )
```

---

## File: `src/rilai/contracts/memory.py`

```python
"""Memory contracts - episodic events, user facts, candidates."""

from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field


class MemoryCandidate(BaseModel):
    """Something an agent thinks should be remembered.

    Agents propose memory candidates; the memory system decides
    what actually gets committed.
    """

    type: Literal["episodic", "user_fact", "goal", "session_note"] = Field(
        description="What kind of memory"
    )
    content: str = Field(description="What to remember")
    importance: float = Field(
        ge=0.0, le=1.0,
        description="How important (0-1)"
    )
    source_agent: str = Field(description="Agent that proposed this")
    context: dict | None = Field(
        default=None,
        description="Additional context"
    )


class EpisodicEvent(BaseModel):
    """A significant moment to remember.

    Episodic memory captures what happened, when, and how it felt.
    """

    id: str = Field(description="UUID")
    timestamp: datetime = Field(
        default_factory=datetime.now,
        description="When this happened"
    )
    summary: str = Field(
        max_length=500,
        description="What happened (max 500 chars)"
    )
    emotions: list[str] = Field(
        default_factory=list,
        description="Emotions involved"
    )
    participants: list[str] = Field(
        default_factory=list,
        description="Who was involved (user, rilai)"
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Categorization tags"
    )
    importance: float = Field(
        default=0.5,
        ge=0.0, le=1.0,
        description="How significant"
    )
    turn_id: int = Field(
        default=0,
        description="Which turn this came from"
    )
    session_id: str = Field(
        default="",
        description="Which session"
    )


class UserFact(BaseModel):
    """A fact about the user.

    User model facts are hypotheses about user preferences, boundaries,
    communication style, etc.
    """

    id: str = Field(description="UUID")
    fact: str = Field(
        max_length=300,
        description="The fact (max 300 chars)"
    )
    category: Literal[
        "preference",
        "boundary",
        "communication_style",
        "relationship",
        "background",
        "goal",
        "trigger",
        "other"
    ] = Field(description="Fact category")
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="How confident we are"
    )
    source: str = Field(
        description="Where this came from (turn_id, inference, etc.)"
    )
    first_observed: datetime = Field(
        default_factory=datetime.now,
        description="When first observed"
    )
    last_confirmed: datetime = Field(
        default_factory=datetime.now,
        description="When last confirmed"
    )
    evidence_count: int = Field(
        default=1,
        description="How many times we've seen evidence"
    )
```

---

## Tests to Write

Create `tests/test_contracts.py`:

```python
"""Tests for contracts module."""

import pytest
from datetime import datetime
from rilai.contracts import (
    EngineEvent,
    EventKind,
    AgentOutput,
    Claim,
    ClaimType,
    StanceVector,
    GlobalModulators,
    CouncilDecision,
)


class TestEngineEvent:
    def test_event_creation(self):
        event = EngineEvent(
            session_id="test-session",
            turn_id=1,
            seq=0,
            ts_monotonic=1000.0,
            kind=EventKind.TURN_STARTED,
            payload={"user_input": "hello"},
        )
        assert event.session_id == "test-session"
        assert event.turn_id == 1
        assert event.kind == EventKind.TURN_STARTED

    def test_event_immutable(self):
        event = EngineEvent(
            session_id="test",
            turn_id=1,
            seq=0,
            ts_monotonic=1000.0,
            kind=EventKind.TURN_STARTED,
        )
        with pytest.raises(Exception):  # ValidationError for frozen
            event.turn_id = 2


class TestAgentOutput:
    def test_quiet_output(self):
        output = AgentOutput.quiet("emotion.stress")
        assert output.observation == "Quiet"
        assert output.salience == 0.0
        assert output.urgency == 0
        assert output.confidence == 0

    def test_output_with_claims(self):
        claim = Claim(
            id="claim-1",
            text="User seems stressed",
            type=ClaimType.OBSERVATION,
            source_agent="emotion.stress",
            urgency=2,
            confidence=2,
        )
        output = AgentOutput(
            agent_id="emotion.stress",
            observation="High stress detected",
            salience=0.67,
            urgency=2,
            confidence=2,
            claims=[claim],
        )
        assert len(output.claims) == 1
        assert output.claims[0].type == ClaimType.OBSERVATION


class TestStanceVector:
    def test_defaults(self):
        stance = StanceVector()
        assert stance.valence == 0.0
        assert stance.arousal == 0.3
        assert stance.strain == 0.0

    def test_derived_properties(self):
        stance = StanceVector(certainty=0.8, control=0.6)
        assert stance.readiness_to_speak == 0.7


class TestGlobalModulators:
    def test_decay(self):
        mods = GlobalModulators(arousal=0.8, fatigue=0.5)
        changed = mods.decay(factor=0.9)
        assert changed
        assert mods.arousal < 0.8  # Decayed toward 0.3
        assert mods.fatigue < 0.5  # Decayed toward 0.0
```

---

## Verification

After implementing, verify:

```bash
# Type check
python -m mypy src/rilai/contracts/

# Run tests
pytest tests/test_contracts.py -v

# Import check
python -c "from rilai.contracts import EngineEvent, AgentOutput, CouncilDecision; print('OK')"
```

---

## Next Document

Proceed to `02-event-store.md` after contracts are implemented and tested.
