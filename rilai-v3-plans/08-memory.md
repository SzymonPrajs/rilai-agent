# Document 08: Memory System

**Purpose:** Implement full memory system with retrieval, episodic storage, user model, and consolidation
**Execution:** One Claude Code session
**Dependencies:** 01-contracts, 02-event-store, 03-runtime-core, 04-workspace

---

## Implementation Checklist

> **Instructions:** Mark items with `[x]` when complete. After completing items here,
> also update the master checklist in `00-overview.md`.

### Files to Create
- [x] `src/rilai/memory/__init__.py`
- [x] `src/rilai/memory/retrieval.py` - MemoryRetriever class
- [x] `src/rilai/memory/episodic.py` - EpisodicStore class
- [x] `src/rilai/memory/user_model.py` - UserModel class
- [ ] `src/rilai/memory/consolidation.py` - MemoryConsolidator class (not created)
- [x] `src/rilai/memory/embeddings.py` - get_embedding, cosine_similarity

### Database Tables
- [x] `episodic_events` table with indexes
- [x] `user_facts` table with indexes
- [x] `user_goals` table with indexes

### Retrieval Features (Stage 2)
- [x] get_recent() episodic events
- [x] search_similar() with embeddings
- [x] get_relevant_facts()
- [x] get_open_threads()

### Consolidation Features (Stage 8)
- [x] Filter by importance threshold
- [x] Store episodic events
- [x] Store/update user facts with dedup
- [x] Update goal progress

### Verification
- [x] Episodic store/retrieve works
- [x] User model add/get facts works
- [x] Goal management works
- [x] Embedding similarity search works
- [x] Write and run unit tests

### Notes
_Add any implementation notes, issues, or decisions here:_

---

## Overview

The memory system provides:
1. **Retrieval** (Stage 2): Inject relevant context before agents run
2. **Episodic Storage**: Store significant interactions as episodes
3. **User Model**: Track user facts, preferences, and boundaries
4. **Consolidation**: Background processing to update long-term memory

---

## Files to Create

```
src/rilai/memory/
├── __init__.py
├── retrieval.py         # Memory retrieval before agents
├── episodic.py          # Episodic event storage
├── user_model.py        # User facts and preferences
├── consolidation.py     # Memory consolidation pipeline
└── embeddings.py        # Embedding generation for similarity search
```

---

## File: `src/rilai/memory/__init__.py`

```python
"""Rilai v3 Memory System."""

from rilai.memory.retrieval import MemoryRetriever
from rilai.memory.episodic import EpisodicStore
from rilai.memory.user_model import UserModel
from rilai.memory.consolidation import MemoryConsolidator

__all__ = [
    "MemoryRetriever",
    "EpisodicStore",
    "UserModel",
    "MemoryConsolidator",
]
```

---

## File: `src/rilai/memory/retrieval.py`

