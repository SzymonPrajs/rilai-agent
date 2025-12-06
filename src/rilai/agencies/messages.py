"""Inter-agency message formats for Society of Mind architecture."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Literal


class Value(Enum):
    """Core values for agency assessments.

    Based on Society of Mind principles - each agency advocates for a specific value.
    """

    # Goal-Oriented Agencies
    PRODUCTIVITY = "productivity"  # Planning Agency
    RESOURCES = "resources"  # Resource Agency
    IDENTITY = "identity"  # Self Agency

    # Evaluative Agencies
    WELLBEING = "wellbeing"  # Emotion Agency
    CONNECTION = "connection"  # Social Agency

    # Problem-Solving Agencies
    UNDERSTANDING = "understanding"  # Reasoning Agency
    CREATIVITY = "creativity"  # Creative Agency

    # Control Agencies
    SAFETY = "safety"  # Inhibition Agency
    AWARENESS = "awareness"  # Monitoring Agency

    # Action Agency
    ACTION = "action"  # Execution Agency


@dataclass
class SalienceMetadata:
    """Salience signals extracted from agent output.

    Agents emit urgency and confidence alongside their voice output.
    These are used for routing, compression, and prioritization.
    """

    urgency: int  # 0-3: how important to act/mention now
    confidence: int  # 0-3: how sure agent is this is relevant
    raw_score: float = 0.0  # Computed salience (U * C * weights * boosts)

    def compute_base_score(self) -> float:
        """Compute basic salience score (U * C)."""
        return float(self.urgency * self.confidence)


@dataclass
class EventSignature:
    """Features extracted from event for routing decisions.

    Used by agencies to decide which agents to activate.
    """

    event_type: str  # "text", "voice", "background", etc.
    has_emotion_markers: bool = False
    has_planning_markers: bool = False
    has_social_markers: bool = False
    has_problem_markers: bool = False
    has_action_markers: bool = False
    is_question: bool = False
    is_urgent: bool = False
    word_count: int = 0

    @classmethod
    def from_event(cls, event: "RilaiEvent") -> "EventSignature":
        """Extract signature from event content."""
        content_lower = event.content.lower()

        # Keyword detection for routing
        emotion_words = [
            "feel",
            "feeling",
            "happy",
            "sad",
            "angry",
            "anxious",
            "stressed",
            "tired",
        ]
        planning_words = [
            "plan",
            "goal",
            "task",
            "deadline",
            "schedule",
            "tomorrow",
            "next week",
        ]
        social_words = [
            "friend",
            "family",
            "relationship",
            "they said",
            "meeting",
            "people",
        ]
        problem_words = ["problem", "issue", "bug", "error", "wrong", "broken", "help"]
        action_words = ["do", "make", "create", "build", "start", "finish", "run"]

        return cls(
            event_type=event.type,
            has_emotion_markers=any(w in content_lower for w in emotion_words),
            has_planning_markers=any(w in content_lower for w in planning_words),
            has_social_markers=any(w in content_lower for w in social_words),
            has_problem_markers=any(w in content_lower for w in problem_words),
            has_action_markers=any(w in content_lower for w in action_words),
            is_question="?" in event.content,
            is_urgent=any(
                w in content_lower for w in ["urgent", "asap", "immediately", "now"]
            ),
            word_count=len(event.content.split()),
        )


@dataclass
class AgentTraceData:
    """Full trace data for an agent execution.

    Captures everything needed for developer visibility:
    - System prompt and full built prompt
    - Input context (event + conversation)
    - LLM request/response details
    - Extracted thinking (from thinking models or <thinking> tags)
    """

    system_prompt: str
    full_prompt: str
    event_content: str
    conversation_history: list[dict]

    # LLM details
    llm_model: str | None = None
    llm_temperature: float | None = None
    llm_latency_ms: int | None = None
    llm_usage: dict | None = None
    llm_request_messages: list[dict] | None = None

    # Extracted thinking from agent output or reasoning tokens
    thinking: str | None = None
    reasoning_tokens: int | None = None  # For thinking models


@dataclass
class AgentAssessment:
    """Output from a single sub-agent within an agency.

    Agents output free-form text with salience metadata.
    Format: "Voice text here [U:N C:N]"
    """

    agent_id: str  # e.g., "emotion.wellbeing"
    agency_id: str  # e.g., "emotion"

    # Free-form output - what this agent observed (includes [U:C] suffix)
    output: str

    # Provenance
    value: Value
    processing_time_ms: int

    # Optional fields
    salience: SalienceMetadata | None = None  # Parsed from output tail
    timestamp: datetime = field(default_factory=datetime.now)
    trace: AgentTraceData | None = None  # Developer visibility

    @property
    def is_quiet(self) -> bool:
        """Check if this agent output 'Quiet.'"""
        return self.output.strip().lower().startswith("quiet")

    @property
    def voice(self) -> str:
        """Get just the voice output without salience metadata."""
        import re

        # Remove [U:N C:N] suffix
        return re.sub(r"\s*\[U:\d+\s*C:\d+\]\s*$", "", self.output).strip()


@dataclass
class AgencyAssessment:
    """Aggregated output from an entire agency (router/compressor).

    Agencies act as routers that gate agent activation and compress
    outputs to the most salient signals.
    """

    agency_id: str
    value: Value

    # Router output
    agency_u_max: int = 0  # Max urgency among agents that ran
    top_hits: list[str] = field(default_factory=list)  # Most salient agent_ids
    brief: str = ""  # 1-3 lines optional summary

    # Sub-agent outputs (filtered to high-salience)
    sub_assessments: list[AgentAssessment] = field(default_factory=list)

    # Metadata
    active_agents: int = 0  # Agents that ran
    total_agents: int = 0  # Total agents in agency
    gated_agents: int = 0  # Agents skipped by gating
    processing_time_ms: int = 0
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def has_high_salience(self) -> bool:
        """Check if any agent has high urgency (U >= 2)."""
        return self.agency_u_max >= 2

    def get_top_assessments(self, n: int = 3) -> list[AgentAssessment]:
        """Get top N assessments by salience score."""
        sorted_assessments = sorted(
            [a for a in self.sub_assessments if a.salience is not None],
            key=lambda a: a.salience.raw_score if a.salience else 0,
            reverse=True,
        )
        return sorted_assessments[:n]


@dataclass
class RilaiEvent:
    """Normalized input event for agency processing."""

    event_id: str
    type: Literal["text", "voice", "system", "timer", "background"]
    content: str

    # Context
    user_id: str
    session_id: str
    timestamp: datetime

    # Sensors (optional)
    keystroke_features: dict[str, Any] | None = None
    voice_features: dict[str, Any] | None = None

    # Metadata
    metadata: dict[str, Any] = field(default_factory=dict)
