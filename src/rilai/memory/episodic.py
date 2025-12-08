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
            results = await self._search_by_embedding(query_embedding, limit, exclude_ids)
            if results:
                return results
            # Fall through to keyword search if no embedding matches

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
