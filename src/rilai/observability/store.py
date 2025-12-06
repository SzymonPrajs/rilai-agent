"""Unified store for logging to both SQLite and JSON.

Provides a single interface for all storage operations, automatically
writing to both permanent (SQLite) and temporary (JSON) storage.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from rilai.config import get_config
from rilai.memory.database import Database
from rilai.memory.short_term import ShortTermMemory, StoredTurn


@dataclass
class TurnContext:
    """Context for tracking a processing turn."""

    turn_id: int
    turn_uuid: str
    session_id: str
    user_input: str
    start_time: datetime


class Store:
    """Unified store for all Rilai data.

    Automatically logs to both SQLite (permanent) and JSON (temporary).
    Provides a consistent interface for:
    - Sessions
    - Messages
    - Turns
    - Agent calls
    - Model calls
    - Council decisions
    - Deliberation rounds
    """

    def __init__(
        self,
        data_dir: Path | None = None,
        enable_sqlite: bool = True,
        enable_json: bool = True,
    ):
        """Initialize the store.

        Args:
            data_dir: Base data directory. If None, uses config.
            enable_sqlite: Whether to write to SQLite.
            enable_json: Whether to write to JSON files.
        """
        if data_dir is None:
            config = get_config()
            data_dir = Path(config.DATA_DIR)

        self.data_dir = data_dir
        self.enable_sqlite = enable_sqlite
        self.enable_json = enable_json

        if enable_sqlite:
            self.db = Database(data_dir / "rilai.db")
        else:
            self.db = None

        if enable_json:
            self.stm = ShortTermMemory(data_dir)
        else:
            self.stm = None

        self._current_session_id: str | None = None
        self._current_turn: TurnContext | None = None

    # Session operations

    def start_session(
        self, session_id: str | None = None, user_id: str = "default"
    ) -> str:
        """Start a new session."""
        if session_id is None:
            session_id = str(uuid.uuid4())

        self._current_session_id = session_id

        if self.db:
            self.db.create_session(session_id)
        if self.stm:
            self.stm.create_session(session_id, user_id)

        return session_id

    def end_session(self) -> None:
        """End the current session."""
        if self._current_session_id and self.db:
            self.db.end_session(self._current_session_id)
        self._current_session_id = None

    @property
    def session_id(self) -> str | None:
        """Get current session ID."""
        return self._current_session_id

    # Message operations

    def add_message(
        self,
        role: str,
        content: str,
        urgency: str | None = None,
        thinking: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        """Add a message to the conversation."""
        if not self._current_session_id:
            return

        if self.db:
            self.db.add_message(
                self._current_session_id,
                role,
                content,
                urgency,
                thinking,
            )

        if self.stm:
            self.stm.add_message(role, content, urgency, thinking, metadata)

    def get_conversation_history(self, limit: int = 20) -> list[dict]:
        """Get recent conversation messages."""
        if self.stm:
            return self.stm.get_messages_as_dicts(limit)
        return []

    # Turn operations

    def start_turn(self, user_input: str) -> TurnContext:
        """Start tracking a new turn."""
        if not self._current_session_id:
            self.start_session()

        turn_uuid = str(uuid.uuid4())[:8]

        turn_id = 0
        if self.db:
            turn_id = self.db.create_turn(
                self._current_session_id,
                user_input,
            )

        self._current_turn = TurnContext(
            turn_id=turn_id,
            turn_uuid=turn_uuid,
            session_id=self._current_session_id,
            user_input=user_input,
            start_time=datetime.now(),
        )

        return self._current_turn

    def end_turn(
        self,
        council_speak: bool,
        council_urgency: str | None = None,
        response: str | None = None,
    ) -> None:
        """End the current turn."""
        if not self._current_turn:
            return

        total_time_ms = int(
            (datetime.now() - self._current_turn.start_time).total_seconds() * 1000
        )

        if self.db:
            self.db.update_turn(
                self._current_turn.turn_id,
                total_time_ms=total_time_ms,
                council_speak=council_speak,
                council_urgency=council_urgency,
            )

        if self.stm:
            turn = StoredTurn(
                turn_id=self._current_turn.turn_uuid,
                user_input=self._current_turn.user_input,
                response=response,
                total_time_ms=total_time_ms,
                council_speak=council_speak,
                council_urgency=council_urgency,
                timestamp=self._current_turn.start_time.isoformat(),
            )
            self.stm.save_turn(turn)

        self._current_turn = None

    @property
    def current_turn_id(self) -> int | None:
        """Get current turn's database ID."""
        return self._current_turn.turn_id if self._current_turn else None

    # Agent call operations

    def log_agent_call(
        self,
        agent_id: str,
        output: str,
        thinking: str | None = None,
        urgency: int = 0,
        confidence: int = 0,
        processing_time_ms: int = 0,
    ) -> int | None:
        """Log an agent call."""
        agent_call_id = None

        if self.db and self._current_turn:
            agent_call_id = self.db.add_agent_call(
                self._current_turn.turn_id,
                agent_id,
                output,
                thinking,
                urgency,
                confidence,
                processing_time_ms,
            )

        if self.stm:
            self.stm.add_agent_assessment(
                agent_id,
                output,
                urgency,
                confidence,
                thinking,
                processing_time_ms,
            )

        return agent_call_id

    # Model call operations

    def log_model_call(
        self,
        model: str,
        messages: list[dict],
        response: str,
        latency_ms: int,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        reasoning_tokens: int | None = None,
        agent_call_id: int | None = None,
        council_call_id: int | None = None,
    ) -> int | None:
        """Log a model API call."""
        if self.db:
            return self.db.add_model_call(
                model,
                messages,
                response,
                latency_ms,
                prompt_tokens,
                completion_tokens,
                reasoning_tokens,
                agent_call_id,
                council_call_id,
            )
        return None

    # Council operations

    def log_council_call(
        self,
        speak: bool,
        urgency: str,
        speech_act: dict | None = None,
        final_message: str | None = None,
        thinking: str | None = None,
        processing_time_ms: int = 0,
    ) -> int | None:
        """Log a council decision."""
        if self.db and self._current_turn:
            return self.db.add_council_call(
                self._current_turn.turn_id,
                speak,
                urgency,
                speech_act,
                final_message,
                thinking,
                processing_time_ms,
            )
        return None

    # Deliberation operations

    def log_deliberation_round(
        self,
        round_number: int,
        agent_id: str,
        voice_content: str,
        stance: str,
        urgency: int = 0,
        confidence: int = 0,
        addressed_agents: list[str] | None = None,
    ) -> None:
        """Log a deliberation round."""
        if self.db and self._current_turn:
            self.db.add_deliberation_round(
                self._current_turn.turn_id,
                round_number,
                agent_id,
                voice_content,
                stance,
                urgency,
                confidence,
                addressed_agents,
            )

    # Query operations

    def get_stats(self, hours: int = 24) -> dict[str, Any]:
        """Get statistics for the last N hours."""
        if self.db:
            return self.db.get_stats(hours)
        return {}

    def get_agent_stats(
        self, agent_id: str | None = None, limit: int = 20
    ) -> list[dict]:
        """Get per-agent statistics."""
        if self.db:
            return self.db.get_agent_stats(agent_id, limit)
        return []

    def get_recent_agent_calls(
        self, agent_id: str | None = None, limit: int = 20
    ) -> list[dict]:
        """Get recent agent calls."""
        if self.db:
            calls = self.db.get_agent_calls(agent_id=agent_id, limit=limit)
            return [
                {
                    "agent_id": c.agent_id,
                    "output": c.output[:200],
                    "urgency": c.urgency,
                    "confidence": c.confidence,
                    "time_ms": c.processing_time_ms,
                    "created_at": c.created_at.isoformat(),
                }
                for c in calls
            ]
        return []

    # Clear operations

    def clear_current(self) -> None:
        """Clear current session data (JSON only)."""
        if self.stm:
            self.stm.clear_current()

    def clear_all(self) -> None:
        """Clear all data."""
        if self.stm:
            self.stm.clear_all()
        # Note: SQLite data is not cleared, only JSON

    # Export operations

    def export_json(self) -> dict:
        """Export current conversation as JSON."""
        if self.stm:
            return self.stm.export_conversation()
        return {}

    def export_markdown(self) -> str:
        """Export current conversation as markdown."""
        if self.stm:
            return self.stm.export_to_markdown()
        return ""


# Global store instance (initialized lazily)
_store: Store | None = None


def get_store() -> Store:
    """Get global store instance."""
    global _store
    if _store is None:
        _store = Store()
    return _store


def set_store(store: Store) -> None:
    """Set global store instance (for testing)."""
    global _store
    _store = store