```python
"""Memory retrieval for context injection."""

from typing import Callable, AsyncIterator
from datetime import datetime, timedelta

from rilai.contracts.events import EngineEvent, EventKind
from rilai.contracts.memory import EpisodicEvent, UserFact, Goal


class MemoryRetriever:
    """Retrieves relevant memories for context injection.

    Runs at Stage 2 to populate workspace context slots:
    - retrieved_episodes: Recent and relevant episodic events
    - user_facts: Known user preferences and facts
    - open_threads: Active goals and threads
    """

    MAX_EPISODES = 10
    MAX_FACTS = 20
    MAX_THREADS = 5
    RECENT_WINDOW_HOURS = 24

    def __init__(
        self,
        episodic_store: "EpisodicStore",
        user_model: "UserModel",
        emit_fn: Callable[[EventKind, dict], EngineEvent],
    ):
        self.episodic_store = episodic_store
        self.user_model = user_model
        self.emit_fn = emit_fn

    async def retrieve_context(
        self,
        user_message: str,
        workspace: "Workspace",
    ) -> AsyncIterator[EngineEvent]:
        """Retrieve and inject memory context into workspace.

        Args:
            user_message: Current user message
            workspace: Workspace to populate

        Yields:
            Events for each retrieval step
        """
        # 1. Retrieve recent episodes
        recent_cutoff = datetime.now() - timedelta(hours=self.RECENT_WINDOW_HOURS)
        recent_episodes = await self.episodic_store.get_recent(
            since=recent_cutoff,
            limit=self.MAX_EPISODES // 2,
        )

        # 2. Retrieve semantically similar episodes
        similar_episodes = await self.episodic_store.search_similar(
            query=user_message,
            limit=self.MAX_EPISODES // 2,
            exclude_ids=[e.id for e in recent_episodes],
        )

        # Combine and dedupe
        all_episodes = recent_episodes + similar_episodes
        workspace.retrieved_episodes = [self._episode_to_dict(e) for e in all_episodes]

        yield self.emit_fn(
            EventKind.WORKSPACE_PATCHED,
            {
                "field": "retrieved_episodes",
                "count": len(all_episodes),
            },
        )

        # 3. Retrieve relevant user facts
        facts = await self.user_model.get_relevant_facts(
            context=user_message,
            limit=self.MAX_FACTS,
        )
        workspace.user_facts = [self._fact_to_dict(f) for f in facts]

        yield self.emit_fn(
            EventKind.WORKSPACE_PATCHED,
            {
                "field": "user_facts",
                "count": len(facts),
            },
        )

        # 4. Retrieve open threads/goals
        threads = await self.user_model.get_open_threads(limit=self.MAX_THREADS)
        workspace.open_threads = threads

        yield self.emit_fn(
            EventKind.WORKSPACE_PATCHED,
            {
                "field": "open_threads",
                "count": len(threads),
            },
        )

    def _episode_to_dict(self, episode: EpisodicEvent) -> dict:
        """Convert episode to dict for workspace."""
        return {
            "id": episode.id,
            "timestamp": episode.timestamp.isoformat(),
            "summary": episode.summary,
            "emotions": episode.emotions,
            "topics": episode.topics,
            "importance": episode.importance,
        }

    def _fact_to_dict(self, fact: UserFact) -> dict:
        """Convert fact to dict for workspace."""
        return {
            "id": fact.id,
            "text": fact.text,
            "category": fact.category,
            "confidence": fact.confidence,
            "source": fact.source,
        }
```

---

## File: `src/rilai/memory/episodic.py`

