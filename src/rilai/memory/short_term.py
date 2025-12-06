"""Short-term memory using JSON files.

Stores current session data in JSON format for easy inspection and debugging.
Data is temporary and can be cleared between sessions.
"""

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from rilai.config import get_config


@dataclass
class StoredMessage:
    """A message stored in short-term memory."""

    role: str
    content: str
    timestamp: str
    urgency: str | None = None
    thinking: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class StoredTurn:
    """A turn stored in short-term memory."""

    turn_id: str
    user_input: str
    response: str | None
    total_time_ms: int
    council_speak: bool
    council_urgency: str | None
    timestamp: str
    agent_assessments: list[dict] = field(default_factory=list)
    council_decision: dict | None = None
    deliberation_rounds: list[dict] = field(default_factory=list)


@dataclass
class SessionData:
    """Current session data."""

    session_id: str
    started_at: str
    user_id: str
    messages: list[StoredMessage] = field(default_factory=list)
    turns: list[str] = field(default_factory=list)  # Turn IDs
    metadata: dict = field(default_factory=dict)


class ShortTermMemory:
    """JSON file-based short-term memory.

    Structure:
        data/current/
        ├── session.json          # Session metadata
        ├── messages.json         # Conversation messages
        ├── turns/{id}.json       # Per-turn traces
        └── agents/{id}.json      # Per-agent history
    """

    def __init__(self, data_dir: Path | None = None):
        """Initialize short-term memory.

        Args:
            data_dir: Base data directory. If None, uses config.
        """
        if data_dir is None:
            config = get_config()
            data_dir = Path(config.DATA_DIR)

        self.data_dir = data_dir
        self.current_dir = data_dir / "current"
        self.turns_dir = self.current_dir / "turns"
        self.agents_dir = self.current_dir / "agents"

        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        """Ensure all directories exist."""
        self.current_dir.mkdir(parents=True, exist_ok=True)
        self.turns_dir.mkdir(exist_ok=True)
        self.agents_dir.mkdir(exist_ok=True)

    def _read_json(self, path: Path) -> dict | list | None:
        """Read JSON file, return None if not exists."""
        if not path.exists():
            return None
        with open(path) as f:
            return json.load(f)

    def _write_json(self, path: Path, data: Any) -> None:
        """Write data to JSON file."""
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)

    # Session operations

    def create_session(self, session_id: str, user_id: str = "default") -> SessionData:
        """Create a new session."""
        session = SessionData(
            session_id=session_id,
            started_at=datetime.now().isoformat(),
            user_id=user_id,
        )
        self._write_json(self.current_dir / "session.json", asdict(session))
        self._write_json(self.current_dir / "messages.json", [])
        return session

    def get_session(self) -> SessionData | None:
        """Get current session."""
        data = self._read_json(self.current_dir / "session.json")
        if data is None:
            return None
        return SessionData(**data)

    def update_session(self, **kwargs) -> None:
        """Update session metadata."""
        session = self.get_session()
        if session is None:
            return
        for key, value in kwargs.items():
            if hasattr(session, key):
                setattr(session, key, value)
        self._write_json(self.current_dir / "session.json", asdict(session))

    # Message operations

    def add_message(
        self,
        role: str,
        content: str,
        urgency: str | None = None,
        thinking: str | None = None,
        metadata: dict | None = None,
    ) -> StoredMessage:
        """Add a message to the conversation."""
        message = StoredMessage(
            role=role,
            content=content,
            timestamp=datetime.now().isoformat(),
            urgency=urgency,
            thinking=thinking,
            metadata=metadata or {},
        )

        messages = self._read_json(self.current_dir / "messages.json") or []
        messages.append(asdict(message))
        self._write_json(self.current_dir / "messages.json", messages)

        return message

    def get_messages(self, limit: int | None = None) -> list[StoredMessage]:
        """Get conversation messages."""
        messages = self._read_json(self.current_dir / "messages.json") or []
        if limit is not None:
            messages = messages[-limit:]
        return [StoredMessage(**m) for m in messages]

    def get_messages_as_dicts(self, limit: int | None = None) -> list[dict]:
        """Get messages as simple dicts for LLM context."""
        messages = self._read_json(self.current_dir / "messages.json") or []
        if limit is not None:
            messages = messages[-limit:]
        return [{"role": m["role"], "content": m["content"]} for m in messages]

    # Turn operations

    def save_turn(self, turn: StoredTurn) -> None:
        """Save a turn trace."""
        self._write_json(self.turns_dir / f"{turn.turn_id}.json", asdict(turn))

        # Update session with turn ID
        session = self.get_session()
        if session and turn.turn_id not in session.turns:
            session.turns.append(turn.turn_id)
            self._write_json(self.current_dir / "session.json", asdict(session))

    def get_turn(self, turn_id: str) -> StoredTurn | None:
        """Get a turn by ID."""
        data = self._read_json(self.turns_dir / f"{turn_id}.json")
        if data is None:
            return None
        return StoredTurn(**data)

    def get_recent_turns(self, limit: int = 10) -> list[StoredTurn]:
        """Get recent turns."""
        session = self.get_session()
        if session is None:
            return []

        turns = []
        for turn_id in session.turns[-limit:]:
            turn = self.get_turn(turn_id)
            if turn:
                turns.append(turn)
        return turns

    # Agent history operations

    def add_agent_assessment(
        self,
        agent_id: str,
        output: str,
        urgency: int = 0,
        confidence: int = 0,
        thinking: str | None = None,
        processing_time_ms: int = 0,
    ) -> None:
        """Add an agent assessment to history."""
        path = self.agents_dir / f"{agent_id.replace('.', '_')}.json"
        history = self._read_json(path) or []

        history.append(
            {
                "output": output,
                "urgency": urgency,
                "confidence": confidence,
                "thinking": thinking,
                "processing_time_ms": processing_time_ms,
                "timestamp": datetime.now().isoformat(),
            }
        )

        # Keep only last 50 assessments per agent
        if len(history) > 50:
            history = history[-50:]

        self._write_json(path, history)

    def get_agent_history(
        self, agent_id: str, limit: int = 10
    ) -> list[dict]:
        """Get recent assessments for an agent."""
        path = self.agents_dir / f"{agent_id.replace('.', '_')}.json"
        history = self._read_json(path) or []
        return history[-limit:]

    # Clearing operations

    def clear_current(self) -> None:
        """Clear current session data (keeps structure)."""
        import shutil

        if self.current_dir.exists():
            shutil.rmtree(self.current_dir)
        self._ensure_dirs()

    def clear_all(self) -> None:
        """Clear all short-term data."""
        import shutil

        if self.data_dir.exists():
            for item in self.data_dir.iterdir():
                if item.is_dir() and item.name != "rilai.db":
                    shutil.rmtree(item)
                elif item.is_file() and item.suffix == ".json":
                    item.unlink()
        self._ensure_dirs()

    # Export operations

    def export_conversation(self) -> dict:
        """Export current conversation for backup."""
        return {
            "session": asdict(self.get_session()) if self.get_session() else None,
            "messages": self._read_json(self.current_dir / "messages.json") or [],
            "exported_at": datetime.now().isoformat(),
        }

    def export_to_markdown(self) -> str:
        """Export conversation as markdown."""
        messages = self.get_messages()
        lines = ["# Conversation Export\n"]
        lines.append(f"Exported: {datetime.now().isoformat()}\n")

        for msg in messages:
            role = msg.role.capitalize()
            lines.append(f"## {role}\n")
            lines.append(f"*{msg.timestamp}*\n")
            lines.append(f"{msg.content}\n")

        return "\n".join(lines)
