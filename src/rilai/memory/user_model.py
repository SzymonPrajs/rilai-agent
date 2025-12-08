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
