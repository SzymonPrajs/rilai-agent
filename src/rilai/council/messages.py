"""Message types for council deliberation.

Defines the structured output types for:
- Multi-round deliberation (agents hearing each other)
- Decision/voice split architecture
- Council synthesis
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from rilai.agencies.messages import SalienceMetadata


# =============================================================================
# Multi-Round Deliberation Types
# =============================================================================


@dataclass
class AgentVoice:
    """Agent's position in deliberation.

    During multi-round deliberation, agents can:
    - maintain: Keep their original position
    - adjust: Modify position based on other agents' input
    - defer: Yield to another agent's stronger argument
    - dissent: Explicitly disagree with emerging consensus
    """

    agent_id: str
    content: str  # What the agent says
    stance: Literal["maintain", "adjust", "defer", "dissent"]
    salience: SalienceMetadata
    reasoning: str | None = None  # Why this position
    addressed_agents: list[str] = field(default_factory=list)  # Which agents influenced this

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "agent_id": self.agent_id,
            "content": self.content,
            "stance": self.stance,
            "salience": {
                "urgency": self.salience.urgency,
                "confidence": self.salience.confidence,
            },
            "reasoning": self.reasoning,
            "addressed_agents": self.addressed_agents,
        }


@dataclass
class DeliberationRound:
    """Record of a single deliberation round.

    Captures all agent voices and metadata for a round.
    """

    round_number: int
    voices: dict[str, AgentVoice]  # agent_id → voice
    consensus_level: float  # 0-1, how aligned agents are
    speaking_pressure: float  # accumulated urgency
    timestamp: datetime = field(default_factory=datetime.now)

    def get_majority_stance(self) -> str:
        """Get the most common stance among agents."""
        stance_counts: dict[str, int] = {}
        for voice in self.voices.values():
            stance_counts[voice.stance] = stance_counts.get(voice.stance, 0) + 1
        if not stance_counts:
            return "maintain"
        return max(stance_counts.items(), key=lambda x: x[1])[0]

    def has_dissent(self) -> bool:
        """Check if any agent is dissenting."""
        return any(v.stance == "dissent" for v in self.voices.values())


@dataclass
class DeliberationContext:
    """Context for multi-round deliberation.

    Passed to agents during deliberation rounds so they can
    see what other agents have said.
    """

    round: int
    previous_voices: dict[str, AgentVoice]  # agent_id → their last statement
    consensus_level: float  # 0-1, how aligned are agents
    speaking_pressure: float  # accumulated urgency
    max_rounds: int = 3

    @property
    def is_final_round(self) -> bool:
        """Check if this is the last allowed round."""
        return self.round >= self.max_rounds

    def format_for_prompt(self) -> str:
        """Format context for inclusion in agent prompts."""
        if not self.previous_voices:
            return "(This is the first round - no previous statements)"

        lines = [f"Round {self.round} of {self.max_rounds}"]
        lines.append(f"Consensus level: {self.consensus_level:.1%}")
        lines.append(f"Speaking pressure: {self.speaking_pressure:.1%}")
        lines.append("")
        lines.append("Previous statements from other agents:")

        for agent_id, voice in self.previous_voices.items():
            stance_emoji = {
                "maintain": "→",
                "adjust": "↔",
                "defer": "↓",
                "dissent": "⚡",
            }.get(voice.stance, "?")
            lines.append(f"  {stance_emoji} {agent_id}: {voice.content}")
            if voice.addressed_agents:
                lines.append(f"    (responding to: {', '.join(voice.addressed_agents)})")

        return "\n".join(lines)


# =============================================================================
# Speech Act Types
# =============================================================================


@dataclass
class SpeechAct:
    """Structured speech intent with constraints.

    Produced by the synthesizer when speak=True.
    Consumed by the voice renderer to produce final text.
    """

    intent: Literal["reflect", "nudge", "warn", "ask", "summarize"]
    """What kind of speech act this is:
    - reflect: Mirror back what was observed/understood
    - nudge: Gently suggest a direction or consideration
    - warn: Flag a concern or risk
    - ask: Request clarification or more information
    - summarize: Synthesize multiple perspectives into coherent summary
    """

    key_points: list[str]
    """2-5 bullet points of content to communicate.
    The voice renderer must include all of these.
    """

    tone: Literal["warm", "direct", "playful", "solemn"]
    """The emotional coloring of the response:
    - warm: Empathetic, caring, supportive
    - direct: Clear, efficient, no-frills
    - playful: Light, humorous, casual
    - solemn: Serious, measured, thoughtful
    """

    do_not: list[str] = field(default_factory=list)
    """Constraints on what NOT to say.
    E.g., "don't sound clinical", "don't mention specific agents"
    """

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "intent": self.intent,
            "key_points": self.key_points,
            "tone": self.tone,
            "do_not": self.do_not,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SpeechAct":
        """Create from dictionary."""
        return cls(
            intent=data.get("intent", "reflect"),
            key_points=data.get("key_points", []),
            tone=data.get("tone", "warm"),
            do_not=data.get("do_not", []),
        )


# =============================================================================
# Council Decision Types
# =============================================================================


@dataclass
class CouncilDecision:
    """Output from council synthesis.

    The council decides whether to speak and produces a structured SpeechAct.
    The Voice renderer transforms SpeechAct into final natural language.
    """

    speak: bool  # Should I say something?
    urgency: Literal["low", "medium", "high", "critical"]  # How urgent
    speech_act: SpeechAct | None  # Structured intent (if speak=True)
    message: str  # Final rendered message (populated by Voice)
    internal_state: str  # Internal reasoning for debug
    thinking: str  # Model's reasoning process (from thinking models or <thinking> tags)
    processing_time_ms: int
    timestamp: datetime = field(default_factory=datetime.now)

    # Deliberation metadata (if multi-round was used)
    deliberation_rounds: int = 0
    final_consensus: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "speak": self.speak,
            "urgency": self.urgency,
            "speech_act": self.speech_act.to_dict() if self.speech_act else None,
            "message": self.message,
            "internal_state": self.internal_state,
            "thinking": self.thinking,
            "processing_time_ms": self.processing_time_ms,
            "timestamp": self.timestamp.isoformat(),
            "deliberation_rounds": self.deliberation_rounds,
            "final_consensus": self.final_consensus,
        }


# Backwards compatibility alias
SynthesisResult = CouncilDecision


@dataclass
class VoiceResult:
    """Output from voice rendering."""

    message: str
    """The final natural language message."""

    processing_time_ms: int
    timestamp: datetime = field(default_factory=datetime.now)


# =============================================================================
# Self-Model Types
# =============================================================================


@dataclass
class SelfModelView:
    """Read-only view of self-model for injection into prompts.

    Lighter-weight than full SelfModel, just what's needed for rendering.
    """

    name: str = "Rilai"
    """The name to use for self-reference."""

    tone_defaults: dict[str, str] = field(
        default_factory=lambda: {
            "baseline": "warm",
            "under_stress": "solemn",
            "playful_context": "playful",
        }
    )
    """Default tone mappings for different contexts."""

    user_preferences: dict[str, Any] = field(default_factory=dict)
    """Learned user preferences that affect communication style.
    E.g., {"verbosity": "concise", "formality": "casual"}
    """

    relationship_context: str = ""
    """Brief description of the relationship context.
    E.g., "We've been talking for 3 days. User prefers direct feedback."
    """

    boundaries_summary: str = ""
    """Summary of key boundaries for quick reference."""

    def to_prompt_section(self) -> str:
        """Format self-model for inclusion in prompts."""
        prefs = (
            ", ".join(f"{k}: {v}" for k, v in self.user_preferences.items())
            if self.user_preferences
            else "(none)"
        )

        return f"""Name: {self.name}
Default tone: {self.tone_defaults.get('baseline', 'warm')}
User preferences: {prefs}
Relationship: {self.relationship_context or '(building relationship)'}
Boundaries: {self.boundaries_summary or '(standard)'}"""
