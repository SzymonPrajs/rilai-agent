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
