"""SessionProjection - conversation history and session state."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from rilai.contracts.events import EngineEvent, EventKind
from rilai.store.projections.base import Projection


@dataclass
class Message:
    """A message in conversation history."""

    role: str  # "user" or "assistant"
    content: str
    timestamp: datetime
    turn_id: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SessionProjection(Projection):
    """Maintains conversation history from events.

    This projection tracks the conversation for context building.
    """

    session_id: str = ""
    started_at: datetime | None = None
    ended_at: datetime | None = None
    messages: list[Message] = field(default_factory=list)
    turn_count: int = 0

    def reset(self) -> None:
        """Reset to initial state."""
        self.session_id = ""
        self.started_at = None
        self.ended_at = None
        self.messages.clear()
        self.turn_count = 0

    def apply(self, event: EngineEvent) -> None:
        """Apply event to update session state."""
        match event.kind:
            case EventKind.SESSION_STARTED:
                self.session_id = event.session_id
                self.started_at = event.ts_wall

            case EventKind.SESSION_ENDED:
                self.ended_at = event.ts_wall

            case EventKind.TURN_STARTED:
                user_input = event.payload.get("user_input", "")
                if user_input:
                    self.messages.append(
                        Message(
                            role="user",
                            content=user_input,
                            timestamp=event.ts_wall,
                            turn_id=event.turn_id,
                        )
                    )
                    self.turn_count += 1

            case EventKind.VOICE_RENDERED:
                text = event.payload.get("text", "")
                if text:
                    self.messages.append(
                        Message(
                            role="assistant",
                            content=text,
                            timestamp=event.ts_wall,
                            turn_id=event.turn_id,
                        )
                    )

    def get_history(self, limit: int = 20) -> list[dict]:
        """Get recent conversation history.

        Returns:
            List of {role, content, timestamp} dicts
        """
        recent = self.messages[-limit:]
        return [
            {
                "role": m.role,
                "content": m.content,
                "timestamp": m.timestamp.isoformat(),
            }
            for m in recent
        ]

    def get_last_user_message(self) -> str | None:
        """Get the most recent user message."""
        for m in reversed(self.messages):
            if m.role == "user":
                return m.content
        return None

    def get_last_assistant_message(self) -> str | None:
        """Get the most recent assistant message."""
        for m in reversed(self.messages):
            if m.role == "assistant":
                return m.content
        return None
