"""
Workspace Packet - The Global Broadcast Bottleneck

Based on Global Workspace Theory (GWT/GNW), this is the single canonical object
that all downstream modules receive after Pass 1 completes.

The workspace packet is built by the workspace builder (medium tier) and then
broadcast to all focused generators in Pass 2. This ensures global coherence
through reentrant conditioning.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from rilai.core.stance import StanceVector


class InteractionGoal(Enum):
    """
    Interaction goals determine the primary intent of the response.

    WITNESS: Validate, name, slow down (for vulnerability)
    INVITE: One clarifying question (for ambiguity)
    REFRAME: Offer alternative meaning (for stuck patterns)
    OPTIONS: Practical steps (only when explicitly requested)
    BOUNDARY: Safety, honesty, refusal (for safety/integrity)
    META: Talk about interaction itself (for AI probes, rupture repair)
    """
    WITNESS = "witness"
    INVITE = "invite"
    REFRAME = "reframe"
    OPTIONS = "options"
    BOUNDARY = "boundary"
    META = "meta"


@dataclass
class EvidenceSpan:
    """A substring reference in the user's message."""
    text: str
    start: int
    end: int


@dataclass
class CueExtraction:
    """Extracted cues from the user's message (tiny tier)."""
    topics: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    key_phrases: list[str] = field(default_factory=list)
    tone_markers: list[str] = field(default_factory=list)
    compressed_intent: str = ""


@dataclass
class AgentHighlight:
    """A highlighted observation from a micro-agent."""
    agent: str
    salience: float
    glimpse: str
    stance_delta: dict[str, float] = field(default_factory=dict)


@dataclass
class Hypothesis:
    """A hypothesis about the user or situation."""
    h_id: str
    text: str
    p: float  # Probability [0, 1]
    evidence_ids: list[str] = field(default_factory=list)


@dataclass
class PrioritizedQuestion:
    """A discriminating question with priority."""
    question: str
    priority: float  # [0, 1]
    agent: str = ""  # Which agent proposed this


@dataclass
class RelationshipSummary:
    """Summary of relational memory for the workspace."""
    summary: str
    evidence_count: int
    hypothesis_count: int
    key_hypotheses: list[Hypothesis] = field(default_factory=list)


@dataclass
class WorkspacePacket:
    """
    The single canonical object that all downstream modules receive.

    This is the "global broadcast" in Global Workspace Theory terms.
    All focused generators (Pass 2) condition on this packet only,
    NOT on raw conversation history.
    """

    # Turn identification
    turn_id: int

    # User input
    user_text: str
    cues: CueExtraction

    # Sensor outputs (probabilities)
    sensor_summary: dict[str, float] = field(default_factory=dict)

    # Affective state
    stance: StanceVector = field(default_factory=StanceVector)

    # Relational context
    relationship_summary: Optional[RelationshipSummary] = None

    # Interaction policy
    goal: InteractionGoal = InteractionGoal.WITNESS
    primary_question: str = ""
    constraints: list[str] = field(default_factory=list)

    # Micro-agent contributions (from Pass 1)
    micro_agent_highlights: list[AgentHighlight] = field(default_factory=list)
    collected_hypotheses: list[Hypothesis] = field(default_factory=list)
    collected_questions: list[PrioritizedQuestion] = field(default_factory=list)

    # Escalation state
    escalate_to_large: bool = False
    escalation_reason: str = ""

    # Processing metadata
    sensor_disagreement: float = 0.0  # Std dev of sensor ensemble
    regen_attempts: int = 0

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization and prompt injection."""
        return {
            "turn_id": self.turn_id,
            "user_text": self.user_text,
            "cues": {
                "topics": self.cues.topics,
                "entities": self.cues.entities,
                "key_phrases": self.cues.key_phrases,
                "tone_markers": self.cues.tone_markers,
                "compressed_intent": self.cues.compressed_intent,
            },
            "sensor_summary": self.sensor_summary,
            "stance": self.stance.to_dict(),
            "relationship_summary": {
                "summary": self.relationship_summary.summary if self.relationship_summary else "",
                "evidence_count": self.relationship_summary.evidence_count if self.relationship_summary else 0,
                "hypothesis_count": self.relationship_summary.hypothesis_count if self.relationship_summary else 0,
                "key_hypotheses": [
                    {"h_id": h.h_id, "text": h.text, "p": h.p, "evidence_ids": h.evidence_ids}
                    for h in (self.relationship_summary.key_hypotheses if self.relationship_summary else [])
                ],
            },
            "goal": self.goal.value,
            "primary_question": self.primary_question,
            "constraints": self.constraints,
            "micro_agent_highlights": [
                {
                    "agent": h.agent,
                    "salience": h.salience,
                    "glimpse": h.glimpse,
                    "stance_delta": h.stance_delta,
                }
                for h in self.micro_agent_highlights
            ],
            "collected_hypotheses": [
                {"h_id": h.h_id, "text": h.text, "p": h.p, "evidence_ids": h.evidence_ids}
                for h in self.collected_hypotheses
            ],
            "collected_questions": [
                {"question": q.question, "priority": q.priority, "agent": q.agent}
                for q in self.collected_questions
            ],
            "escalate_to_large": self.escalate_to_large,
            "escalation_reason": self.escalation_reason,
            "sensor_disagreement": self.sensor_disagreement,
            "regen_attempts": self.regen_attempts,
        }

    def to_prompt_context(self) -> str:
        """Generate a concise context string for injection into generator prompts."""
        lines = [
            f"Turn: {self.turn_id}",
            f"User: {self.user_text}",
            "",
            f"Goal: {self.goal.value.upper()}",
            f"Primary Question: {self.primary_question}" if self.primary_question else "",
            "",
            "Constraints:",
        ]
        for c in self.constraints:
            lines.append(f"  - {c}")

        lines.extend([
            "",
            "Sensors:",
        ])
        for sensor, prob in sorted(self.sensor_summary.items(), key=lambda x: -x[1]):
            bar = "▓" * int(prob * 4) + "░" * (4 - int(prob * 4))
            lines.append(f"  {sensor}: {bar} {prob:.2f}")

        lines.extend([
            "",
            "Stance:",
            f"  valence={self.stance.valence:+.2f} arousal={self.stance.arousal:.2f} control={self.stance.control:.2f}",
            f"  certainty={self.stance.certainty:.2f} safety={self.stance.safety:.2f} closeness={self.stance.closeness:.2f}",
            f"  curiosity={self.stance.curiosity:.2f} strain={self.stance.strain:.2f}",
            f"  → readiness={self.stance.readiness_to_speak:.2f} advice_suppression={self.stance.advice_suppression:.2f}",
        ])

        if self.micro_agent_highlights:
            lines.extend(["", "Agent Glimpses:"])
            for h in sorted(self.micro_agent_highlights, key=lambda x: -x.salience)[:5]:
                if h.glimpse:
                    lines.append(f"  [{h.agent}] {h.glimpse}")

        if self.collected_questions:
            lines.extend(["", "Top Questions:"])
            for q in sorted(self.collected_questions, key=lambda x: -x.priority)[:3]:
                lines.append(f"  - {q.question}")

        if self.relationship_summary and self.relationship_summary.summary:
            lines.extend(["", f"Relationship: {self.relationship_summary.summary}"])

        return "\n".join(lines)


def create_empty_workspace(turn_id: int, user_text: str) -> WorkspacePacket:
    """Create an empty workspace packet for a new turn."""
    return WorkspacePacket(
        turn_id=turn_id,
        user_text=user_text,
        cues=CueExtraction(),
    )
