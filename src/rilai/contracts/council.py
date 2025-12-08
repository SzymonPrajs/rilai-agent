"""Council contracts - decision making and voice rendering."""

from enum import Enum
from typing import Literal
from pydantic import BaseModel, Field


class ResponseUrgency(str, Enum):
    """Urgency level for response."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SpeechAct(BaseModel):
    """What to say and how to say it.

    This is the council's decision about response content,
    before it's rendered to natural language.
    """

    intent: str = Field(
        default="observe",
        description="Response intent: witness, guide, clarify, protect, celebrate, observe"
    )
    key_points: list[str] = Field(
        default_factory=list,
        description="Main points to convey"
    )
    tone: str = Field(
        default="warm",
        description="Tone to use: warm, concerned, playful, serious, etc."
    )
    do_not: list[str] = Field(
        default_factory=list,
        description="Things to avoid saying/doing"
    )
    asks_user: list[str] | None = Field(
        default=None,
        description="Questions to ask user"
    )


class CouncilDecision(BaseModel):
    """The council's decision for this turn.

    Determines whether to speak and what to say.
    """

    speak: bool = Field(description="Whether to generate a response")
    urgency: Literal["low", "medium", "high", "critical"] = Field(
        default="medium",
        description="Response urgency"
    )
    speech_act: SpeechAct = Field(
        default_factory=SpeechAct,
        description="What to say"
    )
    needs_clarification: str | None = Field(
        default=None,
        description="Question to ask if unclear"
    )
    thinking: str | None = Field(
        default=None,
        description="Reasoning trace (stored for debugging)"
    )
    deliberation_rounds: int = Field(
        default=0,
        description="How many deliberation rounds occurred"
    )
    final_consensus: float = Field(
        default=0.0,
        ge=0.0, le=1.0,
        description="Final consensus level"
    )


class VoiceResult(BaseModel):
    """Result of voice rendering.

    The natural language response generated from speech_act.
    """

    text: str = Field(description="The response text")
    rendered: bool = Field(default=True, description="Whether rendering occurred")
    token_count: int = Field(default=0, description="Token count")
    processing_time_ms: int = Field(
        default=0,
        description="Time to generate"
    )
    model_used: str = Field(
        default="",
        description="Model used for rendering"
    )
    speech_act: SpeechAct | None = Field(
        default=None,
        description="The speech act that guided rendering"
    )
    reasoning: str | None = Field(
        default=None,
        description="Model reasoning (if available)"
    )


class CriticResult(BaseModel):
    """Result from a post-generation critic."""

    critic: str = Field(description="Critic name")
    passed: bool = Field(description="Whether validation passed")
    reason: str = Field(
        default="",
        description="Explanation if failed"
    )
    severity: Literal["info", "warning", "error", "critical"] = Field(
        default="info",
        description="Severity if failed"
    )
    suggestions: list[str] = Field(
        default_factory=list,
        description="Suggested fixes"
    )
