"""
Stance Vector - Persistent Affective Control State

This is NOT a claim of human emotion. It is an internal modulation state
that influences response generation through mathematically defined dynamics.

Based on PAD (Pleasure-Arousal-Dominance) model extended with cognitive-social
modulators for AI companionship contexts.
"""

from dataclasses import dataclass, field
from typing import Optional
import time


def clamp(value: float, min_val: float, max_val: float) -> float:
    """Clamp value to range [min_val, max_val]."""
    return max(min_val, min(max_val, value))


def clamp01(value: float) -> float:
    """Clamp value to range [0, 1]."""
    return clamp(value, 0.0, 1.0)


@dataclass
class StanceVector:
    """
    Persistent affective control state - NOT a claim of human emotion.

    This vector influences response generation through derived quantities
    like readiness_to_speak, advice_suppression, and exploration_bias.

    Dimensions:
        valence: [-1, 1] unpleasant to pleasant
        arousal: [0, 1] calm to activated
        control: [0, 1] helpless to dominant (THE MISSING AXIS in most models)
        certainty: [0, 1] confused to clear
        safety: [0, 1] threatened to secure
        closeness: [0, 1] distant to connected
        curiosity: [0, 1] saturated to wondering
        strain: [0, 1] ease to overload
    """

    # Core affective dimensions (PAD model + extensions)
    valence: float = 0.0      # [-1, 1] unpleasant to pleasant
    arousal: float = 0.3      # [0, 1] calm to activated
    control: float = 0.7      # [0, 1] helpless to dominant

    # Cognitive-social modulators
    certainty: float = 0.5    # [0, 1] confused to clear
    safety: float = 0.8       # [0, 1] threatened to secure
    closeness: float = 0.3    # [0, 1] distant to connected
    curiosity: float = 0.5    # [0, 1] saturated to wondering
    strain: float = 0.1       # [0, 1] ease to overload

    # Bookkeeping
    turn_id: int = 0
    last_update_ts: float = field(default_factory=time.time)

    # Style notes from last update (max 6 short items)
    notes: list[str] = field(default_factory=list)

    def __post_init__(self):
        """Ensure all values are within bounds."""
        self.valence = clamp(self.valence, -1.0, 1.0)
        self.arousal = clamp01(self.arousal)
        self.control = clamp01(self.control)
        self.certainty = clamp01(self.certainty)
        self.safety = clamp01(self.safety)
        self.closeness = clamp01(self.closeness)
        self.curiosity = clamp01(self.curiosity)
        self.strain = clamp01(self.strain)

    @property
    def readiness_to_speak(self) -> float:
        """
        Derived quantity: How ready the system is to generate a response.
        High curiosity + closeness + control increases readiness.
        High strain + low safety decreases readiness.
        """
        return clamp01(
            0.35 * self.curiosity +
            0.25 * self.closeness +
            0.20 * self.control +
            0.10 * self.arousal +
            0.10 * (self.valence + 1) / 2 -  # Normalize valence to [0,1]
            0.45 * self.strain -
            0.25 * (1 - self.safety)
        )

    @property
    def advice_suppression(self) -> float:
        """
        Derived quantity: How much to suppress unsolicited advice.
        High closeness + low safety + high arousal = more suppression.
        (User is vulnerable, don't jump to solutions)
        """
        return clamp01(
            0.6 * self.closeness +
            0.3 * (1 - self.safety) +
            0.2 * self.arousal
        )

    @property
    def exploration_bias(self) -> float:
        """
        Derived quantity: How much to explore vs exploit.
        High curiosity + uncertainty + arousal = more exploration.
        """
        return clamp01(
            0.6 * self.curiosity +
            0.2 * (1 - self.certainty) +
            0.2 * self.arousal
        )

    @property
    def warmth_level(self) -> float:
        """
        Derived quantity: How warm/connected the response tone should be.
        """
        return clamp01(
            0.5 * self.closeness +
            0.3 * (self.valence + 1) / 2 +
            0.2 * self.safety
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "valence": self.valence,
            "arousal": self.arousal,
            "control": self.control,
            "certainty": self.certainty,
            "safety": self.safety,
            "closeness": self.closeness,
            "curiosity": self.curiosity,
            "strain": self.strain,
            "turn_id": self.turn_id,
            "last_update_ts": self.last_update_ts,
            "notes": self.notes,
            # Derived quantities
            "readiness_to_speak": self.readiness_to_speak,
            "advice_suppression": self.advice_suppression,
            "exploration_bias": self.exploration_bias,
            "warmth_level": self.warmth_level,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "StanceVector":
        """Create from dictionary."""
        return cls(
            valence=data.get("valence", 0.0),
            arousal=data.get("arousal", 0.3),
            control=data.get("control", 0.7),
            certainty=data.get("certainty", 0.5),
            safety=data.get("safety", 0.8),
            closeness=data.get("closeness", 0.3),
            curiosity=data.get("curiosity", 0.5),
            strain=data.get("strain", 0.1),
            turn_id=data.get("turn_id", 0),
            last_update_ts=data.get("last_update_ts", time.time()),
            notes=data.get("notes", []),
        )


# Maximum delta per dimension per turn (prevents thrashing)
MAX_DELTA = 0.15


def update_stance(
    prev: StanceVector,
    delta: dict[str, float],
    turn_id: int,
    alpha: float = 0.25,
    notes: Optional[list[str]] = None,
) -> StanceVector:
    """
    Update stance vector using leaky integrator dynamics.

    Args:
        prev: Previous stance vector
        delta: Dictionary of dimension deltas (e.g., {"curiosity": 0.1, "safety": -0.05})
        turn_id: Current turn ID
        alpha: Blending factor (0 = no change, 1 = full delta)
        notes: Optional style notes for this update

    Returns:
        New StanceVector with bounded updates

    The update formula is:
        new_value = prev_value + clamp(delta * alpha, -MAX_DELTA, MAX_DELTA)
    """
    new_values = {}

    for dim in ["valence", "arousal", "control", "certainty", "safety", "closeness", "curiosity", "strain"]:
        prev_val = getattr(prev, dim)
        raw_delta = delta.get(dim, 0.0) * alpha
        clamped_delta = clamp(raw_delta, -MAX_DELTA, MAX_DELTA)

        if dim == "valence":
            new_values[dim] = clamp(prev_val + clamped_delta, -1.0, 1.0)
        else:
            new_values[dim] = clamp01(prev_val + clamped_delta)

    return StanceVector(
        **new_values,
        turn_id=turn_id,
        last_update_ts=time.time(),
        notes=notes[:6] if notes else [],
    )


def stance_distance(a: StanceVector, b: StanceVector) -> float:
    """
    Calculate Euclidean distance between two stance vectors.
    Useful for detecting sudden shifts that might indicate issues.
    """
    dims = ["valence", "arousal", "control", "certainty", "safety", "closeness", "curiosity", "strain"]
    sum_sq = sum((getattr(a, d) - getattr(b, d)) ** 2 for d in dims)
    return sum_sq ** 0.5


def create_default_stance() -> StanceVector:
    """Create a neutral default stance vector."""
    return StanceVector()
