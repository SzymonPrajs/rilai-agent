"""
Proactive Store

Storage for proactive intervention items at different levels.
Handles queuing for daily digest (L1) and on-open ping (L2).
"""

import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from rilai.proactive.ladder import InterventionLevel, InterventionScore

logger = logging.getLogger(__name__)


@dataclass
class ProactiveItem:
    """An item queued for proactive surfacing."""

    item_id: str
    level: InterventionLevel
    intervention_score: InterventionScore
    message: str
    created_at: datetime
    expires_at: datetime | None = None
    context_summary: str = ""
    source_agents: list[str] = field(default_factory=list)
    domain: str = "general"

    # Delivery tracking
    delivered: bool = False
    delivered_at: datetime | None = None
    user_response: str | None = None  # Did they engage?

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "level": self.level.value,
            "message": self.message,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "context_summary": self.context_summary,
            "source_agents": self.source_agents,
            "domain": self.domain,
            "delivered": self.delivered,
            "delivered_at": self.delivered_at.isoformat() if self.delivered_at else None,
            "user_response": self.user_response,
            "intervention_score": self.intervention_score.to_dict(),
        }

    @classmethod
    def create(
        cls,
        level: InterventionLevel,
        intervention_score: InterventionScore,
        message: str,
        context_summary: str = "",
        expires_in_hours: float | None = None,
    ) -> "ProactiveItem":
        """Create a new proactive item."""
        expires_at = None
        if expires_in_hours:
            expires_at = datetime.now() + timedelta(hours=expires_in_hours)

        return cls(
            item_id=f"pi_{uuid.uuid4().hex[:8]}",
            level=level,
            intervention_score=intervention_score,
            message=message,
            created_at=datetime.now(),
            expires_at=expires_at,
            context_summary=context_summary,
            source_agents=intervention_score.source_agents,
            domain=intervention_score.domain,
        )


