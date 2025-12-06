"""Agent protocol and types for Rilai v2."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from rilai.agencies.messages import AgentAssessment, RilaiEvent, Value

if TYPE_CHECKING:
    from rilai.council.messages import DeliberationContext, SelfModelView


# Prompts directory relative to this file
PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


@dataclass
class WorkingMemoryView:
    """Read-only view of relevant context for agent processing."""

    conversation_history: list[dict]  # Recent messages
    active_goals: list[str]  # Current user goals
    recent_assessments: list[AgentAssessment]  # From other agents
    user_baseline: dict | None  # Learned user patterns
    current_time: str

    # Agency-specific context (populated by agency)
    agency_context: dict | None = None

    # Self-model view for identity-aware agents
    self_model: "SelfModelView | None" = None

    # Deliberation context (for multi-round deliberation)
    deliberation: "DeliberationContext | None" = None


class Agent(Protocol):
    """Protocol for sub-agents within an agency."""

    agent_id: str  # Unique ID: "{agency}.{agent_name}"
    agency_id: str  # Parent agency ID
    name: str  # Human-readable name
    description: str  # What this agent does
    value: Value  # Primary value this agent promotes

    async def assess(
        self, event: RilaiEvent, context: WorkingMemoryView
    ) -> AgentAssessment:
        """Evaluate the event from this agent's perspective."""
        ...


@dataclass
class AgentConfig:
    """Configuration for a sub-agent."""

    name: str  # e.g., "short_term", "wellbeing"
    description: str = ""
    always_on: bool = False  # Whether this agent runs regardless of gating
    weight: float = 1.0  # Relative importance for ranking


@dataclass
class AgencyConfig:
    """Configuration for an agency."""

    agency_id: str
    display_name: str
    description: str
    value: Value
    agents: list[AgentConfig] = field(default_factory=list)

    # Gating configuration
    domain_marker: str | None = None  # Which event signature field to check
    always_active: bool = False  # Whether agency always runs
