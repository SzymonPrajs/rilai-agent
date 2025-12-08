"""StanceVector management utilities."""

from rilai.contracts.workspace import StanceVector


def create_default_stance() -> StanceVector:
    """Create a default stance vector."""
    return StanceVector(
        valence=0.0,
        arousal=0.3,
        control=0.5,
        certainty=0.5,
        safety=0.7,
        closeness=0.3,
        curiosity=0.5,
        strain=0.0,
    )


def stance_distance(a: StanceVector, b: StanceVector) -> float:
    """Calculate Euclidean distance between two stance vectors."""
    dims = ["valence", "arousal", "control", "certainty", "safety", "closeness", "curiosity", "strain"]
    squared_sum = sum((getattr(a, d) - getattr(b, d)) ** 2 for d in dims)
    return squared_sum ** 0.5


def stance_similarity(a: StanceVector, b: StanceVector) -> float:
    """Calculate similarity (0-1) between two stance vectors."""
    max_distance = 8 ** 0.5  # Max possible distance
    return 1.0 - (stance_distance(a, b) / max_distance)


def describe_stance(stance: StanceVector) -> str:
    """Generate a human-readable description of stance."""
    descriptions = []

    if stance.valence > 0.3:
        descriptions.append("positive")
    elif stance.valence < -0.3:
        descriptions.append("negative")

    if stance.arousal > 0.6:
        descriptions.append("activated")
    elif stance.arousal < 0.3:
        descriptions.append("calm")

    if stance.strain > 0.5:
        descriptions.append("strained")

    if stance.closeness > 0.6:
        descriptions.append("connected")
    elif stance.closeness < 0.3:
        descriptions.append("distant")

    return ", ".join(descriptions) if descriptions else "neutral"
