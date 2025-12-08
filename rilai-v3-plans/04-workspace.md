# Document 04: Workspace

**Purpose:** Implement workspace (blackboard) and deterministic reducer
**Execution:** One Claude Code session
**Dependencies:** 01-contracts, 02-event-store, 03-runtime-core

---

## Overview

The workspace is the global blackboard that all agents can read from and propose updates to. A deterministic reducer merges proposals into actual state.

---

## Files to Create

```
src/rilai/runtime/
├── workspace.py         # Workspace class (blackboard)
├── reducer.py           # Deterministic proposal merger
├── stance.py            # StanceVector management
└── modulators.py        # GlobalModulators with decay
```

---

## File: `src/rilai/runtime/workspace.py`

```python
"""Workspace - global blackboard for agent coordination."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from rilai.contracts.workspace import StanceVector, GlobalModulators, Goal
from rilai.contracts.agent import AgentOutput, Claim


@dataclass
class Workspace:
    """Global workspace / blackboard state.

    All agents read from this, and propose updates through AgentOutput.
    The reducer merges proposals deterministically.
    """

    # ─────────────────────────────────────────────────────────────────────
    # Context Slots (set at turn start)
    # ─────────────────────────────────────────────────────────────────────
    user_message: str = ""
    conversation_history: list[dict[str, Any]] = field(default_factory=list)
    retrieved_episodes: list[dict] = field(default_factory=list)
    user_facts: list[dict] = field(default_factory=list)
    open_threads: list[Goal] = field(default_factory=list)

    # ─────────────────────────────────────────────────────────────────────
    # Live State (updated by reducer)
    # ─────────────────────────────────────────────────────────────────────
    stance: StanceVector = field(default_factory=StanceVector)
    modulators: GlobalModulators = field(default_factory=GlobalModulators)
    active_claims: list[Claim] = field(default_factory=list)
    consensus_level: float = 0.0

    # ─────────────────────────────────────────────────────────────────────
    # Decision Slots (set by council)
    # ─────────────────────────────────────────────────────────────────────
    current_goal: str | None = None
    constraints: list[str] = field(default_factory=list)
    pending_asks: list[str] = field(default_factory=list)
    current_response: str | None = None

    # ─────────────────────────────────────────────────────────────────────
    # Metadata
    # ─────────────────────────────────────────────────────────────────────
    turn_id: int = 0
    last_user_message_time: float | None = None
    _stance_before: dict[str, float] = field(default_factory=dict)

    def set_user_message(self, message: str) -> None:
        """Set the current user message and update timestamp."""
        import time
        self.user_message = message
        self.last_user_message_time = time.time()
        self._stance_before = self.stance.to_dict()

    def reset_for_turn(self) -> None:
        """Reset transient state for a new turn."""
        self.active_claims.clear()
        self.consensus_level = 0.0
        self.current_goal = None
        self.constraints.clear()
        self.pending_asks.clear()
        self.current_response = None
        self._stance_before = self.stance.to_dict()

    def apply_agent_output(self, output: AgentOutput) -> None:
        """Apply an agent's output to the workspace.

        This is the main entry point for the reducer.
        """
        from rilai.runtime.reducer import apply_output
        apply_output(self, output)

    def get_stance_delta(self) -> dict[str, float] | None:
        """Get stance changes since turn start."""
        current = self.stance.to_dict()
        delta = {}
        for key, val in current.items():
            before = self._stance_before.get(key, val)
            if abs(val - before) > 0.01:
                delta[key] = val - before
        return delta if delta else None

    def to_prompt_context(self) -> str:
        """Format workspace for inclusion in agent prompts."""
        lines = [
            f"User message: {self.user_message}",
            "",
            "Recent conversation:",
        ]
        for msg in self.conversation_history[-5:]:
            role = msg.get("role", "?")
            content = msg.get("content", "")[:100]
            lines.append(f"  {role}: {content}")

        lines.append("")
        lines.append(f"Current stance: {self.stance.to_dict()}")
        lines.append(f"Modulators: {self.modulators.to_dict()}")

        if self.active_claims:
            lines.append("")
            lines.append(f"Active claims ({len(self.active_claims)}):")
            for claim in self.active_claims[:5]:
                lines.append(f"  - [{claim.type}] {claim.text}")

        return "\n".join(lines)
```

---

## File: `src/rilai/runtime/reducer.py`

```python
"""Reducer - deterministic proposal merger for workspace."""

from rilai.contracts.agent import AgentOutput, Claim
from rilai.contracts.workspace import StanceVector


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
    from rilai.runtime.workspace import Workspace

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
        setattr(workspace.stance, dim, new_value)


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
```

---

## File: `src/rilai/runtime/stance.py`

```python
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
```

---

## File: `src/rilai/runtime/modulators.py`

```python
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
    setattr(modulators, modulator_name, new_value)
    modulators.source_agents[modulator_name] = agent_id
    modulators.last_update = datetime.now()

    return True


def create_default_modulators() -> GlobalModulators:
    """Create default modulators."""
    return GlobalModulators(
        arousal=0.3,
        fatigue=0.0,
        time_pressure=0.0,
        social_risk=0.0,
    )
```

---

## v2 Files to DELETE

```
src/rilai/core/stance.py
src/rilai/core/stance_aggregator.py
src/rilai/brain/modulators.py
```

---

## Tests

```python
"""Tests for workspace module."""

from rilai.runtime.workspace import Workspace
from rilai.runtime.reducer import apply_output
from rilai.contracts.agent import AgentOutput, Claim, ClaimType


class TestReducer:
    def test_stance_delta_application(self):
        workspace = Workspace()
        initial_strain = workspace.stance.strain

        output = AgentOutput(
            agent_id="emotion.stress",
            observation="High stress",
            salience=0.8,
            urgency=2,
            confidence=2,
            stance_delta={"strain": 0.1},
        )
        workspace.apply_agent_output(output)

        # Strain should increase (with leaky integration)
        assert workspace.stance.strain > initial_strain

    def test_claim_deduplication(self):
        workspace = Workspace()

        claim1 = Claim(
            id="1",
            text="User is stressed",
            type=ClaimType.OBSERVATION,
            source_agent="emotion.stress",
            urgency=1,
            confidence=2,
        )
        claim2 = Claim(
            id="2",
            text="User is stressed about work",  # Similar
            type=ClaimType.OBSERVATION,
            source_agent="emotion.wellbeing",
            urgency=2,
            confidence=2,
        )

        output1 = AgentOutput.quiet("a").model_copy(update={"claims": [claim1]})
        output2 = AgentOutput.quiet("b").model_copy(update={"claims": [claim2]})

        workspace.apply_agent_output(output1)
        workspace.apply_agent_output(output2)

        # Should merge into one claim with max urgency
        assert len(workspace.active_claims) == 1
        assert workspace.active_claims[0].urgency == 2
```

---

## Next Document

Proceed to `05-agents.md` after workspace is implemented.
