"""Workspace contracts - global state and modulators."""

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
            object.__setattr__(self, name, new_value)
        object.__setattr__(self, "last_update", datetime.now())
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
