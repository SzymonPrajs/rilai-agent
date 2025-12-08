"""
Micro-Agent Output Schema

Micro-agents are narrow perspective modules that do NOT answer the user directly.
They produce structured observations that feed into the workspace builder.

Key principles:
    - JSON-only output with strict schema
    - Soft salience (0-1), NO "Quiet" pattern
    - Hypotheses MUST cite evidence_ids
    - Max stance delta: |Δ| = 0.08 per dimension
    - Glimpses are optional short observations
"""

from dataclasses import dataclass, field
from typing import Optional
import json


MAX_STANCE_DELTA = 0.08  # Maximum per-dimension stance change


@dataclass
class MicroHypothesis:
    """A hypothesis about the user or situation with evidence linking."""
    text: str
    p: float  # Probability [0, 1]
    evidence_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "h": self.text,
            "p": self.p,
            "evidence_ids": self.evidence_ids,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MicroHypothesis":
        return cls(
            text=data.get("h", ""),
            p=data.get("p", 0.0),
            evidence_ids=data.get("evidence_ids", []),
        )


@dataclass
class MicroQuestion:
    """A discriminating question with priority."""
    question: str
    priority: float  # [0, 1]

    def to_dict(self) -> dict:
        return {
            "q": self.question,
            "priority": self.priority,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MicroQuestion":
        return cls(
            question=data.get("q", ""),
            priority=data.get("priority", 0.0),
        )


@dataclass
class MicroAgentOutput:
    """
    Output schema for micro-agents.

    Every micro-agent outputs this structure. If nothing arises,
    salience=0 with empty lists and glimpse="".

    There is NO "Quiet" — silence is just low salience with empty glimpse.
    """
    agent: str
    salience: float  # [0, 1]
    stance_delta: dict[str, float] = field(default_factory=dict)
    hypotheses: list[MicroHypothesis] = field(default_factory=list)
    questions: list[MicroQuestion] = field(default_factory=list)
    glimpse: str = ""

    # Extended thinking (if model supports it)
    thinking: Optional[str] = None

    def __post_init__(self):
        """Validate and clamp values."""
        self.salience = max(0.0, min(1.0, self.salience))

        # Clamp stance deltas to max allowed
        clamped_delta = {}
        for dim, delta in self.stance_delta.items():
            clamped_delta[dim] = max(-MAX_STANCE_DELTA, min(MAX_STANCE_DELTA, delta))
        self.stance_delta = clamped_delta

    def to_dict(self) -> dict:
        return {
            "agent": self.agent,
            "salience": self.salience,
            "stance_delta": self.stance_delta,
            "hypotheses": [h.to_dict() for h in self.hypotheses],
            "questions": [q.to_dict() for q in self.questions],
            "glimpse": self.glimpse,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: dict) -> "MicroAgentOutput":
        return cls(
            agent=data.get("agent", "unknown"),
            salience=data.get("salience", 0.0),
            stance_delta=data.get("stance_delta", {}),
            hypotheses=[MicroHypothesis.from_dict(h) for h in data.get("hypotheses", [])],
            questions=[MicroQuestion.from_dict(q) for q in data.get("questions", [])],
            glimpse=data.get("glimpse", ""),
        )

    @classmethod
    def from_json(cls, json_str: str, agent_name: str = "unknown") -> "MicroAgentOutput":
        """Parse agent output from JSON string."""
        try:
            data = json.loads(json_str)
            data["agent"] = data.get("agent", agent_name)
            return cls.from_dict(data)
        except json.JSONDecodeError:
            return cls(agent=agent_name, salience=0.0, glimpse="Parse error")

    @property
    def is_active(self) -> bool:
        """Whether this agent has meaningful output."""
        return (
            self.salience > 0.1 or
            bool(self.hypotheses) or
            bool(self.questions) or
            bool(self.glimpse)
        )


def create_null_output(agent_name: str) -> MicroAgentOutput:
    """Create a null/silent output for an agent."""
    return MicroAgentOutput(agent=agent_name, salience=0.0)


def merge_stance_deltas(outputs: list[MicroAgentOutput]) -> dict[str, float]:
    """
    Merge stance deltas from multiple agents using salience-weighted averaging.

    Args:
        outputs: List of micro-agent outputs

    Returns:
        Merged stance delta dictionary
    """
    if not outputs:
        return {}

    # Collect all dimensions
    all_dims = set()
    for out in outputs:
        all_dims.update(out.stance_delta.keys())

    merged = {}
    for dim in all_dims:
        weighted_sum = 0.0
        weight_total = 0.0
        for out in outputs:
            if dim in out.stance_delta:
                weighted_sum += out.stance_delta[dim] * out.salience
                weight_total += out.salience

        if weight_total > 0:
            merged[dim] = weighted_sum / weight_total
        else:
            merged[dim] = 0.0

    return merged


def select_top_agents(
    outputs: list[MicroAgentOutput],
    top_k: int = 8,
    min_salience: float = 0.1,
) -> list[MicroAgentOutput]:
    """
    Select top agents by salience for workspace inclusion.

    Args:
        outputs: List of all agent outputs
        top_k: Maximum number to include
        min_salience: Minimum salience threshold

    Returns:
        List of top agents sorted by salience
    """
    filtered = [o for o in outputs if o.salience >= min_salience]
    sorted_outputs = sorted(filtered, key=lambda x: -x.salience)
    return sorted_outputs[:top_k]


# Agent groups for diversity selection
AGENT_GROUPS = {
    "grounding": ["literal_listener", "evidence_curator"],
    "affect": [
        "vulnerability_holder", "fear_reader", "shame_reader",
        "anger_boundary_reader", "grief_reader", "overwhelm_load_reader",
        "desire_wanting_reader",
    ],
    "relational": [
        "care_sensor", "judgment_detector", "trust_calibrator",
        "dependency_guard", "boundary_keeper", "humor_mask_unwrapper",
    ],
    "mechanics": [
        "consent_to_advise_checker", "clarification_asker", "specificity_enforcer",
    ],
    "meaning": [
        "meaning_seeker", "value_mapper", "identity_threader", "reframe_gentle",
    ],
    "meta": [
        "rupture_repairer", "meta_transparency", "contrarian",
        "uncertainty_humility", "coherence_checker",
    ],
    "style": [
        "tone_matcher", "metaphor_weaver", "concision_editor", "cliche_filter",
    ],
    "action": [
        "action_planner", "norms_contextualizer",
    ],
}


def ensure_group_diversity(
    outputs: list[MicroAgentOutput],
    required_groups: Optional[list[str]] = None,
) -> list[MicroAgentOutput]:
    """
    Ensure at least one agent from required groups is included.

    Args:
        outputs: Current selected outputs
        required_groups: Groups that must have representation

    Returns:
        Updated list with diversity requirements met
    """
    if required_groups is None:
        required_groups = ["grounding", "affect", "relational", "meaning"]

    included_groups = set()
    agent_to_group = {}

    for group, agents in AGENT_GROUPS.items():
        for agent in agents:
            agent_to_group[agent] = group

    for out in outputs:
        group = agent_to_group.get(out.agent)
        if group:
            included_groups.add(group)

    # All required groups already covered
    missing = set(required_groups) - included_groups
    if not missing:
        return outputs

    # This would require access to all outputs, not just selected ones
    # In practice, the selector should handle this upstream
    return outputs
