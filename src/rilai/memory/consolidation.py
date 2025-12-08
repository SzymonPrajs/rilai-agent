"""Memory consolidation - promoting memories between storage tiers.

Handles the flow of information from:
- Working memory (ephemeral, in-context)
- Short-term memory (JSON files, session-scoped)
- Long-term memory (SQLite, permanent)

Consolidation runs periodically to:
1. Extract significant patterns from short-term
2. Promote important information to long-term
3. Compress and summarize older memories
4. Track memory access patterns
5. Link related memories together
"""

import logging
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from contextlib import contextmanager

logger = logging.getLogger(__name__)


@dataclass
class ConsolidationResult:
    """Result of a consolidation run."""

    items_reviewed: int
    items_promoted: int
    items_compressed: int
    errors: list[str]
    duration_ms: int


@dataclass
class MemoryCandidate:
    """A memory candidate for promotion."""

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    content: str = ""
    source: str = ""
    significance: float = 0.0  # 0.0 to 1.0
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class MemoryLink:
    """A link between two memories."""

    from_id: str
    to_id: str
    relationship: str  # supports, contradicts, exemplifies, related
    strength: float = 0.5  # 0.0 to 1.0
    created_at: datetime = field(default_factory=datetime.now)


class ConsolidationStore:
    """SQLite store for consolidated memories, access tracking, and links.

    Provides the backing storage for the consolidation system.
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_schema()

    def _init_schema(self) -> None:
        """Initialize database tables for consolidation."""
        with self._conn() as conn:
            # Consolidated memories table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS consolidated_memories (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    source TEXT NOT NULL,
                    significance REAL DEFAULT 0.5,
                    metadata_json TEXT,
                    created_at TEXT NOT NULL,
                    promoted_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    compressed_from_json TEXT,
                    is_compressed INTEGER DEFAULT 0
                )
            """)

            # Memory access tracking
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_access (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    memory_id TEXT NOT NULL,
                    accessed_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    access_type TEXT DEFAULT 'retrieval',
                    context TEXT,
                    FOREIGN KEY (memory_id) REFERENCES consolidated_memories(id)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_memory_access_memory_id
                ON memory_access(memory_id)
            """)

            # Memory links table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_links (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    from_id TEXT NOT NULL,
                    to_id TEXT NOT NULL,
                    relationship TEXT NOT NULL,
                    strength REAL DEFAULT 0.5,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(from_id, to_id, relationship)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_memory_links_from
                ON memory_links(from_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_memory_links_to
                ON memory_links(to_id)
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

    def store_memory(self, candidate: MemoryCandidate) -> str:
        """Store a consolidated memory."""
        import json

        with self._conn() as conn:
            conn.execute("""
                INSERT INTO consolidated_memories
                (id, content, source, significance, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                candidate.id,
                candidate.content,
                candidate.source,
                candidate.significance,
                json.dumps(candidate.metadata),
                candidate.created_at.isoformat(),
            ))
        return candidate.id

    def record_access(self, memory_id: str, access_type: str = "retrieval", context: str | None = None) -> None:
        """Record a memory access for tracking."""
        # Use explicit timestamp in ISO format for consistent comparison
        timestamp = datetime.now().isoformat()
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO memory_access (memory_id, accessed_at, access_type, context)
                VALUES (?, ?, ?, ?)
            """, (memory_id, timestamp, access_type, context))

    def get_access_count(self, memory_id: str, since: datetime | None = None) -> int:
        """Get access count for a memory."""
        with self._conn() as conn:
            if since:
                row = conn.execute("""
                    SELECT COUNT(*) as count FROM memory_access
                    WHERE memory_id = ? AND accessed_at >= ?
                """, (memory_id, since.isoformat())).fetchone()
            else:
                row = conn.execute("""
                    SELECT COUNT(*) as count FROM memory_access
                    WHERE memory_id = ?
                """, (memory_id,)).fetchone()
        return row["count"] if row else 0

    def create_link(self, link: MemoryLink) -> None:
        """Create a link between memories."""
        with self._conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO memory_links
                (from_id, to_id, relationship, strength, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (
                link.from_id,
                link.to_id,
                link.relationship,
                link.strength,
                link.created_at.isoformat(),
            ))

    def get_links(self, memory_id: str) -> list[MemoryLink]:
        """Get all links for a memory (both directions)."""
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT * FROM memory_links
                WHERE from_id = ? OR to_id = ?
            """, (memory_id, memory_id)).fetchall()

        return [
            MemoryLink(
                from_id=row["from_id"],
                to_id=row["to_id"],
                relationship=row["relationship"],
                strength=row["strength"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]

    def get_old_memories(self, older_than: datetime, limit: int = 100) -> list[dict]:
        """Get old uncompressed memories for potential compression."""
        import json

        with self._conn() as conn:
            rows = conn.execute("""
                SELECT * FROM consolidated_memories
                WHERE created_at < ? AND is_compressed = 0
                ORDER BY created_at ASC
                LIMIT ?
            """, (older_than.isoformat(), limit)).fetchall()

        return [
            {
                "id": row["id"],
                "content": row["content"],
                "source": row["source"],
                "significance": row["significance"],
                "metadata": json.loads(row["metadata_json"]) if row["metadata_json"] else {},
                "created_at": datetime.fromisoformat(row["created_at"]),
            }
            for row in rows
        ]

    def mark_compressed(self, memory_ids: list[str], summary_id: str) -> None:
        """Mark memories as compressed into a summary."""
        import json

        with self._conn() as conn:
            for memory_id in memory_ids:
                conn.execute("""
                    UPDATE consolidated_memories
                    SET is_compressed = 1, compressed_from_json = ?
                    WHERE id = ?
                """, (json.dumps({"summary_id": summary_id}), memory_id))


class MemoryConsolidator:
    """Handles memory promotion and compression.

    The consolidation process mimics human memory consolidation:
    - Frequently accessed memories become stronger
    - Emotionally significant memories are prioritized
    - Related memories are linked together
    - Old, unused memories fade
    """

    def __init__(
        self,
        db_path: Path | str,
        significance_threshold: float = 0.6,
        max_age_hours: int = 72,
        compression_age_days: int = 7,
    ):
        """Initialize the consolidator.

        Args:
            db_path: Path to consolidation SQLite database
            significance_threshold: Minimum significance for promotion
            max_age_hours: Maximum age for short-term memories before review
            compression_age_days: Days before memories are eligible for compression
        """
        self.store = ConsolidationStore(Path(db_path))
        self.significance_threshold = significance_threshold
        self.max_age_hours = max_age_hours
        self.compression_age_days = compression_age_days
        # Candidates collected from external sources
        self._pending_candidates: list[MemoryCandidate] = []

    def add_candidate(self, candidate: MemoryCandidate) -> None:
        """Add a candidate for consideration during next consolidation.

        Args:
            candidate: Memory candidate to consider
        """
        self._pending_candidates.append(candidate)

    def add_candidates_from_assessments(self, assessments: list[dict[str, Any]]) -> None:
        """Add candidates extracted from agent assessments.

        Args:
            assessments: List of agent assessment dicts with output, urgency, confidence
        """
        for assessment in assessments:
            significance = self._compute_significance(assessment)
            if significance > 0.3:  # Pre-filter low significance
                candidate = MemoryCandidate(
                    content=assessment.get("output", assessment.get("observation", "")),
                    source=f"agent:{assessment.get('agent_id', 'unknown')}",
                    significance=significance,
                    metadata={
                        "urgency": assessment.get("urgency", 0),
                        "confidence": assessment.get("confidence", 0),
                        "agent_id": assessment.get("agent_id"),
                        "turn_id": assessment.get("turn_id"),
                    },
                    created_at=datetime.fromisoformat(
                        assessment.get("timestamp", datetime.now().isoformat())
                    ),
                )
                self._pending_candidates.append(candidate)

    async def run_consolidation(self) -> ConsolidationResult:
        """Run a full consolidation cycle.

        Returns:
            ConsolidationResult with statistics
        """
        start_time = datetime.now()
        errors: list[str] = []
        items_reviewed = 0
        items_promoted = 0
        items_compressed = 0

        try:
            # Step 1: Review pending candidates
            candidates = self._pending_candidates
            items_reviewed = len(candidates)
            self._pending_candidates = []  # Clear after processing

            # Step 2: Score and filter candidates, promote significant ones
            for candidate in candidates:
                if candidate.significance >= self.significance_threshold:
                    try:
                        self._promote_to_long_term(candidate)
                        items_promoted += 1
                    except Exception as e:
                        errors.append(f"Promotion error: {e}")

            # Step 3: Compress old long-term memories
            compressed = await self._compress_old_memories()
            items_compressed = compressed

        except Exception as e:
            logger.error(f"Consolidation error: {e}")
            errors.append(str(e))

        duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

        return ConsolidationResult(
            items_reviewed=items_reviewed,
            items_promoted=items_promoted,
            items_compressed=items_compressed,
            errors=errors,
            duration_ms=duration_ms,
        )

    def _compute_significance(self, assessment: dict[str, Any]) -> float:
        """Compute significance score for an assessment.

        Factors:
        - Urgency (higher = more significant)
        - Confidence (higher = more significant)
        - Content length (moderate length preferred)

        Args:
            assessment: The assessment dict

        Returns:
            Significance score 0.0 to 1.0
        """
        urgency = assessment.get("urgency", 0)
        confidence = assessment.get("confidence", 0)
        content = assessment.get("output", "")

        # Urgency contributes 40%
        urgency_score = urgency / 3.0 * 0.4

        # Confidence contributes 30%
        confidence_score = confidence / 3.0 * 0.3

        # Content quality contributes 30%
        content_len = len(content)
        if content_len < 20:
            content_score = 0.1
        elif content_len < 500:
            content_score = 0.3
        else:
            content_score = 0.2  # Too long might be noise

        return urgency_score + confidence_score + content_score

    def _promote_to_long_term(self, candidate: MemoryCandidate) -> str:
        """Promote a memory candidate to long-term storage.

        Args:
            candidate: The candidate to promote

        Returns:
            ID of the stored memory
        """
        # Store the memory in the consolidation database
        memory_id = self.store.store_memory(candidate)

        logger.info(
            f"Promoted memory from {candidate.source}: "
            f"id={memory_id}, significance={candidate.significance:.2f}"
        )

        # Record initial access (the promotion itself)
        self.store.record_access(memory_id, access_type="promotion")

        return memory_id

    async def _compress_old_memories(self) -> int:
        """Compress old long-term memories.

        Old memories are summarized and linked together
        to reduce storage while preserving meaning.

        Returns:
            Number of memories compressed
        """
        # Find memories older than threshold
        cutoff = datetime.now() - timedelta(days=self.compression_age_days)
        old_memories = self.store.get_old_memories(cutoff, limit=50)

        if len(old_memories) < 3:
            # Not enough memories to compress
            return 0

        # Group memories by source/theme
        groups = self._group_related_memories(old_memories)
        compressed_count = 0

        for group in groups:
            if len(group) < 2:
                continue

            # Generate summary for the group
            summary = self._generate_summary(group)
            if not summary:
                continue

            # Create a new summary memory
            summary_candidate = MemoryCandidate(
                content=summary,
                source="compression",
                significance=max(m["significance"] for m in group),
                metadata={
                    "compressed_from": [m["id"] for m in group],
                    "original_count": len(group),
                    "date_range": {
                        "start": min(m["created_at"] for m in group).isoformat(),
                        "end": max(m["created_at"] for m in group).isoformat(),
                    },
                },
            )
            summary_id = self.store.store_memory(summary_candidate)

            # Mark original memories as compressed
            self.store.mark_compressed([m["id"] for m in group], summary_id)
            compressed_count += len(group)

            logger.info(f"Compressed {len(group)} memories into summary {summary_id}")

        return compressed_count

    def _group_related_memories(self, memories: list[dict]) -> list[list[dict]]:
        """Group related memories for compression.

        Groups by source and time proximity.
        """
        if not memories:
            return []

        # Simple grouping by source
        by_source: dict[str, list[dict]] = {}
        for mem in memories:
            source = mem["source"]
            if source not in by_source:
                by_source[source] = []
            by_source[source].append(mem)

        # Return groups with at least 2 memories
        return [group for group in by_source.values() if len(group) >= 2]

    def _generate_summary(self, memories: list[dict]) -> str | None:
        """Generate a summary of a group of memories.

        For now, uses simple concatenation. In production, could use an LLM.
        """
        if not memories:
            return None

        # Extract key points
        contents = [m["content"] for m in memories if m["content"]]
        if not contents:
            return None

        # Simple summary: combine unique sentences
        seen = set()
        unique_points = []
        for content in contents:
            # Split into sentences and dedupe
            sentences = content.replace(". ", ".\n").split("\n")
            for sentence in sentences:
                sentence = sentence.strip()
                if sentence and sentence not in seen:
                    seen.add(sentence)
                    unique_points.append(sentence)
                    if len(unique_points) >= 5:  # Limit summary length
                        break
            if len(unique_points) >= 5:
                break

        if not unique_points:
            return None

        return " ".join(unique_points)

    def compute_access_score(self, memory_id: str) -> float:
        """Compute an access score for a memory.

        Frequently accessed memories get higher scores.
        Score is based on recent access frequency with time decay.

        Args:
            memory_id: The memory to score

        Returns:
            Access score 0.0 to 1.0
        """
        # Recent accesses (last 7 days) weigh more
        recent_cutoff = datetime.now() - timedelta(days=7)
        recent_count = self.store.get_access_count(memory_id, since=recent_cutoff)

        # All-time accesses
        total_count = self.store.get_access_count(memory_id)

        # Compute score: recent accesses have 3x weight
        # Scale: 0 accesses = 0.0, 10+ recent accesses = 1.0
        weighted_count = recent_count * 3 + (total_count - recent_count)
        score = min(1.0, weighted_count / 10.0)

        return score

    def record_access(self, memory_id: str, context: str | None = None) -> None:
        """Record an access to a memory (for retrieval tracking).

        Args:
            memory_id: The accessed memory
            context: Optional context about the access
        """
        self.store.record_access(memory_id, access_type="retrieval", context=context)

    def link_memories(
        self, memory_id_1: str, memory_id_2: str, relationship: str, strength: float = 0.5
    ) -> None:
        """Create a link between two memories.

        Args:
            memory_id_1: First memory
            memory_id_2: Second memory
            relationship: Type of relationship (supports, contradicts, exemplifies, related)
            strength: Link strength 0.0-1.0
        """
        link = MemoryLink(
            from_id=memory_id_1,
            to_id=memory_id_2,
            relationship=relationship,
            strength=strength,
        )
        self.store.create_link(link)

        logger.debug(
            f"Linked memories {memory_id_1} <-> {memory_id_2}: "
            f"{relationship} (strength={strength:.2f})"
        )

    def get_linked_memories(self, memory_id: str) -> list[MemoryLink]:
        """Get all memories linked to a given memory.

        Args:
            memory_id: The memory to find links for

        Returns:
            List of MemoryLink objects
        """
        return self.store.get_links(memory_id)


class ConsolidationScheduler:
    """Schedules periodic consolidation runs.

    Runs consolidation at configurable intervals,
    typically during low-activity periods.
    """

    def __init__(
        self,
        consolidator: MemoryConsolidator,
        interval_minutes: int = 30,
    ):
        """Initialize the scheduler.

        Args:
            consolidator: The consolidator to run
            interval_minutes: Minutes between runs
        """
        self.consolidator = consolidator
        self.interval = timedelta(minutes=interval_minutes)
        self.last_run: datetime | None = None
        self._running = False
        self._total_runs = 0
        self._total_promoted = 0
        self._total_compressed = 0

    async def start(self) -> None:
        """Start the consolidation scheduler."""
        self._running = True
        logger.info(f"Consolidation scheduler started (interval: {self.interval})")

    async def stop(self) -> None:
        """Stop the consolidation scheduler."""
        self._running = False
        logger.info(
            f"Consolidation scheduler stopped. Stats: "
            f"runs={self._total_runs}, promoted={self._total_promoted}, "
            f"compressed={self._total_compressed}"
        )

    @property
    def is_running(self) -> bool:
        """Check if scheduler is running."""
        return self._running

    async def maybe_consolidate(self) -> ConsolidationResult | None:
        """Run consolidation if enough time has passed.

        Returns:
            ConsolidationResult if run, None otherwise
        """
        if not self._running:
            return None

        now = datetime.now()
        if self.last_run and (now - self.last_run) < self.interval:
            return None

        result = await self.consolidator.run_consolidation()
        self.last_run = now

        # Update stats
        self._total_runs += 1
        self._total_promoted += result.items_promoted
        self._total_compressed += result.items_compressed

        logger.info(
            f"Consolidation complete: reviewed={result.items_reviewed}, "
            f"promoted={result.items_promoted}, compressed={result.items_compressed}, "
            f"duration={result.duration_ms}ms"
        )

        return result

    async def force_consolidate(self) -> ConsolidationResult:
        """Force a consolidation run regardless of interval.

        Returns:
            ConsolidationResult from the run
        """
        result = await self.consolidator.run_consolidation()
        self.last_run = datetime.now()

        # Update stats
        self._total_runs += 1
        self._total_promoted += result.items_promoted
        self._total_compressed += result.items_compressed

        return result

    def get_stats(self) -> dict[str, Any]:
        """Get scheduler statistics.

        Returns:
            Dict with run stats
        """
        return {
            "total_runs": self._total_runs,
            "total_promoted": self._total_promoted,
            "total_compressed": self._total_compressed,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "is_running": self._running,
            "interval_minutes": self.interval.total_seconds() / 60,
        }
