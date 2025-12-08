# Document 02: Event Store (`rilai-store`)

**Purpose:** Implement event log and projections
**Execution:** One Claude Code session
**Dependencies:** 01-contracts

---

## Overview

The store module implements the event-sourcing backbone:
- **EventLogWriter**: Single-writer append-only SQLite log
- **Projections**: Derived views rebuilt from events

**Key principles:**
- Event log is the single source of truth
- All other state is derived via projections
- Projections can be rebuilt from scratch at any time
- No dual-write (eliminates v2's SQLite + JSON disagreement)

---

## Files to Create

```
src/rilai/store/
├── __init__.py
├── event_log.py              # EventLogWriter (append-only)
└── projections/
    ├── __init__.py
    ├── base.py               # Projection base class
    ├── turn_state.py         # TurnStateProjection (for TUI)
    ├── session.py            # SessionProjection
    ├── analytics.py          # AnalyticsProjection
    └── debug.py              # DebugProjection
```

---

## File: `src/rilai/store/__init__.py`

```python
"""Rilai v3 Store - Event log and projections."""

from rilai.store.event_log import EventLogWriter
from rilai.store.projections.base import Projection
from rilai.store.projections.turn_state import TurnStateProjection
from rilai.store.projections.session import SessionProjection
from rilai.store.projections.analytics import AnalyticsProjection
from rilai.store.projections.debug import DebugProjection

__all__ = [
    "EventLogWriter",
    "Projection",
    "TurnStateProjection",
    "SessionProjection",
    "AnalyticsProjection",
    "DebugProjection",
]
```

---

## File: `src/rilai/store/event_log.py`

```python
"""Event log - single source of truth for all system state."""

import json
import sqlite3
import time
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
```

---

## File: `src/rilai/store/projections/__init__.py`

```python
"""Projections - derived views from event log."""

from rilai.store.projections.base import Projection
from rilai.store.projections.turn_state import TurnStateProjection
from rilai.store.projections.session import SessionProjection
from rilai.store.projections.analytics import AnalyticsProjection
from rilai.store.projections.debug import DebugProjection

__all__ = [
    "Projection",
    "TurnStateProjection",
    "SessionProjection",
    "AnalyticsProjection",
    "DebugProjection",
]
```

---

## File: `src/rilai/store/projections/base.py`

```python
"""Base class for projections."""

from abc import ABC, abstractmethod
from typing import Any

from rilai.contracts.events import EngineEvent


class Projection(ABC):
    """Base class for event projections.

    A projection maintains derived state from an event stream.
    It can be rebuilt from scratch by replaying events.
    """

    @abstractmethod
    def apply(self, event: EngineEvent) -> Any:
        """Apply an event to update projection state.

        Args:
            event: The event to apply

        Returns:
            Optional return value (e.g., UI updates)
        """
        pass

    @abstractmethod
    def reset(self) -> None:
        """Reset projection to initial state."""
        pass

    def rebuild_from(self, events: list[EngineEvent]) -> None:
        """Rebuild projection from a list of events.

        This is used to restore state from the event log.
        """
        self.reset()
        for event in events:
            self.apply(event)
```

---

## File: `src/rilai/store/projections/turn_state.py`

```python
"""TurnStateProjection - maintains TUI-ready state from events."""

from dataclasses import dataclass, field
from typing import Literal, Any

from rilai.contracts.events import EngineEvent, EventKind
from rilai.store.projections.base import Projection


UIUpdateKind = Literal[
    "sensors",
    "stance",
    "agents",
    "workspace",
    "critics",
    "memory",
    "chat",
    "activity",
]


@dataclass
class UIUpdate:
    """A single UI update to apply."""

    kind: UIUpdateKind
    payload: dict[str, Any]


@dataclass
class TurnStateProjection(Projection):
    """Maintains TUI-ready state from event stream.

    This projection is designed for real-time UI updates.
    Each event produces zero or more UIUpdates that the TUI
    can apply immediately.
    """

    # Panel state
    sensors: dict[str, float] = field(default_factory=dict)
    stance: dict[str, float] = field(default_factory=dict)
    agent_logs: list[str] = field(default_factory=list)
    workspace: dict[str, Any] = field(default_factory=dict)
    critics: list[dict] = field(default_factory=list)
    memory: dict[str, Any] = field(default_factory=dict)

    # Turn state
    current_stage: str = "idle"
    current_turn_id: int = 0
    response: str = ""

    # Timing
    turn_start_time: float = 0.0
    stage_times: dict[str, float] = field(default_factory=dict)

    def reset(self) -> None:
        """Reset to initial state."""
        self.sensors.clear()
        self.stance.clear()
        self.agent_logs.clear()
        self.workspace.clear()
        self.critics.clear()
        self.memory.clear()
        self.current_stage = "idle"
        self.current_turn_id = 0
        self.response = ""
        self.turn_start_time = 0.0
        self.stage_times.clear()

    def reset_for_turn(self) -> None:
        """Reset transient state for a new turn."""
        self.agent_logs.clear()
        self.critics.clear()
        self.response = ""
        self.stage_times.clear()

    def apply(self, event: EngineEvent) -> list[UIUpdate]:
        """Apply event and return UI updates.

        This is the main method called by the TUI to process events.
        Each event can produce multiple UI updates.

        Args:
            event: The event to apply

        Returns:
            List of UI updates to apply
        """
        updates: list[UIUpdate] = []

        match event.kind:
            # ─────────────────────────────────────────────────────────────
            # Turn Lifecycle
            # ─────────────────────────────────────────────────────────────
            case EventKind.TURN_STARTED:
                self.reset_for_turn()
                self.current_turn_id = event.payload.get("turn_id", 0)
                self.turn_start_time = event.ts_monotonic
                updates.append(UIUpdate("activity", {"stage": "starting"}))

            case EventKind.TURN_STAGE_CHANGED:
                stage = event.payload.get("stage", "unknown")
                self.current_stage = stage
                self.stage_times[stage] = event.ts_monotonic
                updates.append(UIUpdate("activity", {"stage": stage}))

            case EventKind.TURN_COMPLETED:
                self.current_stage = "idle"
                self.response = event.payload.get("response", "")
                updates.append(UIUpdate("activity", {"stage": "idle"}))

            # ─────────────────────────────────────────────────────────────
            # Sensors
            # ─────────────────────────────────────────────────────────────
            case EventKind.SENSORS_FAST_UPDATED:
                self.sensors = event.payload.get("sensors", {})
                updates.append(UIUpdate("sensors", {"sensors": self.sensors}))

            # ─────────────────────────────────────────────────────────────
            # Agents
            # ─────────────────────────────────────────────────────────────
            case EventKind.AGENT_COMPLETED:
                agent_id = event.payload.get("agent_id", "?")
                observation = event.payload.get("observation", "")
                if observation and observation.lower() != "quiet":
                    line = f"{agent_id}: {observation[:100]}"
                    self.agent_logs.append(line)
                    updates.append(UIUpdate("agents", {"line": line}))

            case EventKind.AGENT_FAILED:
                agent_id = event.payload.get("agent_id", "?")
                error = event.payload.get("error", "Unknown error")
                line = f"[red]{agent_id}: FAILED - {error[:50]}[/]"
                self.agent_logs.append(line)
                updates.append(UIUpdate("agents", {"line": line}))

            # ─────────────────────────────────────────────────────────────
            # Workspace
            # ─────────────────────────────────────────────────────────────
            case EventKind.WORKSPACE_PATCHED:
                patch = event.payload.get("patch", {})
                self.workspace.update(patch)
                updates.append(UIUpdate("workspace", {"workspace": self.workspace}))

            case EventKind.STANCE_UPDATED:
                delta = event.payload.get("delta", {})
                current = event.payload.get("current", {})
                self.stance.update(current if current else delta)
                updates.append(UIUpdate("stance", {"stance": self.stance}))

            # ─────────────────────────────────────────────────────────────
            # Deliberation
            # ─────────────────────────────────────────────────────────────
            case EventKind.DELIB_ROUND_STARTED:
                round_num = event.payload.get("round", 0)
                line = f"[dim]Deliberation round {round_num} started[/]"
                self.agent_logs.append(line)
                updates.append(UIUpdate("agents", {"line": line}))

            case EventKind.CONSENSUS_UPDATED:
                level = event.payload.get("level", 0.0)
                self.workspace["consensus"] = level
                updates.append(UIUpdate("workspace", {"workspace": self.workspace}))

            # ─────────────────────────────────────────────────────────────
            # Council + Voice
            # ─────────────────────────────────────────────────────────────
            case EventKind.COUNCIL_DECISION_MADE:
                self.workspace["speak"] = event.payload.get("speak", False)
                self.workspace["urgency"] = event.payload.get("urgency", "medium")
                self.workspace["intent"] = event.payload.get("intent", "")
                updates.append(UIUpdate("workspace", {"workspace": self.workspace}))

            case EventKind.VOICE_RENDERED:
                text = event.payload.get("text", "")
                self.response = text
                updates.append(
                    UIUpdate("chat", {"text": text, "role": "assistant"})
                )

            # ─────────────────────────────────────────────────────────────
            # Critics
            # ─────────────────────────────────────────────────────────────
            case EventKind.CRITICS_UPDATED:
                self.critics = event.payload.get("results", [])
                updates.append(UIUpdate("critics", {"results": self.critics}))

            case EventKind.SAFETY_INTERRUPT:
                reason = event.payload.get("reason", "Unknown")
                self.critics.append({
                    "critic": "safety_interrupt",
                    "passed": False,
                    "reason": reason,
                })
                updates.append(UIUpdate("critics", {"results": self.critics}))
                updates.append(UIUpdate("activity", {"stage": "safety_interrupt"}))

            # ─────────────────────────────────────────────────────────────
            # Memory
            # ─────────────────────────────────────────────────────────────
            case EventKind.MEMORY_RETRIEVED:
                self.memory["retrieved"] = {
                    "episodes": len(event.payload.get("episodes", [])),
                    "user_facts": len(event.payload.get("user_facts", [])),
                    "open_threads": len(event.payload.get("open_threads", [])),
                }
                updates.append(UIUpdate("memory", {"memory": self.memory}))

            case EventKind.MEMORY_COMMITTED:
                self.memory["committed"] = event.payload.get("summary", {})
                updates.append(UIUpdate("memory", {"memory": self.memory}))

            # ─────────────────────────────────────────────────────────────
            # Daemon
            # ─────────────────────────────────────────────────────────────
            case EventKind.PROACTIVE_NUDGE:
                reason = event.payload.get("reason", "")
                suggestion = event.payload.get("suggestion", "")
                line = f"[yellow]Nudge ({reason}): {suggestion}[/]"
                self.agent_logs.append(line)
                updates.append(UIUpdate("agents", {"line": line}))

        return updates

    def get_elapsed_ms(self) -> int:
        """Get elapsed time since turn start."""
        import time
        if self.turn_start_time == 0:
            return 0
        return int((time.monotonic() - self.turn_start_time) * 1000)
```

---

## File: `src/rilai/store/projections/session.py`

```python
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
```

---

## File: `src/rilai/store/projections/analytics.py`

```python
"""AnalyticsProjection - token usage and latency tracking."""

from dataclasses import dataclass, field
from typing import Any

from rilai.contracts.events import EngineEvent, EventKind
from rilai.store.projections.base import Projection


@dataclass
class ModelCallStats:
    """Stats for a single model call."""

    model: str
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int
    latency_ms: int


@dataclass
class AnalyticsProjection(Projection):
    """Tracks token usage and latency metrics.

    Useful for cost tracking and performance optimization.
    """

    # Per-session totals
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_reasoning_tokens: int = 0
    total_latency_ms: int = 0

    # Per-turn stats
    turn_stats: dict[int, dict[str, Any]] = field(default_factory=dict)

    # Model breakdown
    model_usage: dict[str, dict[str, int]] = field(default_factory=dict)

    # Call history
    recent_calls: list[ModelCallStats] = field(default_factory=list)

    def reset(self) -> None:
        """Reset to initial state."""
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_reasoning_tokens = 0
        self.total_latency_ms = 0
        self.turn_stats.clear()
        self.model_usage.clear()
        self.recent_calls.clear()

    def apply(self, event: EngineEvent) -> None:
        """Apply event to update analytics."""
        match event.kind:
            case EventKind.MODEL_CALL_COMPLETED:
                model = event.payload.get("model", "unknown")
                prompt = event.payload.get("prompt_tokens", 0)
                completion = event.payload.get("completion_tokens", 0)
                reasoning = event.payload.get("reasoning_tokens", 0) or 0
                latency = event.payload.get("latency_ms", 0)

                # Update totals
                self.total_prompt_tokens += prompt
                self.total_completion_tokens += completion
                self.total_reasoning_tokens += reasoning
                self.total_latency_ms += latency

                # Update model breakdown
                if model not in self.model_usage:
                    self.model_usage[model] = {
                        "calls": 0,
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "reasoning_tokens": 0,
                        "latency_ms": 0,
                    }
                self.model_usage[model]["calls"] += 1
                self.model_usage[model]["prompt_tokens"] += prompt
                self.model_usage[model]["completion_tokens"] += completion
                self.model_usage[model]["reasoning_tokens"] += reasoning
                self.model_usage[model]["latency_ms"] += latency

                # Track call
                self.recent_calls.append(
                    ModelCallStats(
                        model=model,
                        prompt_tokens=prompt,
                        completion_tokens=completion,
                        reasoning_tokens=reasoning,
                        latency_ms=latency,
                    )
                )
                # Keep only recent calls
                if len(self.recent_calls) > 100:
                    self.recent_calls = self.recent_calls[-100:]

            case EventKind.TURN_COMPLETED:
                turn_id = event.turn_id
                total_time = event.payload.get("total_time_ms", 0)
                self.turn_stats[turn_id] = {
                    "total_time_ms": total_time,
                    "timestamp": event.ts_wall.isoformat(),
                }

    def get_summary(self) -> dict[str, Any]:
        """Get analytics summary."""
        return {
            "total_tokens": (
                self.total_prompt_tokens
                + self.total_completion_tokens
                + self.total_reasoning_tokens
            ),
            "prompt_tokens": self.total_prompt_tokens,
            "completion_tokens": self.total_completion_tokens,
            "reasoning_tokens": self.total_reasoning_tokens,
            "total_latency_ms": self.total_latency_ms,
            "model_count": len(self.model_usage),
            "call_count": len(self.recent_calls),
            "turn_count": len(self.turn_stats),
        }
```

---

## File: `src/rilai/store/projections/debug.py`

```python
"""DebugProjection - agent traces and timing for debugging."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from rilai.contracts.events import EngineEvent, EventKind
from rilai.store.projections.base import Projection


@dataclass
class AgentTrace:
    """Trace of a single agent execution."""

    agent_id: str
    turn_id: int
    started_at: datetime | None = None
    completed_at: datetime | None = None
    observation: str = ""
    claims: list[dict] = field(default_factory=list)
    urgency: int = 0
    confidence: int = 0
    salience: float = 0.0
    error: str | None = None
    processing_time_ms: int = 0


@dataclass
class DebugProjection(Projection):
    """Tracks agent traces and timing for debugging.

    Useful for understanding what agents did and why.
    """

    # Per-turn agent traces
    turn_traces: dict[int, list[AgentTrace]] = field(default_factory=dict)

    # Pending traces (started but not completed)
    pending_traces: dict[str, AgentTrace] = field(default_factory=dict)

    # Stage timing
    stage_timing: dict[int, dict[str, float]] = field(default_factory=dict)

    # Error history
    errors: list[dict] = field(default_factory=list)

    def reset(self) -> None:
        """Reset to initial state."""
        self.turn_traces.clear()
        self.pending_traces.clear()
        self.stage_timing.clear()
        self.errors.clear()

    def apply(self, event: EngineEvent) -> None:
        """Apply event to update debug state."""
        turn_id = event.turn_id

        match event.kind:
            case EventKind.TURN_STARTED:
                self.turn_traces[turn_id] = []
                self.stage_timing[turn_id] = {}

            case EventKind.TURN_STAGE_CHANGED:
                stage = event.payload.get("stage", "unknown")
                if turn_id in self.stage_timing:
                    self.stage_timing[turn_id][stage] = event.ts_monotonic

            case EventKind.AGENT_STARTED:
                agent_id = event.payload.get("agent_id", "?")
                trace = AgentTrace(
                    agent_id=agent_id,
                    turn_id=turn_id,
                    started_at=event.ts_wall,
                )
                self.pending_traces[agent_id] = trace

            case EventKind.AGENT_COMPLETED:
                agent_id = event.payload.get("agent_id", "?")
                trace = self.pending_traces.pop(agent_id, None)
                if trace is None:
                    trace = AgentTrace(agent_id=agent_id, turn_id=turn_id)

                trace.completed_at = event.ts_wall
                trace.observation = event.payload.get("observation", "")
                trace.claims = event.payload.get("claims", [])
                trace.urgency = event.payload.get("urgency", 0)
                trace.confidence = event.payload.get("confidence", 0)
                trace.salience = event.payload.get("salience", 0.0)
                trace.processing_time_ms = event.payload.get("processing_time_ms", 0)

                if turn_id in self.turn_traces:
                    self.turn_traces[turn_id].append(trace)

            case EventKind.AGENT_FAILED:
                agent_id = event.payload.get("agent_id", "?")
                error = event.payload.get("error", "Unknown error")
                trace = self.pending_traces.pop(agent_id, None)
                if trace is None:
                    trace = AgentTrace(agent_id=agent_id, turn_id=turn_id)

                trace.completed_at = event.ts_wall
                trace.error = error

                if turn_id in self.turn_traces:
                    self.turn_traces[turn_id].append(trace)

            case EventKind.ERROR:
                self.errors.append({
                    "turn_id": turn_id,
                    "error": event.payload.get("error", "Unknown"),
                    "traceback": event.payload.get("traceback"),
                    "timestamp": event.ts_wall.isoformat(),
                })

    def get_turn_summary(self, turn_id: int) -> dict[str, Any]:
        """Get summary of a turn for debugging."""
        traces = self.turn_traces.get(turn_id, [])
        timing = self.stage_timing.get(turn_id, {})

        return {
            "turn_id": turn_id,
            "agent_count": len(traces),
            "agents": [
                {
                    "agent_id": t.agent_id,
                    "observation": t.observation[:100] if t.observation else "",
                    "urgency": t.urgency,
                    "confidence": t.confidence,
                    "salience": t.salience,
                    "error": t.error,
                    "processing_time_ms": t.processing_time_ms,
                }
                for t in traces
            ],
            "stages": list(timing.keys()),
            "errors": [e for e in self.errors if e["turn_id"] == turn_id],
        }
```

---

## Files to DELETE from v2

After implementing and verifying the store module works:

```
src/rilai/memory/database.py      # Replaced by EventLogWriter
src/rilai/memory/short_term.py    # Replaced by projections
src/rilai/observability/store.py  # Dual-write pattern eliminated
data/current/                     # JSON ephemeral storage (delete directory)
```

---

## Tests to Write

Create `tests/test_store.py`:

```python
"""Tests for store module."""

import pytest
import tempfile
from pathlib import Path
from datetime import datetime

from rilai.contracts.events import EngineEvent, EventKind
from rilai.store.event_log import EventLogWriter
from rilai.store.projections.turn_state import TurnStateProjection


class TestEventLogWriter:
    def test_append_and_replay(self, tmp_path):
        db_path = tmp_path / "test.db"
        log = EventLogWriter(db_path)

        # Append events
        event1 = EngineEvent(
            session_id="test",
            turn_id=1,
            seq=0,
            ts_monotonic=1000.0,
            kind=EventKind.TURN_STARTED,
            payload={"user_input": "hello"},
        )
        event2 = EngineEvent(
            session_id="test",
            turn_id=1,
            seq=1,
            ts_monotonic=1001.0,
            kind=EventKind.TURN_COMPLETED,
            payload={"response": "hi"},
        )
        log.append(event1)
        log.append(event2)

        # Replay
        events = list(log.replay_turn("test", 1))
        assert len(events) == 2
        assert events[0].kind == EventKind.TURN_STARTED
        assert events[1].kind == EventKind.TURN_COMPLETED

    def test_next_seq(self, tmp_path):
        db_path = tmp_path / "test.db"
        log = EventLogWriter(db_path)

        assert log.next_seq("s1", 1) == 0
        assert log.next_seq("s1", 1) == 1
        assert log.next_seq("s1", 1) == 2
        assert log.next_seq("s1", 2) == 0  # New turn resets


class TestTurnStateProjection:
    def test_sensors_update(self):
        proj = TurnStateProjection()
        event = EngineEvent(
            session_id="test",
            turn_id=1,
            seq=0,
            ts_monotonic=1000.0,
            kind=EventKind.SENSORS_FAST_UPDATED,
            payload={"sensors": {"vulnerability": 0.8, "advice_requested": 0.2}},
        )
        updates = proj.apply(event)

        assert len(updates) == 1
        assert updates[0].kind == "sensors"
        assert proj.sensors["vulnerability"] == 0.8

    def test_agent_completed(self):
        proj = TurnStateProjection()
        event = EngineEvent(
            session_id="test",
            turn_id=1,
            seq=0,
            ts_monotonic=1000.0,
            kind=EventKind.AGENT_COMPLETED,
            payload={
                "agent_id": "emotion.stress",
                "observation": "High stress detected",
            },
        )
        updates = proj.apply(event)

        assert len(updates) == 1
        assert updates[0].kind == "agents"
        assert "emotion.stress" in proj.agent_logs[0]

    def test_quiet_agent_not_logged(self):
        proj = TurnStateProjection()
        event = EngineEvent(
            session_id="test",
            turn_id=1,
            seq=0,
            ts_monotonic=1000.0,
            kind=EventKind.AGENT_COMPLETED,
            payload={
                "agent_id": "emotion.stress",
                "observation": "Quiet",
            },
        )
        updates = proj.apply(event)

        assert len(updates) == 0
        assert len(proj.agent_logs) == 0
```

---

## Verification

After implementing, verify:

```bash
# Type check
python -m mypy src/rilai/store/

# Run tests
pytest tests/test_store.py -v

# Import check
python -c "from rilai.store import EventLogWriter, TurnStateProjection; print('OK')"

# Quick integration test
python -c "
from pathlib import Path
from rilai.store import EventLogWriter
from rilai.contracts.events import EngineEvent, EventKind

log = EventLogWriter(Path('/tmp/test_rilai.db'))
event = EngineEvent(
    session_id='test',
    turn_id=1,
    seq=log.next_seq('test', 1),
    ts_monotonic=1000.0,
    kind=EventKind.TURN_STARTED,
    payload={'user_input': 'hello'},
)
log.append(event)
print('Events:', log.count_events())
for e in log.replay_turn('test', 1):
    print(f'  {e.kind}: {e.payload}')
"
```

---

## Next Document

Proceed to `03-runtime-core.md` after store is implemented and tested.