class ProactiveStore:
    """Storage for proactive intervention items.

    Manages:
    - L0: Silent log to SQLite
    - L1: Digest queue (pending items for daily/weekly summary)
    - L2: On-open queue (items to show when TUI opens)
    - L3/L4: Logged after delivery
    """

    def __init__(self, data_dir: Path):
        """Initialize proactive store.

        Args:
            data_dir: Directory for storage files
        """
        self.data_dir = data_dir
        self.db_path = data_dir / "proactive.db"

        # In-memory queues for active items
        self.digest_queue: list[ProactiveItem] = []  # L1 items
        self.on_open_queue: list[ProactiveItem] = []  # L2 items

        self._init_db()

    def _init_db(self) -> None:
        """Initialize SQLite schema."""
        self.data_dir.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(self.db_path)
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS proactive_items (
                    item_id TEXT PRIMARY KEY,
                    level INTEGER NOT NULL,
                    message TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    context_summary TEXT,
                    source_agents TEXT,  -- JSON array

                    -- Score components
                    stakes REAL NOT NULL,
                    confidence REAL NOT NULL,
                    reversibility_gain REAL NOT NULL,
                    calibrated_score REAL NOT NULL,

                    -- Timestamps
                    created_at TEXT NOT NULL,
                    expires_at TEXT,
                    delivered_at TEXT,

                    -- Delivery status
                    delivered INTEGER DEFAULT 0,
                    user_response TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_proactive_level ON proactive_items(level);
                CREATE INDEX IF NOT EXISTS idx_proactive_delivered ON proactive_items(delivered);
                CREATE INDEX IF NOT EXISTS idx_proactive_created ON proactive_items(created_at);
            """
            )
            conn.commit()
        finally:
            conn.close()

    def add_item(self, item: ProactiveItem) -> None:
        """Add item to appropriate queue based on level.

        Args:
            item: ProactiveItem to store
        """
        if item.level == InterventionLevel.SILENT:
            self._log_silent(item)
        elif item.level == InterventionLevel.DIGEST:
            self.digest_queue.append(item)
            self._persist_item(item)
        elif item.level == InterventionLevel.ON_OPEN:
            self.on_open_queue.append(item)
            self._persist_item(item)
        else:
            # L3/L4 are delivered immediately, but log them
            self._persist_item(item)

    def _log_silent(self, item: ProactiveItem) -> None:
        """Log L0 item to database without queuing."""
        self._persist_item(item, delivered=True)
        logger.debug(f"Silent log: {item.message[:50]}...")

    def _persist_item(self, item: ProactiveItem, delivered: bool = False) -> None:
        """Persist item to SQLite."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO proactive_items
                (item_id, level, message, domain, context_summary, source_agents,
                 stakes, confidence, reversibility_gain, calibrated_score,
                 created_at, expires_at, delivered_at, delivered, user_response)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    item.item_id,
                    item.level.value,
                    item.message,
                    item.domain,
                    item.context_summary,
                    json.dumps(item.source_agents),
                    item.intervention_score.stakes,
                    item.intervention_score.confidence,
                    item.intervention_score.reversibility_gain,
                    item.intervention_score.calibrated_score,
                    item.created_at.isoformat(),
                    item.expires_at.isoformat() if item.expires_at else None,
                    item.delivered_at.isoformat() if item.delivered_at else None,
                    1 if delivered or item.delivered else 0,
                    item.user_response,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def mark_delivered(self, item_id: str, user_response: str | None = None) -> None:
        """Mark an item as delivered.

        Args:
            item_id: ID of the item
            user_response: Optional user response/engagement
        """
        now = datetime.now()

        # Update in-memory queues
        for queue in [self.digest_queue, self.on_open_queue]:
            for item in queue:
                if item.item_id == item_id:
                    item.delivered = True
                    item.delivered_at = now
                    item.user_response = user_response

        # Update database
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """
                UPDATE proactive_items
                SET delivered = 1, delivered_at = ?, user_response = ?
                WHERE item_id = ?
            """,
                (now.isoformat(), user_response, item_id),
            )
            conn.commit()
        finally:
            conn.close()

    def get_digest_items(
        self, since: datetime | None = None, limit: int = 50
    ) -> list[ProactiveItem]:
        """Get L1 items for digest generation.

        Args:
            since: Only items after this time
            limit: Maximum items to return

        Returns:
            List of ProactiveItems
        """
        if since is None:
            since = datetime.now() - timedelta(days=1)

        # Filter in-memory queue
        items = [
            item
            for item in self.digest_queue
            if item.created_at >= since and not item.delivered
        ]

        return items[:limit]

    def get_on_open_items(self) -> list[ProactiveItem]:
        """Get L2 items to show when TUI opens.

        Returns:
            List of undelivered L2 items
        """
        now = datetime.now()

        # Filter expired and delivered
        items = [
            item
            for item in self.on_open_queue
            if not item.delivered
            and (item.expires_at is None or item.expires_at > now)
        ]

        return items

    def generate_daily_digest(self, since: datetime | None = None) -> str:
        """Generate markdown digest of L1 items.

        Args:
            since: Start time for digest (default: last 24h)

        Returns:
            Markdown formatted digest
        """
        items = self.get_digest_items(since)

        if not items:
            return ""

        # Group by domain
        by_domain: dict[str, list[ProactiveItem]] = {}
        for item in items:
            if item.domain not in by_domain:
                by_domain[item.domain] = []
            by_domain[item.domain].append(item)

        lines = ["## Daily Observations\n"]

        for domain, domain_items in sorted(by_domain.items()):
            lines.append(f"### {domain.title()}")
            for item in domain_items:
                lines.append(f"- {item.message}")
                if item.context_summary:
                    lines.append(f"  _{item.context_summary}_")
            lines.append("")

        return "\n".join(lines)

    def cleanup_expired(self) -> int:
        """Remove expired items from queues.

        Returns:
            Number of items removed
        """
        now = datetime.now()
        removed = 0

        # Clean in-memory queues
        for queue in [self.digest_queue, self.on_open_queue]:
            before = len(queue)
            queue[:] = [
                item
                for item in queue
                if item.expires_at is None or item.expires_at > now
            ]
            removed += before - len(queue)

        return removed

    def get_stats(self) -> dict:
        """Get storage statistics.

        Returns:
            Dictionary of statistics
        """
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(
                """
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN delivered = 1 THEN 1 ELSE 0 END) as delivered,
                    SUM(CASE WHEN level = 0 THEN 1 ELSE 0 END) as l0,
                    SUM(CASE WHEN level = 1 THEN 1 ELSE 0 END) as l1,
                    SUM(CASE WHEN level = 2 THEN 1 ELSE 0 END) as l2,
                    SUM(CASE WHEN level = 3 THEN 1 ELSE 0 END) as l3,
                    SUM(CASE WHEN level = 4 THEN 1 ELSE 0 END) as l4
                FROM proactive_items
            """
            )
            row = cursor.fetchone()

            return {
                "total_items": row[0] or 0,
                "delivered": row[1] or 0,
                "by_level": {
                    "L0": row[2] or 0,
                    "L1": row[3] or 0,
                    "L2": row[4] or 0,
                    "L3": row[5] or 0,
                    "L4": row[6] or 0,
                },
                "digest_queue_size": len(self.digest_queue),
                "on_open_queue_size": len(self.on_open_queue),
            }
        finally:
            conn.close()
