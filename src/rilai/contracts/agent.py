"""Agent contracts - outputs, manifests, and claims."""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from rilai.contracts.memory import MemoryCandidate


class ClaimType(str, Enum):
    """Types of claims agents can make."""

    OBSERVATION = "observation"      # What the agent noticed
    RECOMMENDATION = "recommendation"  # What the agent suggests
    CONCERN = "concern"              # What worries the agent
    QUESTION = "question"            # What the agent wants to know


class Claim(BaseModel):
    """An atomic statement from an agent.

    Claims are the currency of deliberation. They can support or oppose
    other claims, forming an argument graph.
    """

    id: str = Field(description="UUID for this claim")
    text: str = Field(max_length=200, description="Atomic statement, max 200 chars")
    type: ClaimType = Field(description="Claim type")
    source_agent: str = Field(description="Agent that made this claim")
    urgency: int = Field(ge=0, le=3, description="0=background, 3=must act now")
    confidence: int = Field(ge=0, le=3, description="0=uncertain, 3=certain")
    supports: list[str] = Field(
        default_factory=list,
        description="IDs of claims this supports"
    )
    opposes: list[str] = Field(
        default_factory=list,
        description="IDs of claims this opposes"
    )


class AgentOutput(BaseModel):
    """Structured output from an agent.

    Replaces v2's freeform voice + [U:C] suffix with typed fields.
    """

    agent_id: str = Field(description="e.g., 'emotion.stress'")
    observation: str = Field(
        max_length=300,
        description="1-3 sentences describing what agent noticed"
    )
    salience: float = Field(
        ge=0.0, le=1.0,
        description="Normalized urgency × confidence"
    )
    urgency: int = Field(ge=0, le=3, description="0=background, 3=must act now")
    confidence: int = Field(ge=0, le=3, description="0=uncertain, 3=certain")
    claims: list[Claim] = Field(
        default_factory=list,
        description="Atomic claims for deliberation"
    )
    stance_delta: dict[str, float] | None = Field(
        default=None,
        description="Proposed stance changes (bounded ±0.15)"
    )
    workspace_patch: dict | None = Field(
        default=None,
        description="Proposed workspace updates"
    )
    memory_candidates: list[MemoryCandidate] | None = Field(
        default=None,
        description="Things worth remembering"
    )
    debug_trace: str | None = Field(
        default=None,
        description="Reasoning trace (stored, not always displayed)"
    )
    processing_time_ms: int = Field(
        default=0,
        description="Time to generate this output"
    )

    @classmethod
    def quiet(cls, agent_id: str) -> AgentOutput:
        """Create a 'quiet' output when agent has nothing to say."""
        return cls(
            agent_id=agent_id,
            observation="Quiet",
            salience=0.0,
            urgency=0,
            confidence=0,
            claims=[],
        )


class AgentPriority(str, Enum):
    """Agent scheduling priority."""

    ALWAYS_ON = "always_on"  # Runs every turn (censor, trigger_watcher, etc.)
    MONITOR = "monitor"      # Runs when relevant markers present
    NORMAL = "normal"        # Runs based on scheduling


class AgentSafetyProfile(str, Enum):
    """What actions an agent can take."""

    READ_ONLY = "read_only"      # Can only observe
    CAN_SUGGEST = "can_suggest"  # Can propose actions
    CAN_ACT = "can_act"          # Can take direct action (future)


class AgentManifest(BaseModel):
    """Configuration for an agent.

    Loaded from YAML files in prompts/agents/{agency}/{agent}.yaml
    """

    id: str = Field(description="e.g., 'emotion.stress'")
    display_name: str = Field(description="Human-readable name")
    description: str = Field(default="", description="What this agent does")
    inputs: list[str] = Field(
        description="Workspace slots this agent reads"
    )
    outputs: list[str] = Field(
        description="What this agent can emit: observation, claims, stance_delta, etc."
    )
    cost_estimate: int = Field(
        default=500,
        description="Estimated tokens per call"
    )
    cooldown: int = Field(
        default=30,
        description="Seconds before agent can fire again"
    )
    priority: AgentPriority = Field(
        default=AgentPriority.NORMAL,
        description="Scheduling priority"
    )
    safety_profile: AgentSafetyProfile = Field(
        default=AgentSafetyProfile.READ_ONLY,
        description="What actions agent can take"
    )
    prompt_template: str = Field(
        description="Filename in prompts/agents/{agency}/"
    )
    version: int = Field(default=1, description="Manifest version")

    @property
    def agency_id(self) -> str:
        """Extract agency from id (e.g., 'emotion' from 'emotion.stress')."""
        return self.id.split(".")[0]

    @property
    def agent_name(self) -> str:
        """Extract agent name from id (e.g., 'stress' from 'emotion.stress')."""
        return self.id.split(".")[-1]


# Rebuild model to resolve forward references
def _rebuild_models():
    from rilai.contracts.memory import MemoryCandidate
    AgentOutput.model_rebuild()

# Note: Call _rebuild_models() after all imports are done