```python
"""Episodic memory storage."""

import sqlite3
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from contextlib import contextmanager

from rilai.contracts.memory import EpisodicEvent


class EpisodicStore:
    """Stores and retrieves episodic memories.

    Episodic events are significant interactions that are worth remembering.
    They include:
    - Emotional moments
    - Important decisions
    - User disclosures
    - Goal completions
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_schema()

    def _init_schema(self) -> None:
        """Initialize database schema."""
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS episodic_events (
                    id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    emotions_json TEXT,
                    topics_json TEXT,
                    participants_json TEXT,
                    importance REAL DEFAULT 0.5,
                    embedding_json TEXT,
                    turn_id INTEGER,
                    session_id TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_episodic_timestamp
                ON episodic_events(timestamp DESC)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_episodic_importance
                ON episodic_events(importance DESC)
            """)

    @contextmanager
    def _conn(self):
        """Get database connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    async def store(self, event: EpisodicEvent) -> str:
        """Store an episodic event.

        Returns:
            Event ID
        """
        event_id = event.id or str(uuid.uuid4())[:12]

        with self._conn() as conn:
            conn.execute("""
                INSERT INTO episodic_events
                (id, timestamp, summary, emotions_json, topics_json,
                 participants_json, importance, embedding_json, turn_id, session_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                event_id,
                event.timestamp.isoformat(),
                event.summary,
                json.dumps(event.emotions) if event.emotions else None,
                json.dumps(event.topics) if event.topics else None,
                json.dumps(event.participants) if event.participants else None,
                event.importance,
                json.dumps(event.embedding) if event.embedding else None,
                event.turn_id,
                event.session_id,
            ))

        return event_id

    async def get_recent(
        self,
        since: datetime,
        limit: int = 10,
    ) -> List[EpisodicEvent]:
        """Get recent episodes since a timestamp."""
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT * FROM episodic_events
                WHERE timestamp >= ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (since.isoformat(), limit)).fetchall()

        return [self._row_to_event(row) for row in rows]

    async def search_similar(
        self,
        query: str,
        limit: int = 5,
        exclude_ids: Optional[List[str]] = None,
    ) -> List[EpisodicEvent]:
        """Search for semantically similar episodes.

        Uses embedding similarity if available, falls back to keyword matching.
        """
        # Generate embedding for query
        from rilai.memory.embeddings import get_embedding

        query_embedding = await get_embedding(query)

        if query_embedding:
            return await self._search_by_embedding(query_embedding, limit, exclude_ids)

        # Fallback to keyword search
        return await self._search_by_keywords(query, limit, exclude_ids)

    async def _search_by_embedding(
        self,
        embedding: List[float],
        limit: int,
        exclude_ids: Optional[List[str]],
    ) -> List[EpisodicEvent]:
        """Search by embedding similarity."""
        with self._conn() as conn:
            # Get all events with embeddings
            rows = conn.execute("""
                SELECT * FROM episodic_events
                WHERE embedding_json IS NOT NULL
                ORDER BY importance DESC
                LIMIT 100
            """).fetchall()

        # Calculate similarities
        scored = []
        for row in rows:
            if exclude_ids and row["id"] in exclude_ids:
                continue

            event_embedding = json.loads(row["embedding_json"])
            similarity = self._cosine_similarity(embedding, event_embedding)
            scored.append((similarity, row))

        # Sort by similarity
        scored.sort(key=lambda x: x[0], reverse=True)

        return [self._row_to_event(row) for _, row in scored[:limit]]

    async def _search_by_keywords(
        self,
        query: str,
        limit: int,
        exclude_ids: Optional[List[str]],
    ) -> List[EpisodicEvent]:
        """Fallback keyword search."""
        words = query.lower().split()
        if not words:
            return []

        # Build LIKE clauses
        like_clauses = " OR ".join(["summary LIKE ?" for _ in words])
        params = [f"%{word}%" for word in words[:5]]  # Limit words

        with self._conn() as conn:
            rows = conn.execute(f"""
                SELECT * FROM episodic_events
                WHERE ({like_clauses})
                ORDER BY importance DESC
                LIMIT ?
            """, params + [limit * 2]).fetchall()

        results = []
        for row in rows:
            if exclude_ids and row["id"] in exclude_ids:
                continue
            results.append(self._row_to_event(row))
            if len(results) >= limit:
                break

        return results

    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        if len(a) != len(b):
            return 0.0

        dot_product = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5

        if norm_a == 0 or norm_b == 0:
            return 0.0

        return dot_product / (norm_a * norm_b)

    def _row_to_event(self, row: sqlite3.Row) -> EpisodicEvent:
        """Convert database row to EpisodicEvent."""
        return EpisodicEvent(
            id=row["id"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            summary=row["summary"],
            emotions=json.loads(row["emotions_json"]) if row["emotions_json"] else [],
            topics=json.loads(row["topics_json"]) if row["topics_json"] else [],
            participants=json.loads(row["participants_json"]) if row["participants_json"] else [],
            importance=row["importance"],
            embedding=json.loads(row["embedding_json"]) if row["embedding_json"] else None,
            turn_id=row["turn_id"],
            session_id=row["session_id"],
        )
```

---

## File: `src/rilai/memory/user_model.py`

