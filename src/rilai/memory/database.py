"""SQLite database for permanent storage.

Stores sessions, messages, turns, agent calls, model calls, and council decisions.
"""

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Generator

from rilai.config import get_config


@dataclass
class MessageRecord:
    """A stored message."""

    id: int
    session_id: str
    role: str
    content: str
    urgency: str | None
    thinking: str | None
    created_at: datetime


@dataclass
class TurnRecord:
    """A stored turn (user input + response)."""

    id: int
    session_id: str
    user_input: str
    total_time_ms: int
    council_speak: bool
    council_urgency: str | None
    created_at: datetime


@dataclass
class AgentCallRecord:
    """A stored agent call."""

    id: int
    turn_id: int
    agent_id: str
    output: str
    thinking: str | None
    urgency: int
    confidence: int
    processing_time_ms: int
    created_at: datetime


@dataclass
class ModelCallRecord:
    """A stored model API call."""

    id: int
    agent_call_id: int | None
    council_call_id: int | None
    model: str
    messages: str  # JSON
    response: str
    latency_ms: int
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int | None
    created_at: datetime


@dataclass
class CouncilCallRecord:
    """A stored council call."""

    id: int
    turn_id: int
    speak: bool
    urgency: str
    speech_act: str | None  # JSON
    final_message: str | None
    thinking: str | None
    processing_time_ms: int
    created_at: datetime


# SQL schema for all tables
SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    metadata TEXT  -- JSON
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,  -- user, assistant, system
    content TEXT NOT NULL,
    urgency TEXT,
    thinking TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    user_input TEXT NOT NULL,
    total_time_ms INTEGER NOT NULL,
    council_speak INTEGER NOT NULL,  -- 0 or 1
    council_urgency TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS agent_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    turn_id INTEGER NOT NULL,
    agent_id TEXT NOT NULL,
    output TEXT NOT NULL,
    thinking TEXT,
    urgency INTEGER NOT NULL DEFAULT 0,
    confidence INTEGER NOT NULL DEFAULT 0,
    processing_time_ms INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (turn_id) REFERENCES turns(id)
);

CREATE TABLE IF NOT EXISTS model_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_call_id INTEGER,
    council_call_id INTEGER,
    model TEXT NOT NULL,
    messages TEXT NOT NULL,  -- JSON
    response TEXT NOT NULL,
    latency_ms INTEGER NOT NULL,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    reasoning_tokens INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY (agent_call_id) REFERENCES agent_calls(id),
    FOREIGN KEY (council_call_id) REFERENCES council_calls(id)
);

CREATE TABLE IF NOT EXISTS council_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    turn_id INTEGER NOT NULL,
    speak INTEGER NOT NULL,  -- 0 or 1
    urgency TEXT NOT NULL,
    speech_act TEXT,  -- JSON
    final_message TEXT,
    thinking TEXT,
    processing_time_ms INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (turn_id) REFERENCES turns(id)
);

