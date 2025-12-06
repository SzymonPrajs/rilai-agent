"""Global modulators and agent activation state for the scheduler.

Modulators are system-wide affective signals that influence routing decisions.
Activation state tracks per-agent firing history for cooldown and salience calculation.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class GlobalModulators:
    """System-wide affective state inferred from specific agents.

    These modulators influence which agencies/agents are activated.
    Values are normalized to [0.0, 1.0].
    """

    arousal: float = 0.3  # 0.0 (calm) to 1.0 (activated)
    fatigue: float = 0.0  # 0.0 (rested) to 1.0 (exhausted)
    time_pressure: float = 0.0  # 0.0 (relaxed) to 1.0 (urgent)
    social_risk: float = 0.0  # 0.0 (safe) to 1.0 (high stakes)

    # Source tracking for debugging
    last_update: datetime = field(default_factory=datetime.now)
    source_agents: dict[str, str] = field(default_factory=dict)  # modulator -> agent_id

    def decay(self, factor: float = 0.9) -> None:
        """Decay all modulator values toward baseline."""
        self.arousal = max(0.0, min(1.0, self.arousal * factor))
        self.fatigue = max(0.0, min(1.0, self.fatigue * factor))
        self.time_pressure = max(0.0, min(1.0, self.time_pressure * factor))
        self.social_risk = max(0.0, min(1.0, self.social_risk * factor))

    def update(self, modulator: str, delta: float, source_agent: str) -> None:
        """Update a specific modulator with bounds checking."""
        current = getattr(self, modulator, None)
        if current is not None:
            new_value = max(0.0, min(1.0, current + delta))
            setattr(self, modulator, new_value)
            self.source_agents[modulator] = source_agent
            self.last_update = datetime.now()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "arousal": self.arousal,
            "fatigue": self.fatigue,
            "time_pressure": self.time_pressure,
            "social_risk": self.social_risk,
            "last_update": self.last_update.isoformat(),
        }

    def to_prompt_section(self) -> str:
        """Format modulators for inclusion in agent prompts."""
        return (
            f"Arousal: {self.arousal:.2f} (0=calm, 1=activated)\n"
            f"Fatigue: {self.fatigue:.2f} (0=rested, 1=exhausted)\n"
            f"Time pressure: {self.time_pressure:.2f} (0=relaxed, 1=urgent)\n"
            f"Social risk: {self.social_risk:.2f} (0=safe, 1=high stakes)"
        )


@dataclass
class AgentActivationState:
    """Per-agent activation memory for scheduling.

    Tracks firing history, cooldowns, and rolling salience for each agent.
    Used to calculate final salience scores and prevent agent fatigue.
    """

    agent_id: str
    last_fired: datetime | None = None
    cooldown_until: datetime | None = None
    rolling_salience: float = 0.0  # Exponential moving average
    fire_count: int = 0

    # Archetype weight (interrupt agents get higher)
    archetype_weight: float = 1.0

    def mark_fired(self, cooldown_seconds: float = 30.0) -> None:
        """Mark this agent as having fired."""
        now = datetime.now()
        self.last_fired = now
        self.fire_count += 1
        if cooldown_seconds > 0:
            self.cooldown_until = datetime.fromtimestamp(
                now.timestamp() + cooldown_seconds
            )

    def is_on_cooldown(self) -> bool:
        """Check if agent is currently on cooldown."""
        if self.cooldown_until is None:
            return False
        return datetime.now() < self.cooldown_until

    def get_cooldown_penalty(self) -> float:
        """Get cooldown penalty (0.0 to 0.5)."""
        if not self.is_on_cooldown():
            return 0.0
        remaining = (self.cooldown_until - datetime.now()).total_seconds()
        # Max 0.5 penalty over 30 seconds
        return min(0.5, remaining / 60.0)

    def get_recency_boost(self) -> float:
        """Get recency boost (encourages turn-taking)."""
        if self.last_fired is None:
            return 1.2  # Never fired, give boost
        seconds_since = (datetime.now() - self.last_fired).total_seconds()
        if seconds_since > 300:  # 5 minutes
            return 1.2
        return 1.0

    def update_rolling_salience(self, new_score: float, alpha: float = 0.3) -> None:
        """Update rolling salience with exponential moving average."""
        self.rolling_salience = alpha * new_score + (1 - alpha) * self.rolling_salience


# Agent archetype weights - interrupt-capable agents get higher weight
ARCHETYPE_WEIGHTS: dict[str, float] = {
    # Interrupt-capable agents (priority flag)
    "censor": 1.5,
    "exception_handler": 1.5,
    "trigger_watcher": 1.3,
    "anomaly_detector": 1.3,
    # Default weight for most agents
    "default": 1.0,
    # Potentially verbose agents (slightly lower)
    "brainstormer": 0.9,
    "researcher": 0.9,
}


def get_archetype_weight(agent_name: str) -> float:
    """Get archetype weight for an agent by name."""
    return ARCHETYPE_WEIGHTS.get(agent_name, ARCHETYPE_WEIGHTS["default"])


# Modulator inference mapping: agent_id -> (modulator, weight, is_inverse)
MODULATOR_MAP: dict[str, tuple[str, float, bool]] = {
    "emotion.stress": ("arousal", 0.3, False),
    "monitoring.trigger_watcher": ("arousal", 0.2, False),
    "emotion.wellbeing": ("fatigue", 0.3, True),  # Inverse: high wellbeing = low fatigue
    "resource.energy": ("fatigue", 0.2, False),
    "resource.time": ("time_pressure", 0.3, False),
    "planning.short_term": ("time_pressure", 0.2, False),
    "social.norms": ("social_risk", 0.3, False),
    "social.relationships": ("social_risk", 0.2, False),
    "inhibition.censor": ("social_risk", 0.2, False),
}
