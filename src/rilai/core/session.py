"""Session management for Rilai v2."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from rilai.config import get_config


@dataclass
class Message:
    """A conversation message."""

    role: str  # "user" or "assistant"
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }


@dataclass
class Session:
    """A conversation session."""

    id: str
    started_at: datetime = field(default_factory=datetime.now)
    ended_at: datetime | None = None
    messages: list[Message] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def new(cls) -> "Session":
        """Create a new session."""
        return cls(id=str(uuid.uuid4()))

    def add_message(self, role: str, content: str, **metadata: Any) -> Message:
        """Add a message to the session."""
        message = Message(role=role, content=content, metadata=metadata)
        self.messages.append(message)
        return message

    def get_history(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get recent message history for context."""
        return [msg.to_dict() for msg in self.messages[-limit:]]

    def end(self) -> None:
        """End the session."""
        self.ended_at = datetime.now()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "messages": [msg.to_dict() for msg in self.messages],
            "metadata": self.metadata,
        }


class SessionManager:
    """Manages sessions and their persistence."""

    def __init__(self) -> None:
        self._current: Session | None = None
        self._config = get_config()

    @property
    def data_dir(self) -> Path:
        """Get the data directory."""
        return Path(self._config.DATA_DIR)

    @property
    def current_dir(self) -> Path:
        """Get the current session directory."""
        return self.data_dir / "current"

    @property
    def sessions_dir(self) -> Path:
        """Get the sessions archive directory."""
        return self.data_dir / "sessions"

    def ensure_dirs(self) -> None:
        """Ensure data directories exist."""
        self.current_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def get_or_create_session(self) -> Session:
        """Get current session or create a new one."""
        if self._current is None:
            self._current = Session.new()
        return self._current

    @property
    def current(self) -> Session:
        """Get the current session, creating if needed."""
        return self.get_or_create_session()

    def add_user_message(self, content: str, **metadata: Any) -> Message:
        """Add a user message to current session."""
        return self.current.add_message("user", content, **metadata)

    def add_assistant_message(self, content: str, **metadata: Any) -> Message:
        """Add an assistant message to current session."""
        return self.current.add_message("assistant", content, **metadata)

    def get_context(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get conversation context for agencies."""
        return self.current.get_history(limit)

    def clear_current(self) -> None:
        """Clear the current session."""
        if self._current:
            self._current.end()
        self._current = Session.new()

    def archive_current(self) -> None:
        """Archive the current session to sessions directory."""
        import json

        if self._current and self._current.messages:
            self.ensure_dirs()
            self._current.end()

            # Save to sessions directory
            archive_path = self.sessions_dir / f"{self._current.id}.json"
            with open(archive_path, "w") as f:
                json.dump(self._current.to_dict(), f, indent=2)

        # Start fresh
        self._current = Session.new()


# Global session manager
session_manager = SessionManager()