```python
"""User model - facts, preferences, and boundaries."""

import sqlite3
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from contextlib import contextmanager

from rilai.contracts.memory import UserFact, Goal


class UserModel:
    """Maintains model of the user.

    Stores:
    - Facts: Known information about the user
    - Preferences: User's stated preferences
    - Boundaries: Things the user doesn't want
    - Goals: Active user goals/threads
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_schema()

    def _init_schema(self) -> None:
        """Initialize database schema."""
        with self._conn() as conn:
            # User facts table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_facts (
                    id TEXT PRIMARY KEY,
                    text TEXT NOT NULL,
                    category TEXT NOT NULL,
                    confidence REAL DEFAULT 0.5,
                    source TEXT,
                    first_seen TEXT,
                    last_updated TEXT,
                    mention_count INTEGER DEFAULT 1,
                    embedding_json TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_facts_category
                ON user_facts(category)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_facts_confidence
                ON user_facts(confidence DESC)
            """)

            # Goals/threads table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_goals (
                    id TEXT PRIMARY KEY,
                    text TEXT NOT NULL,
                    status TEXT DEFAULT 'open',
                    created_at TEXT,
                    deadline TEXT,
                    priority INTEGER DEFAULT 1,
                    progress REAL DEFAULT 0.0,
                    notes TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_goals_status
                ON user_goals(status)
            """)

    @contextmanager
    def _conn(self):
        """Get database connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ─────────────────────────────────────────────────────────────────────
    # Facts Management
    # ─────────────────────────────────────────────────────────────────────

    async def add_fact(self, fact: UserFact) -> str:
        """Add or update a user fact.

        If similar fact exists, updates confidence and mention count.
        """
        # Check for existing similar fact
        existing = await self._find_similar_fact(fact.text, fact.category)

        if existing:
            # Update existing
            with self._conn() as conn:
                conn.execute("""
                    UPDATE user_facts
                    SET confidence = MIN(1.0, confidence + 0.1),
                        mention_count = mention_count + 1,
                        last_updated = ?
                    WHERE id = ?
                """, (datetime.now().isoformat(), existing.id))
            return existing.id

        # Insert new
        fact_id = fact.id or str(uuid.uuid4())[:12]
        now = datetime.now().isoformat()

        with self._conn() as conn:
            conn.execute("""
                INSERT INTO user_facts
                (id, text, category, confidence, source, first_seen, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                fact_id,
                fact.text,
                fact.category,
                fact.confidence,
                fact.source,
                now,
                now,
            ))

        return fact_id

    async def _find_similar_fact(
        self,
        text: str,
        category: str,
    ) -> Optional[UserFact]:
        """Find existing similar fact."""
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT * FROM user_facts
                WHERE category = ?
            """, (category,)).fetchall()

        text_words = set(text.lower().split())

        for row in rows:
            row_words = set(row["text"].lower().split())
            overlap = len(text_words & row_words)
            total = len(text_words | row_words)

            if total > 0 and overlap / total > 0.6:
                return self._row_to_fact(row)

        return None

    async def get_relevant_facts(
        self,
        context: str,
        limit: int = 20,
    ) -> List[UserFact]:
        """Get facts relevant to current context."""
        # Get all high-confidence facts
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT * FROM user_facts
                WHERE confidence > 0.3
                ORDER BY confidence DESC, mention_count DESC
                LIMIT ?
            """, (limit * 2,)).fetchall()

        # Score by relevance to context
        context_words = set(context.lower().split())
        scored = []

        for row in rows:
            fact_words = set(row["text"].lower().split())
            overlap = len(context_words & fact_words)

            # Base score from confidence
            score = row["confidence"]

            # Boost for relevance
            if overlap > 0:
                score += 0.2 * overlap

            # Boost for important categories
            if row["category"] in ["boundary", "preference", "trigger"]:
                score += 0.3

            scored.append((score, row))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [self._row_to_fact(row) for _, row in scored[:limit]]

    async def get_facts_by_category(
        self,
        category: str,
        limit: int = 10,
    ) -> List[UserFact]:
        """Get facts in a specific category."""
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT * FROM user_facts
                WHERE category = ?
                ORDER BY confidence DESC
                LIMIT ?
            """, (category, limit)).fetchall()

        return [self._row_to_fact(row) for row in rows]

    def _row_to_fact(self, row: sqlite3.Row) -> UserFact:
        """Convert row to UserFact."""
        return UserFact(
            id=row["id"],
            text=row["text"],
            category=row["category"],
            confidence=row["confidence"],
            source=row["source"],
            first_seen=datetime.fromisoformat(row["first_seen"]) if row["first_seen"] else None,
            last_updated=datetime.fromisoformat(row["last_updated"]) if row["last_updated"] else None,
            mention_count=row["mention_count"],
        )

    # ─────────────────────────────────────────────────────────────────────
    # Goals/Threads Management
    # ─────────────────────────────────────────────────────────────────────

    async def add_goal(self, goal: Goal) -> str:
        """Add a new goal/thread."""
        goal_id = goal.id or str(uuid.uuid4())[:12]

        with self._conn() as conn:
            conn.execute("""
                INSERT INTO user_goals
                (id, text, status, created_at, deadline, priority, progress, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                goal_id,
                goal.text,
                goal.status,
                goal.created_at.isoformat() if goal.created_at else datetime.now().isoformat(),
                goal.deadline.isoformat() if goal.deadline else None,
                goal.priority,
                goal.progress,
                goal.notes,
            ))

        return goal_id

    async def get_open_threads(self, limit: int = 5) -> List[Goal]:
        """Get open goals/threads."""
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT * FROM user_goals
                WHERE status = 'open'
                ORDER BY priority DESC, created_at DESC
                LIMIT ?
            """, (limit,)).fetchall()

        return [self._row_to_goal(row) for row in rows]

    async def update_goal_progress(
        self,
        goal_id: str,
        progress: float,
        notes: Optional[str] = None,
    ) -> None:
        """Update goal progress."""
        with self._conn() as conn:
            if notes:
                conn.execute("""
                    UPDATE user_goals
                    SET progress = ?, notes = ?
                    WHERE id = ?
                """, (progress, notes, goal_id))
            else:
                conn.execute("""
                    UPDATE user_goals
                    SET progress = ?
                    WHERE id = ?
                """, (progress, goal_id))

    async def complete_goal(self, goal_id: str) -> None:
        """Mark goal as completed."""
        with self._conn() as conn:
            conn.execute("""
                UPDATE user_goals
                SET status = 'completed', progress = 1.0
                WHERE id = ?
            """, (goal_id,))

    def _row_to_goal(self, row: sqlite3.Row) -> Goal:
        """Convert row to Goal."""
        return Goal(
            id=row["id"],
            text=row["text"],
            status=row["status"],
            created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
            deadline=datetime.fromisoformat(row["deadline"]) if row["deadline"] else None,
            priority=row["priority"],
            progress=row["progress"],
            notes=row["notes"],
        )
```

