"""
UserQueryEvent - Explicit user interaction event.

Separate from UtteranceEvent (ambient listening).
This is when the user explicitly asks the assistant something.
"""

from dataclasses import dataclass, field
from datetime import datetime
import uuid


@dataclass
class UserQueryEvent:
    """An explicit query from the user to the assistant.

    This is distinct from UtteranceEvent (ambient listening).
    A UserQueryEvent triggers INTERACTIVE_ASSIST mode and
    allows the system to surface queued suggestions.

    Fields:
        query_id: Unique identifier
        timestamp: When the query was made
        text: The query text ("Help me plan dinner")
        context_window: Seconds of ambient context to include (default 1 hour)
    """

    query_id: str
    timestamp: datetime
    text: str
    context_window: int = 3600  # 1 hour of context by default

    # Optional metadata
    channel: str | None = None  # Where the query was made
    urgency: str = "normal"  # "low", "normal", "high"

    @classmethod
    def create(
        cls,
        text: str,
        context_window: int = 3600,
        channel: str | None = None,
        urgency: str = "normal",
    ) -> "UserQueryEvent":
        """Factory method to create a UserQueryEvent.

        Args:
            text: The query text
            context_window: Seconds of ambient context to include
            channel: Where the query was made
            urgency: Query urgency level

        Returns:
            New UserQueryEvent instance
        """
        return cls(
            query_id=str(uuid.uuid4()),
            timestamp=datetime.now(),
            text=text,
            context_window=context_window,
            channel=channel,
            urgency=urgency,
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "query_id": self.query_id,
            "timestamp": self.timestamp.isoformat(),
            "text": self.text,
            "context_window": self.context_window,
            "channel": self.channel,
            "urgency": self.urgency,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "UserQueryEvent":
        """Create from dictionary."""
        return cls(
            query_id=data["query_id"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            text=data["text"],
            context_window=data.get("context_window", 3600),
            channel=data.get("channel"),
            urgency=data.get("urgency", "normal"),
        )

    def __repr__(self) -> str:
        return (
            f"UserQueryEvent(text={self.text[:50]!r}"
            f"{'...' if len(self.text) > 50 else ''}, "
            f"context_window={self.context_window}s)"
        )
