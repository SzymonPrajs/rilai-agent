"""
Workspace Packet - The Global Broadcast Bottleneck

Based on Global Workspace Theory (GWT/GNW), this is the single canonical object
that all downstream modules receive after Pass 1 completes.

The workspace packet is built by the workspace builder (medium tier) and then
broadcast to all focused generators in Pass 2. This ensures global coherence
through reentrant conditioning.

Extended with AmbientContext for ambient cognitive processing mode.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Literal, Optional

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


# ============================================================================
# AMBIENT CONTEXT TYPES
# ============================================================================


@dataclass
class Commitment:
    """A commitment or TODO extracted from ambient stream."""

    id: str
    text: str
    deadline: datetime | None = None
    status: Literal["open", "completed", "abandoned", "delegated"] = "open"
    evidence_id: str = ""  # Link to source evidence
    confidence: float = 0.5
    extracted_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "text": self.text,
            "deadline": self.deadline.isoformat() if self.deadline else None,
            "status": self.status,
            "evidence_id": self.evidence_id,
            "confidence": self.confidence,
            "extracted_at": self.extracted_at.isoformat(),
        }


@dataclass
class Decision:
    """An unresolved decision detected in ambient stream."""

    id: str
    topic: str
    options: list[str] = field(default_factory=list)
    user_leaning: str | None = None
    evidence_ids: list[str] = field(default_factory=list)
    extracted_at: datetime = field(default_factory=datetime.now)
    resolution: str | None = None  # Filled when resolved

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "topic": self.topic,
            "options": self.options,
            "user_leaning": self.user_leaning,
            "evidence_ids": self.evidence_ids,
            "extracted_at": self.extracted_at.isoformat(),
            "resolution": self.resolution,
        }


@dataclass
class PendingNudge:
    """A nudge waiting to be delivered."""

    id: str
    nudge_type: str  # reminder, reflection_prompt, connection, celebration
    message: str
    evidence_chain: list[str] = field(default_factory=list)
    confidence: float = 0.5
    level: int = 1  # 0-4 proactive ladder level
    created_at: datetime = field(default_factory=datetime.now)
    expires_at: datetime | None = None
    delivered: bool = False
    delivered_at: datetime | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "nudge_type": self.nudge_type,
            "message": self.message,
            "evidence_chain": self.evidence_chain,
            "confidence": self.confidence,
            "level": self.level,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "delivered": self.delivered,
            "delivered_at": self.delivered_at.isoformat() if self.delivered_at else None,
        }


@dataclass
class AmbientContext:
    """Context from ambient mode processing.

    Contains:
    - Episode tracking (current episode state)
    - Stakes tracking (rolling stakes estimates)
    - Open loops (commitments, decisions)
    - Daydream state (hypotheses, pending nudges)
    """

    # Episode tracking
    current_episode_id: str = ""
    episode_started_at: datetime | None = None
    episode_summary: str = ""

    # Stakes tracking
    current_stakes: float = 0.0
    stakes_history: list[tuple[datetime, float]] = field(default_factory=list)
    stakes_trend: Literal["rising", "stable", "falling"] = "stable"

    # Open loops
    active_commitments: list[Commitment] = field(default_factory=list)
    unresolved_decisions: list[Decision] = field(default_factory=list)
    recent_closures: list[str] = field(default_factory=list)  # IDs of recently resolved

    # Daydream state
    active_hypotheses: list[Hypothesis] = field(default_factory=list)
    hypothesis_evidence_map: dict[str, list[str]] = field(default_factory=dict)
    pending_verifications: list[str] = field(default_factory=list)

    # Proactive state
    pending_nudges: list[PendingNudge] = field(default_factory=list)
    last_nudge_delivered: datetime | None = None
    nudge_cooldown_until: datetime | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "current_episode_id": self.current_episode_id,
            "episode_started_at": (
                self.episode_started_at.isoformat() if self.episode_started_at else None
            ),
            "episode_summary": self.episode_summary,
            "current_stakes": self.current_stakes,
            "stakes_history": [
                (ts.isoformat(), stakes) for ts, stakes in self.stakes_history[-10:]
            ],
            "stakes_trend": self.stakes_trend,
            "active_commitments": [c.to_dict() for c in self.active_commitments],
            "unresolved_decisions": [d.to_dict() for d in self.unresolved_decisions],
            "recent_closures": self.recent_closures,
            "active_hypotheses": [
                {"h_id": h.h_id, "text": h.text, "p": h.p, "evidence_ids": h.evidence_ids}
                for h in self.active_hypotheses
            ],
            "hypothesis_evidence_map": self.hypothesis_evidence_map,
            "pending_verifications": self.pending_verifications,
            "pending_nudges": [n.to_dict() for n in self.pending_nudges],
            "last_nudge_delivered": (
                self.last_nudge_delivered.isoformat() if self.last_nudge_delivered else None
            ),
            "nudge_cooldown_until": (
                self.nudge_cooldown_until.isoformat() if self.nudge_cooldown_until else None
            ),
        }

    def update_stakes(self, stakes: float) -> None:
        """Update stakes and compute trend."""
        now = datetime.now()
        self.stakes_history.append((now, stakes))

        # Keep last 10 entries
        if len(self.stakes_history) > 10:
            self.stakes_history = self.stakes_history[-10:]

        # Compute trend
        if len(self.stakes_history) >= 3:
            recent = [s for _, s in self.stakes_history[-3:]]
            if recent[-1] > recent[0] + 0.1:
                self.stakes_trend = "rising"
            elif recent[-1] < recent[0] - 0.1:
                self.stakes_trend = "falling"
            else:
                self.stakes_trend = "stable"

        self.current_stakes = stakes

    def add_commitment(self, commitment: Commitment) -> None:
        """Add an active commitment."""
        self.active_commitments.append(commitment)

    def add_decision(self, decision: Decision) -> None:
        """Add an unresolved decision."""
        self.unresolved_decisions.append(decision)

    def add_nudge(self, nudge: PendingNudge) -> None:
        """Add a pending nudge."""
        self.pending_nudges.append(nudge)

    def get_high_confidence_hypotheses(self, threshold: float = 0.7) -> list[Hypothesis]:
        """Get hypotheses above confidence threshold."""
        return [h for h in self.active_hypotheses if h.p >= threshold]

    def get_urgent_commitments(self) -> list[Commitment]:
        """Get commitments with upcoming deadlines."""
        now = datetime.now()
        urgent = []
        for c in self.active_commitments:
            if c.status == "open" and c.deadline:
                hours_until = (c.deadline - now).total_seconds() / 3600
                if hours_until < 24:
                    urgent.append(c)
        return urgent


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

    # Ambient context (populated in ambient mode)
    ambient: Optional[AmbientContext] = None

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
            "ambient": self.ambient.to_dict() if self.ambient else None,
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

        # Ambient context
        if self.ambient:
            lines.extend(["", "Ambient Context:"])
            lines.append(f"  Stakes: {self.ambient.current_stakes:.2f} ({self.ambient.stakes_trend})")

            if self.ambient.active_commitments:
                lines.append(f"  Open commitments: {len(self.ambient.active_commitments)}")
                urgent = self.ambient.get_urgent_commitments()
                if urgent:
                    lines.append(f"  URGENT ({len(urgent)}): {urgent[0].text[:50]}...")

            if self.ambient.unresolved_decisions:
                lines.append(f"  Pending decisions: {len(self.ambient.unresolved_decisions)}")

            if self.ambient.pending_nudges:
                lines.append(f"  Pending nudges: {len(self.ambient.pending_nudges)}")

        return "\n".join(lines)


def create_empty_workspace(turn_id: int, user_text: str) -> WorkspacePacket:
    """Create an empty workspace packet for a new turn."""
    return WorkspacePacket(
        turn_id=turn_id,
        user_text=user_text,
        cues=CueExtraction(),
    )