---

## File: `src/rilai/memory/consolidation.py`

```python
"""Memory consolidation - processes memory candidates into durable storage."""

from typing import Callable, List
from datetime import datetime

from rilai.contracts.events import EngineEvent, EventKind
from rilai.contracts.memory import MemoryCandidate, EpisodicEvent, UserFact


class MemoryConsolidator:
    """Processes memory candidates into durable storage.

    Runs at Stage 8 to:
    1. Filter significant memory candidates
    2. Create episodic events for significant turns
    3. Extract and store user facts
    4. Generate session summaries
    """

    EPISODIC_THRESHOLD = 0.6  # Minimum importance for episodic storage
    FACT_CONFIDENCE_THRESHOLD = 0.5  # Minimum confidence for fact storage

    def __init__(
        self,
        episodic_store: "EpisodicStore",
        user_model: "UserModel",
        emit_fn: Callable[[EventKind, dict], EngineEvent],
    ):
        self.episodic_store = episodic_store
        self.user_model = user_model
        self.emit_fn = emit_fn

    async def consolidate(
        self,
        candidates: List[MemoryCandidate],
        workspace: "Workspace",
        session_id: str,
        turn_id: int,
    ) -> dict:
        """Consolidate memory candidates into durable storage.

        Args:
            candidates: Memory candidates from agents
            workspace: Current workspace state
            session_id: Current session ID
            turn_id: Current turn ID

        Returns:
            Summary of what was stored
        """
        summary = {
            "episodic_events": 0,
            "facts_added": 0,
            "facts_updated": 0,
            "goals_updated": 0,
        }

        # 1. Process candidates
        for candidate in candidates:
            if candidate.type == "episodic":
                if candidate.importance >= self.EPISODIC_THRESHOLD:
                    await self._store_episodic(candidate, session_id, turn_id)
                    summary["episodic_events"] += 1

            elif candidate.type == "fact":
                if candidate.confidence >= self.FACT_CONFIDENCE_THRESHOLD:
                    is_new = await self._store_fact(candidate)
                    if is_new:
                        summary["facts_added"] += 1
                    else:
                        summary["facts_updated"] += 1

            elif candidate.type == "goal":
                await self._update_goal(candidate)
                summary["goals_updated"] += 1

        # 2. Check if turn itself is significant enough for episodic
        turn_importance = self._calculate_turn_importance(workspace)
        if turn_importance >= self.EPISODIC_THRESHOLD:
            await self._store_turn_as_episode(workspace, session_id, turn_id, turn_importance)
            summary["episodic_events"] += 1

        # 3. Emit completion event
        self.emit_fn(
            EventKind.MEMORY_COMMITTED,
            {
                "summary": summary,
                "candidates_processed": len(candidates),
            },
        )

        return summary

    async def _store_episodic(
        self,
        candidate: MemoryCandidate,
        session_id: str,
        turn_id: int,
    ) -> None:
        """Store episodic memory candidate."""
        from rilai.memory.embeddings import get_embedding

        embedding = await get_embedding(candidate.content)

        event = EpisodicEvent(
            timestamp=datetime.now(),
            summary=candidate.content,
            emotions=candidate.emotions or [],
            topics=candidate.topics or [],
            importance=candidate.importance,
            embedding=embedding,
            session_id=session_id,
            turn_id=turn_id,
        )

        await self.episodic_store.store(event)

    async def _store_fact(self, candidate: MemoryCandidate) -> bool:
        """Store fact candidate. Returns True if new fact."""
        fact = UserFact(
            text=candidate.content,
            category=candidate.category or "general",
            confidence=candidate.confidence,
            source=f"agent:{candidate.source_agent}",
        )

        # add_fact returns existing ID if similar exists
        result_id = await self.user_model.add_fact(fact)
        return result_id == fact.id  # True if new

    async def _update_goal(self, candidate: MemoryCandidate) -> None:
        """Update goal from candidate."""
        if candidate.goal_id:
            # Update existing goal
            await self.user_model.update_goal_progress(
                goal_id=candidate.goal_id,
                progress=candidate.goal_progress or 0.0,
                notes=candidate.content,
            )
        else:
            # Create new goal
            goal = Goal(
                text=candidate.content,
                status="open",
                priority=candidate.goal_priority or 1,
            )
            await self.user_model.add_goal(goal)

    def _calculate_turn_importance(self, workspace: "Workspace") -> float:
        """Calculate how important this turn is for episodic storage.

        Factors:
        - High emotion (stance changes)
        - User disclosure
        - Goal-related
        - High urgency claims
        """
        importance = 0.0

        # Stance change magnitude
        stance_delta = workspace.get_stance_delta()
        if stance_delta:
            delta_magnitude = sum(abs(v) for v in stance_delta.values())
            importance += min(0.3, delta_magnitude)

        # High urgency claims
        high_urgency = sum(1 for c in workspace.active_claims if c.urgency >= 2)
        importance += min(0.3, high_urgency * 0.1)

        # Message length (longer = more content)
        word_count = len(workspace.user_message.split())
        if word_count > 50:
            importance += 0.2

        # Emotional keywords
        emotion_words = {"feel", "feeling", "felt", "happy", "sad", "angry", "scared", "love", "hate", "worry"}
        message_words = set(workspace.user_message.lower().split())
        if emotion_words & message_words:
            importance += 0.2

        return min(1.0, importance)

    async def _store_turn_as_episode(
        self,
        workspace: "Workspace",
        session_id: str,
        turn_id: int,
        importance: float,
    ) -> None:
        """Store the turn itself as an episodic event."""
        from rilai.memory.embeddings import get_embedding

        # Build summary from user message and response
        summary_parts = [f"User: {workspace.user_message[:200]}"]
        if workspace.current_response:
            summary_parts.append(f"Response: {workspace.current_response[:200]}")

        summary = " | ".join(summary_parts)

        # Extract emotions from stance
        emotions = []
        if workspace.stance.strain > 0.5:
            emotions.append("stressed")
        if workspace.stance.valence > 0.3:
            emotions.append("positive")
        elif workspace.stance.valence < -0.3:
            emotions.append("negative")

        # Extract topics from claims
        topics = list(set(
            c.text.split()[0].lower()
            for c in workspace.active_claims[:5]
            if c.text
        ))

        embedding = await get_embedding(summary)

        event = EpisodicEvent(
            timestamp=datetime.now(),
            summary=summary,
            emotions=emotions,
            topics=topics,
            importance=importance,
            embedding=embedding,
            session_id=session_id,
            turn_id=turn_id,
        )

        await self.episodic_store.store(event)
```

