"""Memory contracts - episodic events, user facts, candidates."""

from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field


class MemoryCandidate(BaseModel):
    """Something an agent thinks should be remembered.

    Agents propose memory candidates; the memory system decides
    what actually gets committed.
    """

    type: Literal["episodic", "fact", "goal", "session_note"] = Field(
        description="What kind of memory"
    )
    content: str = Field(description="What to remember")
    importance: float = Field(
        default=0.5,
        ge=0.0, le=1.0,
        description="How important (0-1)"
    )
    confidence: float = Field(
        default=0.5,
        ge=0.0, le=1.0,
        description="Confidence in this memory"
    )
    source_agent: str = Field(description="Agent that proposed this")
    category: str | None = Field(
        default=None,
        description="Category for facts"
    )
    emotions: list[str] | None = Field(
        default=None,
        description="Emotions for episodic"
    )
    topics: list[str] | None = Field(
        default=None,
        description="Topics for episodic"
    )
    goal_id: str | None = Field(
        default=None,
        description="Goal ID for updates"
    )
    goal_progress: float | None = Field(
        default=None,
        description="Goal progress"
    )
    goal_priority: int | None = Field(
        default=None,
        description="Goal priority"
    )
    context: dict | None = Field(
        default=None,
        description="Additional context"
    )


class EpisodicEvent(BaseModel):
    """A significant moment to remember.

    Episodic memory captures what happened, when, and how it felt.
    """

    id: str | None = Field(default=None, description="UUID")
    timestamp: datetime = Field(
        default_factory=datetime.now,
        description="When this happened"
    )
    summary: str = Field(
        max_length=500,
        description="What happened (max 500 chars)"
    )
    emotions: list[str] = Field(
        default_factory=list,
        description="Emotions involved"
    )
    topics: list[str] = Field(
        default_factory=list,
        description="Topics discussed"
    )
    participants: list[str] = Field(
        default_factory=list,
        description="Who was involved (user, rilai)"
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Categorization tags"
    )
    importance: float = Field(
        default=0.5,
        ge=0.0, le=1.0,
        description="How significant"
    )
    embedding: list[float] | None = Field(
        default=None,
        description="Semantic embedding vector"
    )
    turn_id: int | None = Field(
        default=None,
        description="Which turn this came from"
    )
    session_id: str | None = Field(
        default=None,
        description="Which session"
    )


class UserFact(BaseModel):
    """A fact about the user.

    User model facts are hypotheses about user preferences, boundaries,
    communication style, etc.
    """

    id: str | None = Field(default=None, description="UUID")
    text: str = Field(
        max_length=300,
        description="The fact text (max 300 chars)"
    )
    category: str = Field(
        default="general",
        description="Fact category: preference, boundary, background, trigger, general"
    )
    confidence: float = Field(
        default=0.5,
        ge=0.0, le=1.0,
        description="How confident we are"
    )
    source: str | None = Field(
        default=None,
        description="Where this came from (turn_id, inference, etc.)"
    )
    first_seen: datetime | None = Field(
        default=None,
        description="When first observed"
    )
    last_updated: datetime | None = Field(
        default=None,
        description="When last confirmed"
    )
    mention_count: int = Field(
        default=1,
        description="How many times we've seen evidence"
    )


class Goal(BaseModel):
    """An active user goal or thread."""

    id: str | None = Field(default=None, description="UUID")
    text: str = Field(description="Goal description")
    status: str = Field(
        default="open",
        description="Status: open, completed, abandoned"
    )
    created_at: datetime | None = Field(
        default=None,
        description="When created"
    )
    deadline: datetime | None = Field(
        default=None,
        description="Optional deadline"
    )
    priority: int = Field(
        default=1,
        description="Priority 1-5"
    )
    progress: float = Field(
        default=0.0,
        ge=0.0, le=1.0,
        description="Progress 0-1"
    )
    notes: str | None = Field(
        default=None,
        description="Notes"
    )
