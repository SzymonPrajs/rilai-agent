"""Modulator decay logic."""

from dataclasses import dataclass
from typing import Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from rilai.runtime.workspace import Workspace


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