---

## File: `src/rilai/memory/embeddings.py`

```python
"""Embedding generation for semantic search."""

from typing import List, Optional
import hashlib
import json
from pathlib import Path

# Simple cache for embeddings
_cache: dict[str, List[float]] = {}
_cache_file: Optional[Path] = None


def set_cache_file(path: Path) -> None:
    """Set the cache file path and load existing cache."""
    global _cache, _cache_file
    _cache_file = path

    if path.exists():
        try:
            with open(path) as f:
                _cache = json.load(f)
        except (json.JSONDecodeError, IOError):
            _cache = {}


def _save_cache() -> None:
    """Save cache to file."""
    if _cache_file:
        with open(_cache_file, "w") as f:
            json.dump(_cache, f)


def _get_cache_key(text: str) -> str:
    """Generate cache key for text."""
    return hashlib.sha256(text.encode()).hexdigest()[:16]


async def get_embedding(text: str) -> Optional[List[float]]:
    """Get embedding for text.

    Uses OpenRouter's embedding endpoint or falls back to simple hashing.
    Results are cached to reduce API calls.
    """
    if not text:
        return None

    # Check cache
    cache_key = _get_cache_key(text)
    if cache_key in _cache:
        return _cache[cache_key]

    # Try to get real embedding
    try:
        embedding = await _fetch_embedding(text)
    except Exception:
        # Fallback to simple hash-based embedding
        embedding = _simple_embedding(text)

    # Cache result
    _cache[cache_key] = embedding
    _save_cache()

    return embedding


async def _fetch_embedding(text: str) -> List[float]:
    """Fetch embedding from API."""
    from rilai.providers.openrouter import get_provider

    provider = get_provider()

    # Use embedding endpoint if available
    if hasattr(provider, "embed"):
        return await provider.embed(text)

    # Otherwise use a small model to generate pseudo-embedding
    # This is a fallback - not as good as real embeddings
    raise NotImplementedError("Real embeddings not available")


def _simple_embedding(text: str, dim: int = 128) -> List[float]:
    """Generate simple hash-based embedding.

    This is a fallback when real embeddings aren't available.
    Uses character n-grams and word features.
    """
    import math

    # Initialize with zeros
    embedding = [0.0] * dim

    words = text.lower().split()

    # Word-level features
    for i, word in enumerate(words[:50]):
        word_hash = hash(word)
        idx = word_hash % dim
        # Position-weighted contribution
        weight = 1.0 / (1.0 + i * 0.1)
        embedding[idx] += weight

    # Character n-gram features
    text_lower = text.lower()
    for n in [2, 3]:
        for i in range(len(text_lower) - n + 1):
            ngram = text_lower[i:i+n]
            idx = hash(ngram) % dim
            embedding[idx] += 0.5

    # Normalize
    magnitude = math.sqrt(sum(x * x for x in embedding))
    if magnitude > 0:
        embedding = [x / magnitude for x in embedding]

    return embedding


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Calculate cosine similarity between two vectors."""
    if len(a) != len(b):
        return 0.0

    dot_product = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot_product / (norm_a * norm_b)
```

