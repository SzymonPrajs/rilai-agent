"""Reducer - deterministic proposal merger for workspace."""

from typing import TYPE_CHECKING

from rilai.contracts.agent import AgentOutput, Claim

if TYPE_CHECKING:
    from rilai.runtime.workspace import Workspace


# Maximum stance delta per turn (prevents thrashing)
MAX_STANCE_DELTA = 0.15

# Stance dimension bounds
STANCE_BOUNDS = {
    "valence": (-1.0, 1.0),
    "arousal": (0.0, 1.0),
    "control": (0.0, 1.0),
    "certainty": (0.0, 1.0),
    "safety": (0.0, 1.0),
    "closeness": (0.0, 1.0),
    "curiosity": (0.0, 1.0),
    "strain": (0.0, 1.0),
}


def apply_output(workspace: "Workspace", output: AgentOutput) -> None:
    """Apply an agent's output to the workspace.

    This is the core reducer function. It:
    1. Adds claims to active_claims (with deduplication)
    2. Applies stance_delta with leaky integration
    3. Applies workspace_patch
    """
    # 1. Add claims
    if output.claims:
        for claim in output.claims:
            _add_claim(workspace, claim)

    # 2. Apply stance delta
    if output.stance_delta:
        _apply_stance_delta(workspace, output.stance_delta)

    # 3. Apply workspace patch
    if output.workspace_patch:
        _apply_workspace_patch(workspace, output.workspace_patch)


def _add_claim(workspace: "Workspace", claim: Claim) -> None:
    """Add a claim with deduplication and support/oppose merging."""
    # Check for duplicate by text similarity
    for existing in workspace.active_claims:
        if _claims_similar(existing, claim):
            # Merge supports/opposes
            existing.supports = list(set(existing.supports + claim.supports))
            existing.opposes = list(set(existing.opposes + claim.opposes))
            # Update urgency/confidence to max
            existing.urgency = max(existing.urgency, claim.urgency)
            existing.confidence = max(existing.confidence, claim.confidence)
            return

    # New claim
    workspace.active_claims.append(claim)


def _claims_similar(a: Claim, b: Claim) -> bool:
    """Check if two claims are similar enough to merge."""
    # Simple: same type and >70% word overlap
    if a.type != b.type:
        return False

    words_a = set(a.text.lower().split())
    words_b = set(b.text.lower().split())

    if not words_a or not words_b:
        return False

    overlap = len(words_a & words_b)
    total = len(words_a | words_b)

    return overlap / total > 0.7


def _apply_stance_delta(
    workspace: "Workspace",
    delta: dict[str, float],
) -> None:
    """Apply stance delta with leaky integration.

    Uses exponential moving average: new = old * (1 - alpha) + delta * alpha
    Clamps delta to MAX_STANCE_DELTA and result to bounds.
    """
    alpha = 0.25  # Integration rate

    for dim, change in delta.items():
        if dim not in STANCE_BOUNDS:
            continue

        # Clamp delta
        clamped_delta = max(-MAX_STANCE_DELTA, min(MAX_STANCE_DELTA, change))

        # Get current value
        current = getattr(workspace.stance, dim, 0.0)

        # Leaky integration
        new_value = current * (1 - alpha) + (current + clamped_delta) * alpha

        # Clamp to bounds
        min_val, max_val = STANCE_BOUNDS[dim]
        new_value = max(min_val, min(max_val, new_value))

        # Update
        object.__setattr__(workspace.stance, dim, new_value)


def _apply_workspace_patch(
    workspace: "Workspace",
    patch: dict,
) -> None:
    """Apply a workspace patch.

    Only certain fields can be patched by agents.
    """
    allowed_fields = {"pending_asks", "constraints"}

    for key, value in patch.items():
        if key in allowed_fields:
            current = getattr(workspace, key, [])
            if isinstance(current, list) and isinstance(value, list):
                # Extend lists
                setattr(workspace, key, list(set(current + value)))
            else:
                setattr(workspace, key, value)
