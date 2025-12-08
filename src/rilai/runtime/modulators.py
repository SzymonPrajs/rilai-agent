"""GlobalModulators management."""

from datetime import datetime

from rilai.contracts.workspace import GlobalModulators


# Mapping from agent_id to (modulator, weight, is_inverse)
MODULATOR_MAP = {
    "emotion.stress": ("arousal", 0.3, False),
    "emotion.wellbeing": ("fatigue", 0.3, True),  # High wellbeing reduces fatigue
    "resource.energy": ("fatigue", 0.2, False),
    "resource.time": ("time_pressure", 0.3, False),
    "planning.short_term": ("time_pressure", 0.2, False),
    "social.norms": ("social_risk", 0.3, False),
    "social.relationships": ("social_risk", 0.2, False),
    "inhibition.censor": ("social_risk", 0.2, False),
}


def update_modulators_from_agent(
    modulators: GlobalModulators,
    agent_id: str,
    urgency: int,
) -> bool:
    """Update modulators based on agent output.

    Returns True if any modulator changed significantly.
    """
    if agent_id not in MODULATOR_MAP:
        return False

    modulator_name, weight, is_inverse = MODULATOR_MAP[agent_id]

    # Calculate delta based on urgency
    delta = (urgency / 3.0) * weight
    if is_inverse:
        delta = -delta

    # Get current value
    current = getattr(modulators, modulator_name, 0.0)

    # Apply with bounds
    new_value = max(0.0, min(1.0, current + delta))

    # Check if changed significantly
    if abs(new_value - current) < 0.01:
        return False

    # Update
    object.__setattr__(modulators, modulator_name, new_value)
    modulators.source_agents[modulator_name] = agent_id
    object.__setattr__(modulators, "last_update", datetime.now())

    return True


def create_default_modulators() -> GlobalModulators:
    """Create default modulators."""
    return GlobalModulators(
        arousal=0.3,
        fatigue=0.0,
        time_pressure=0.0,
        social_risk=0.0,
    )