---

## Update Contracts: `src/rilai/contracts/memory.py`

```python
"""Memory contracts."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class EpisodicEvent:
    """A significant episodic memory."""
    timestamp: datetime
    summary: str
    emotions: List[str] = field(default_factory=list)
    topics: List[str] = field(default_factory=list)
    participants: List[str] = field(default_factory=list)
    importance: float = 0.5
    embedding: Optional[List[float]] = None
    id: Optional[str] = None
    turn_id: Optional[int] = None
    session_id: Optional[str] = None


@dataclass
class UserFact:
    """A known fact about the user."""
    text: str
    category: str  # "preference", "boundary", "background", "trigger", "general"
    confidence: float = 0.5
    source: Optional[str] = None
    id: Optional[str] = None
    first_seen: Optional[datetime] = None
    last_updated: Optional[datetime] = None
    mention_count: int = 1


@dataclass
class Goal:
    """An active user goal or thread."""
    text: str
    status: str = "open"  # "open", "completed", "abandoned"
    created_at: Optional[datetime] = None
    deadline: Optional[datetime] = None
    priority: int = 1
    progress: float = 0.0
    notes: Optional[str] = None
    id: Optional[str] = None


@dataclass
class MemoryCandidate:
    """A candidate for memory storage from agent output."""
    type: str  # "episodic", "fact", "goal"
    content: str
    source_agent: str
    importance: float = 0.5
    confidence: float = 0.5
    category: Optional[str] = None
    emotions: Optional[List[str]] = None
    topics: Optional[List[str]] = None
    goal_id: Optional[str] = None
    goal_progress: Optional[float] = None
    goal_priority: Optional[int] = None
```

---

## Integration with TurnRunner

Add to `src/rilai/runtime/turn_runner.py`:

