"""Event log - single source of truth for all system state."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from rilai.contracts.events import EngineEvent, EventKind


class EventLogWriter:
    """Single-writer append-only event log.

    This is the heart of the event-sourcing system. All events are
    appended here, and all other state is derived from this log.

    Thread Safety:
    - Single writer assumed (one TurnRunner at a time)
    - Multiple readers supported via separate connections

    Invariants:
    - Events within a turn have monotonically increasing seq
    - Events are never deleted or modified
    - Event order is deterministic (session_id, turn_id, seq)
    """

    def __init__(self, db_path: Path | str):
        """Initialize event log.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Sequence counters per (session_id, turn_id)
        self._seq_counters: dict[tuple[str, int], int] = {}

        # Initialize schema
        self._init_schema()

    def _init_schema(self) -> None:
        """Create tables and indexes if they don't exist."""
        with self._conn() as conn:
            conn.executescript("""
                -- Main events table
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    turn_id INTEGER NOT NULL,
                    seq INTEGER NOT NULL,
                    ts_monotonic REAL NOT NULL,
                    ts_wall TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    schema_version INTEGER NOT NULL DEFAULT 1,
                    UNIQUE(session_id, turn_id, seq)
                );

                -- Indexes for common queries
                CREATE INDEX IF NOT EXISTS idx_events_session_turn
                    ON events(session_id, turn_id);
                CREATE INDEX IF NOT EXISTS idx_events_kind
                    ON events(kind);
                CREATE INDEX IF NOT EXISTS idx_events_session
                    ON events(session_id);

                -- Memory tables (separate from event log)
                CREATE TABLE IF NOT EXISTS memory_episodic (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    turn_id INTEGER NOT NULL,
                    timestamp TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    emotions TEXT NOT NULL,  -- JSON array
                    participants TEXT NOT NULL,  -- JSON array
                    tags TEXT NOT NULL,  -- JSON array
                    importance REAL NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS memory_user (
                    id TEXT PRIMARY KEY,
                    fact TEXT NOT NULL,
                    category TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    source TEXT NOT NULL,
                    first_observed TEXT NOT NULL,
                    last_confirmed TEXT NOT NULL,
                    evidence_count INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_episodic_session
                    ON memory_episodic(session_id);
                CREATE INDEX IF NOT EXISTS idx_episodic_timestamp
                    ON memory_episodic(timestamp);
                CREATE INDEX IF NOT EXISTS idx_user_category
                    ON memory_user(category);
            """)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        """Get a database connection with automatic commit/rollback."""
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

    def next_seq(self, session_id: str, turn_id: int) -> int:
        """Get next sequence number for a turn.

        This is monotonically increasing within a turn.
        Thread-safe within a single writer.
        """
        key = (session_id, turn_id)
        seq = self._seq_counters.get(key, 0)
        self._seq_counters[key] = seq + 1
        return seq

    def reset_seq(self, session_id: str, turn_id: int) -> None:
        """Reset sequence counter for a turn (for replay scenarios)."""
        key = (session_id, turn_id)
        self._seq_counters[key] = 0

    def append(self, event: EngineEvent) -> None:
        """Append an event to the log.

        This is the primary write operation. Events are immutable
        once written.

        Args:
            event: The event to append
        """
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO events
                    (session_id, turn_id, seq, ts_monotonic, ts_wall,
                     kind, payload_json, schema_version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.session_id,
                    event.turn_id,
                    event.seq,
                    event.ts_monotonic,
                    event.ts_wall.isoformat(),
                    event.kind.value,
                    json.dumps(event.payload),
                    event.schema_version,
                ),
            )

    def append_batch(self, events: list[EngineEvent]) -> None:
        """Append multiple events in a single transaction."""
        with self._conn() as conn:
            conn.executemany(
                """
                INSERT INTO events
                    (session_id, turn_id, seq, ts_monotonic, ts_wall,
                     kind, payload_json, schema_version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        e.session_id,
                        e.turn_id,
                        e.seq,
                        e.ts_monotonic,
                        e.ts_wall.isoformat(),
                        e.kind.value,
                        json.dumps(e.payload),
                        e.schema_version,
                    )
                    for e in events
                ],
            )

    # ─────────────────────────────────────────────────────────────────────
    # Query Methods
    # ─────────────────────────────────────────────────────────────────────

    def replay_turn(
        self, session_id: str, turn_id: int
    ) -> Iterator[EngineEvent]:
        """Replay all events for a specific turn.

        This is used to rebuild state from the log.

        Yields:
            Events in sequence order
        """
        with self._conn() as conn:
            cursor = conn.execute(
                """
                SELECT session_id, turn_id, seq, ts_monotonic, ts_wall,
                       kind, payload_json, schema_version
                FROM events
                WHERE session_id = ? AND turn_id = ?
                ORDER BY seq
                """,
                (session_id, turn_id),
            )
            for row in cursor:
                yield EngineEvent(
                    session_id=row["session_id"],
                    turn_id=row["turn_id"],
                    seq=row["seq"],
                    ts_monotonic=row["ts_monotonic"],
                    ts_wall=datetime.fromisoformat(row["ts_wall"]),
                    kind=EventKind(row["kind"]),
                    payload=json.loads(row["payload_json"]),
                    schema_version=row["schema_version"],
                )

    def replay_session(self, session_id: str) -> Iterator[EngineEvent]:
        """Replay all events for a session.

        Yields:
            Events in (turn_id, seq) order
        """
        with self._conn() as conn:
            cursor = conn.execute(
                """
                SELECT session_id, turn_id, seq, ts_monotonic, ts_wall,
                       kind, payload_json, schema_version
                FROM events
                WHERE session_id = ?
                ORDER BY turn_id, seq
                """,
                (session_id,),
            )
            for row in cursor:
                yield EngineEvent(
                    session_id=row["session_id"],
                    turn_id=row["turn_id"],
                    seq=row["seq"],
                    ts_monotonic=row["ts_monotonic"],
                    ts_wall=datetime.fromisoformat(row["ts_wall"]),
                    kind=EventKind(row["kind"]),
                    payload=json.loads(row["payload_json"]),
                    schema_version=row["schema_version"],
                )

    def get_events_by_kind(
        self,
        session_id: str,
        kind: EventKind,
        limit: int = 100,
    ) -> list[EngineEvent]:
        """Get events of a specific kind from a session."""
        events = []
        with self._conn() as conn:
            cursor = conn.execute(
                """
                SELECT session_id, turn_id, seq, ts_monotonic, ts_wall,
                       kind, payload_json, schema_version
                FROM events
                WHERE session_id = ? AND kind = ?
                ORDER BY turn_id DESC, seq DESC
                LIMIT ?
                """,
                (session_id, kind.value, limit),
            )
            for row in cursor:
                events.append(
                    EngineEvent(
                        session_id=row["session_id"],
                        turn_id=row["turn_id"],
                        seq=row["seq"],
                        ts_monotonic=row["ts_monotonic"],
                        ts_wall=datetime.fromisoformat(row["ts_wall"]),
                        kind=EventKind(row["kind"]),
                        payload=json.loads(row["payload_json"]),
                        schema_version=row["schema_version"],
                    )
                )
        return events

    def get_last_turn_id(self, session_id: str) -> int:
        """Get the last turn ID for a session."""
        with self._conn() as conn:
            cursor = conn.execute(
                "SELECT MAX(turn_id) FROM events WHERE session_id = ?",
                (session_id,),
            )
            row = cursor.fetchone()
            return row[0] if row[0] is not None else 0

    def get_session_ids(self, limit: int = 100) -> list[str]:
        """Get recent session IDs."""
        with self._conn() as conn:
            cursor = conn.execute(
                """
                SELECT DISTINCT session_id
                FROM events
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            )
            return [row[0] for row in cursor]

    def count_events(
        self, session_id: str | None = None, turn_id: int | None = None
    ) -> int:
        """Count events, optionally filtered."""
        with self._conn() as conn:
            if session_id and turn_id is not None:
                cursor = conn.execute(
                    "SELECT COUNT(*) FROM events WHERE session_id = ? AND turn_id = ?",
                    (session_id, turn_id),
                )
            elif session_id:
                cursor = conn.execute(
                    "SELECT COUNT(*) FROM events WHERE session_id = ?",
                    (session_id,),
                )
            else:
                cursor = conn.execute("SELECT COUNT(*) FROM events")
            return cursor.fetchone()[0]