CREATE TABLE IF NOT EXISTS deliberation_rounds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    turn_id INTEGER NOT NULL,
    round_number INTEGER NOT NULL,
    agent_id TEXT NOT NULL,
    voice_content TEXT NOT NULL,
    stance TEXT NOT NULL,
    urgency INTEGER NOT NULL DEFAULT 0,
    confidence INTEGER NOT NULL DEFAULT 0,
    addressed_agents TEXT,  -- JSON array
    created_at TEXT NOT NULL,
    FOREIGN KEY (turn_id) REFERENCES turns(id)
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id);
CREATE INDEX IF NOT EXISTS idx_agent_calls_turn ON agent_calls(turn_id);
CREATE INDEX IF NOT EXISTS idx_agent_calls_agent ON agent_calls(agent_id);
CREATE INDEX IF NOT EXISTS idx_model_calls_agent ON model_calls(agent_call_id);
CREATE INDEX IF NOT EXISTS idx_council_calls_turn ON council_calls(turn_id);
CREATE INDEX IF NOT EXISTS idx_deliberation_turn ON deliberation_rounds(turn_id);
"""


class Database:
    """SQLite database interface for Rilai storage."""

    def __init__(self, db_path: Path | None = None):
        """Initialize database connection.

        Args:
            db_path: Path to SQLite database file. If None, uses config.
        """
        if db_path is None:
            config = get_config()
            db_path = Path(config.DATA_DIR) / "rilai.db"

        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        """Initialize database schema."""
        with self._connection() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Get a database connection with proper cleanup."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # Session operations

    def create_session(self, session_id: str, metadata: dict | None = None) -> None:
        """Create a new session."""
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO sessions (id, started_at, metadata) VALUES (?, ?, ?)",
                (session_id, datetime.now().isoformat(), json.dumps(metadata or {})),
            )

    def end_session(self, session_id: str) -> None:
        """Mark a session as ended."""
        with self._connection() as conn:
            conn.execute(
                "UPDATE sessions SET ended_at = ? WHERE id = ?",
                (datetime.now().isoformat(), session_id),
            )

    def get_session(self, session_id: str) -> dict | None:
        """Get session by ID."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if row:
                return dict(row)
            return None

    # Message operations

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        urgency: str | None = None,
        thinking: str | None = None,
    ) -> int:
        """Add a message to a session."""
        with self._connection() as conn:
            cursor = conn.execute(
                """INSERT INTO messages (session_id, role, content, urgency, thinking, created_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (session_id, role, content, urgency, thinking, datetime.now().isoformat()),
            )
            return cursor.lastrowid

    def get_messages(
        self, session_id: str, limit: int = 100
    ) -> list[MessageRecord]:
        """Get messages for a session."""
        with self._connection() as conn:
            rows = conn.execute(
                """SELECT * FROM messages WHERE session_id = ?
                ORDER BY created_at DESC LIMIT ?""",
                (session_id, limit),
            ).fetchall()
            return [
                MessageRecord(
                    id=row["id"],
                    session_id=row["session_id"],
                    role=row["role"],
                    content=row["content"],
                    urgency=row["urgency"],
                    thinking=row["thinking"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                )
                for row in rows
            ]

    # Turn operations

    def create_turn(
        self,
        session_id: str,
        user_input: str,
        total_time_ms: int = 0,
        council_speak: bool = False,
        council_urgency: str | None = None,
    ) -> int:
        """Create a new turn."""
        with self._connection() as conn:
            cursor = conn.execute(
                """INSERT INTO turns (session_id, user_input, total_time_ms, council_speak, council_urgency, created_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    session_id,
                    user_input,
                    total_time_ms,
                    1 if council_speak else 0,
                    council_urgency,
                    datetime.now().isoformat(),
                ),
            )
            return cursor.lastrowid

    def update_turn(
        self,
        turn_id: int,
        total_time_ms: int | None = None,
        council_speak: bool | None = None,
        council_urgency: str | None = None,
    ) -> None:
        """Update a turn."""
        updates = []
        params = []

        if total_time_ms is not None:
            updates.append("total_time_ms = ?")
            params.append(total_time_ms)
        if council_speak is not None:
            updates.append("council_speak = ?")
            params.append(1 if council_speak else 0)
        if council_urgency is not None:
            updates.append("council_urgency = ?")
            params.append(council_urgency)

        if updates:
            params.append(turn_id)
            with self._connection() as conn:
                conn.execute(
                    f"UPDATE turns SET {', '.join(updates)} WHERE id = ?",
                    params,
                )

    # Agent call operations

    def add_agent_call(
        self,
        turn_id: int,
        agent_id: str,
        output: str,
        thinking: str | None = None,
        urgency: int = 0,
        confidence: int = 0,
        processing_time_ms: int = 0,
    ) -> int:
        """Add an agent call record."""
        with self._connection() as conn:
            cursor = conn.execute(
                """INSERT INTO agent_calls
                (turn_id, agent_id, output, thinking, urgency, confidence, processing_time_ms, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    turn_id,
                    agent_id,
                    output,
                    thinking,
                    urgency,
                    confidence,
                    processing_time_ms,
                    datetime.now().isoformat(),
                ),
            )
            return cursor.lastrowid

    def get_agent_calls(
        self,
        turn_id: int | None = None,
        agent_id: str | None = None,
        limit: int = 100,
    ) -> list[AgentCallRecord]:
        """Get agent calls, optionally filtered."""
        query = "SELECT * FROM agent_calls WHERE 1=1"
        params = []

        if turn_id is not None:
            query += " AND turn_id = ?"
            params.append(turn_id)
        if agent_id is not None:
            query += " AND agent_id = ?"
            params.append(agent_id)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with self._connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [
                AgentCallRecord(
                    id=row["id"],
                    turn_id=row["turn_id"],
                    agent_id=row["agent_id"],
                    output=row["output"],
                    thinking=row["thinking"],
                    urgency=row["urgency"],
                    confidence=row["confidence"],
                    processing_time_ms=row["processing_time_ms"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                )
                for row in rows
            ]

    # Model call operations

    def add_model_call(
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
    ) -> int:
        """Add a model call record."""
        with self._connection() as conn:
            cursor = conn.execute(
                """INSERT INTO model_calls
                (agent_call_id, council_call_id, model, messages, response, latency_ms,
                 prompt_tokens, completion_tokens, reasoning_tokens, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    agent_call_id,
                    council_call_id,
                    model,
                    json.dumps(messages),
                    response,
                    latency_ms,
                    prompt_tokens,
                    completion_tokens,
                    reasoning_tokens,
                    datetime.now().isoformat(),
                ),
            )
            return cursor.lastrowid

    # Council call operations

    def add_council_call(
        self,
        turn_id: int,
        speak: bool,
        urgency: str,
        speech_act: dict | None = None,
        final_message: str | None = None,
        thinking: str | None = None,
        processing_time_ms: int = 0,
    ) -> int:
        """Add a council call record."""
        with self._connection() as conn:
            cursor = conn.execute(
                """INSERT INTO council_calls
                (turn_id, speak, urgency, speech_act, final_message, thinking, processing_time_ms, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    turn_id,
                    1 if speak else 0,
                    urgency,
                    json.dumps(speech_act) if speech_act else None,
                    final_message,
                    thinking,
                    processing_time_ms,
                    datetime.now().isoformat(),
                ),
            )
            return cursor.lastrowid

    # Deliberation round operations

    def add_deliberation_round(
        self,
        turn_id: int,
        round_number: int,
        agent_id: str,
        voice_content: str,
        stance: str,
        urgency: int = 0,
        confidence: int = 0,
        addressed_agents: list[str] | None = None,
    ) -> int:
        """Add a deliberation round record."""
        with self._connection() as conn:
            cursor = conn.execute(
                """INSERT INTO deliberation_rounds
                (turn_id, round_number, agent_id, voice_content, stance, urgency, confidence, addressed_agents, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    turn_id,
                    round_number,
                    agent_id,
                    voice_content,
                    stance,
                    urgency,
                    confidence,
                    json.dumps(addressed_agents) if addressed_agents else None,
                    datetime.now().isoformat(),
                ),
            )
            return cursor.lastrowid

    # Query operations

    def get_stats(self, hours: int = 24) -> dict[str, Any]:
        """Get statistics for the last N hours."""
        cutoff = datetime.now().isoformat()[:10]  # Just use date for simplicity

        with self._connection() as conn:
            # Count turns
            turns = conn.execute(
                "SELECT COUNT(*) as count FROM turns WHERE created_at > ?",
                (cutoff,),
            ).fetchone()["count"]

            # Count agent calls
            agent_calls = conn.execute(
                "SELECT COUNT(*) as count FROM agent_calls WHERE created_at > ?",
                (cutoff,),
            ).fetchone()["count"]

            # Sum tokens
            tokens = conn.execute(
                """SELECT
                    COALESCE(SUM(prompt_tokens), 0) as prompt,
                    COALESCE(SUM(completion_tokens), 0) as completion,
                    COALESCE(SUM(reasoning_tokens), 0) as reasoning
                FROM model_calls WHERE created_at > ?""",
                (cutoff,),
            ).fetchone()

            # Average turn time
            avg_time = conn.execute(
                """SELECT AVG(total_time_ms) as avg_ms
                FROM turns WHERE created_at > ?""",
                (cutoff,),
            ).fetchone()["avg_ms"] or 0

            return {
                "turns": turns,
                "agent_calls": agent_calls,
                "prompt_tokens": tokens["prompt"],
                "completion_tokens": tokens["completion"],
                "reasoning_tokens": tokens["reasoning"],
                "avg_turn_time_ms": round(avg_time, 1),
            }

    def get_agent_stats(self, agent_id: str | None = None, limit: int = 20) -> list[dict]:
        """Get per-agent statistics."""
        query = """
            SELECT
                agent_id,
                COUNT(*) as call_count,
                AVG(urgency) as avg_urgency,
                AVG(confidence) as avg_confidence,
                AVG(processing_time_ms) as avg_time_ms
            FROM agent_calls
        """
        params = []

        if agent_id:
            query += " WHERE agent_id = ?"
            params.append(agent_id)

        query += " GROUP BY agent_id ORDER BY call_count DESC LIMIT ?"
        params.append(limit)

        with self._connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]