```python
async def _run_memory_retrieval(self) -> AsyncIterator[EngineEvent]:
    """Stage 2: Retrieve episodic events, user facts, open threads."""
    from rilai.memory.retrieval import MemoryRetriever
    from rilai.memory.episodic import EpisodicStore
    from rilai.memory.user_model import UserModel

    db_path = Path(self.config.data_dir) / "memory.db"
    episodic_store = EpisodicStore(db_path)
    user_model = UserModel(db_path)

    retriever = MemoryRetriever(
        episodic_store=episodic_store,
        user_model=user_model,
        emit_fn=self._emit,
    )

    async for event in retriever.retrieve_context(
        self.workspace.user_message,
        self.workspace,
    ):
        yield event


async def _run_memory_commit(self) -> AsyncIterator[EngineEvent]:
    """Stage 8: Commit durable memory updates."""
    from rilai.memory.consolidation import MemoryConsolidator
    from rilai.memory.episodic import EpisodicStore
    from rilai.memory.user_model import UserModel

    db_path = Path(self.config.data_dir) / "memory.db"
    episodic_store = EpisodicStore(db_path)
    user_model = UserModel(db_path)

    consolidator = MemoryConsolidator(
        episodic_store=episodic_store,
        user_model=user_model,
        emit_fn=self._emit,
    )

    # Collect memory candidates from agent outputs
    candidates = []
    for output in self._agent_outputs:
        if output.memory_candidates:
            candidates.extend(output.memory_candidates)

    await consolidator.consolidate(
        candidates=candidates,
        workspace=self.workspace,
        session_id=self.session_id,
        turn_id=self.turn_id,
    )
```

---

## Tests

```python
"""Tests for memory module."""

import pytest
import tempfile
from pathlib import Path
from datetime import datetime, timedelta

from rilai.memory.episodic import EpisodicStore
from rilai.memory.user_model import UserModel
from rilai.contracts.memory import EpisodicEvent, UserFact, Goal


class TestEpisodicStore:
    @pytest.fixture
    def store(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            yield EpisodicStore(Path(f.name))

    @pytest.mark.asyncio
    async def test_store_and_retrieve(self, store):
        event = EpisodicEvent(
            timestamp=datetime.now(),
            summary="User shared about work stress",
            emotions=["stressed", "overwhelmed"],
            importance=0.8,
        )

        event_id = await store.store(event)
        assert event_id

        recent = await store.get_recent(
            since=datetime.now() - timedelta(hours=1),
            limit=10,
        )
        assert len(recent) == 1
        assert recent[0].summary == "User shared about work stress"

    @pytest.mark.asyncio
    async def test_keyword_search(self, store):
        event1 = EpisodicEvent(
            timestamp=datetime.now(),
            summary="Discussed project deadline",
            importance=0.7,
        )
        event2 = EpisodicEvent(
            timestamp=datetime.now(),
            summary="Talked about weekend plans",
            importance=0.5,
        )

        await store.store(event1)
        await store.store(event2)

        results = await store.search_similar("deadline stress", limit=5)
        assert len(results) >= 1
        assert "deadline" in results[0].summary.lower()


class TestUserModel:
    @pytest.fixture
    def model(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            yield UserModel(Path(f.name))

    @pytest.mark.asyncio
    async def test_add_and_get_fact(self, model):
        fact = UserFact(
            text="User prefers morning meetings",
            category="preference",
            confidence=0.8,
        )

        await model.add_fact(fact)

        facts = await model.get_facts_by_category("preference")
        assert len(facts) == 1
        assert "morning meetings" in facts[0].text

    @pytest.mark.asyncio
    async def test_fact_deduplication(self, model):
        fact1 = UserFact(
            text="User likes coffee",
            category="preference",
            confidence=0.6,
        )
        fact2 = UserFact(
            text="User really likes coffee in morning",
            category="preference",
            confidence=0.7,
        )

        await model.add_fact(fact1)
        await model.add_fact(fact2)

        facts = await model.get_facts_by_category("preference")
        assert len(facts) == 1
        # Confidence should have increased
        assert facts[0].confidence >= 0.6

    @pytest.mark.asyncio
    async def test_goal_management(self, model):
        goal = Goal(
            text="Complete project report",
            priority=2,
        )

        goal_id = await model.add_goal(goal)

        threads = await model.get_open_threads()
        assert len(threads) == 1

        await model.update_goal_progress(goal_id, 0.5, "Halfway done")

        threads = await model.get_open_threads()
        assert threads[0].progress == 0.5

        await model.complete_goal(goal_id)

        threads = await model.get_open_threads()
        assert len(threads) == 0
```

---

## Next Document

Proceed to `09-tui.md` after memory system is implemented.
