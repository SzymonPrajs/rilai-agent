"""Memory consolidation - promoting memories between storage tiers.

Handles the flow of information from:
- Working memory (ephemeral, in-context)
- Short-term memory (JSON files, session-scoped)
- Long-term memory (SQLite, permanent)

Consolidation runs periodically to:
1. Extract significant patterns from short-term
2. Promote important information to long-term
3. Compress and summarize older memories
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from rilai.memory.database import Database
from rilai.memory.short_term import ShortTermMemory

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

    content: str
    source: str
    significance: float  # 0.0 to 1.0
    metadata: dict[str, Any]
    created_at: datetime


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
        db: Database,
        stm: ShortTermMemory | None = None,
        significance_threshold: float = 0.6,
        max_age_hours: int = 72,
    ):
        """Initialize the consolidator.

        Args:
            db: Database for long-term storage
            stm: Short-term memory (optional)
            significance_threshold: Minimum significance for promotion
            max_age_hours: Maximum age for short-term memories before review
        """
        self.db = db
        self.stm = stm
        self.significance_threshold = significance_threshold
        self.max_age_hours = max_age_hours

    async def run_consolidation(self) -> ConsolidationResult:
        """Run a full consolidation cycle.

        Returns:
            ConsolidationResult with statistics
        """
        start_time = datetime.now()
        errors = []
        items_reviewed = 0
        items_promoted = 0
        items_compressed = 0

        try:
            # Step 1: Review short-term memories
            if self.stm:
                candidates = self._extract_candidates_from_stm()
                items_reviewed += len(candidates)

                # Step 2: Score and filter candidates
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

    def _extract_candidates_from_stm(self) -> list[MemoryCandidate]:
        """Extract promotion candidates from short-term memory.

        Returns:
            List of memory candidates with significance scores
        """
        candidates = []

        if not self.stm:
            return candidates

        # Get recent assessments that might be significant
        # High urgency or confidence signals significance
        for agent_id, history in self.stm._agent_history.items():
            for assessment in history:
                significance = self._compute_significance(assessment)
                if significance > 0.3:  # Pre-filter low significance
                    candidates.append(
                        MemoryCandidate(
                            content=assessment.get("output", ""),
                            source=f"agent:{agent_id}",
                            significance=significance,
                            metadata={
                                "urgency": assessment.get("urgency", 0),
                                "confidence": assessment.get("confidence", 0),
                                "agent_id": agent_id,
                            },
                            created_at=datetime.fromisoformat(
                                assessment.get("timestamp", datetime.now().isoformat())
                            ),
                        )
                    )

        return candidates

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

    def _promote_to_long_term(self, candidate: MemoryCandidate) -> None:
        """Promote a memory candidate to long-term storage.

        Args:
            candidate: The candidate to promote
        """
        # Store as a special long-term memory entry
        # This would be implemented based on the schema
        # For now, we log the promotion
        logger.info(
            f"Promoting memory from {candidate.source}: "
            f"significance={candidate.significance:.2f}"
        )

        # In a full implementation, this would:
        # 1. Create a consolidated memory record
        # 2. Link to related memories
        # 3. Update access patterns

    async def _compress_old_memories(self) -> int:
        """Compress old long-term memories.

        Old memories are summarized and linked together
        to reduce storage while preserving meaning.

        Returns:
            Number of memories compressed
        """
        # This would implement memory compression:
        # 1. Find memories older than threshold
        # 2. Group related memories
        # 3. Generate summaries
        # 4. Replace detailed entries with summaries

        # Placeholder - compression not yet implemented
        return 0

    def compute_access_score(self, memory_id: str) -> float:
        """Compute an access score for a memory.

        Frequently accessed memories get higher scores.

        Args:
            memory_id: The memory to score

        Returns:
            Access score 0.0 to 1.0
        """
        # Would track access patterns
        # For now, return a default
        return 0.5

    def link_memories(
        self, memory_id_1: str, memory_id_2: str, relationship: str
    ) -> None:
        """Create a link between two memories.

        Args:
            memory_id_1: First memory
            memory_id_2: Second memory
            relationship: Type of relationship
        """
        # Would create memory links in the database
        logger.debug(
            f"Linking memories {memory_id_1} <-> {memory_id_2}: {relationship}"
        )


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

    async def start(self) -> None:
        """Start the consolidation scheduler."""
        self._running = True
        logger.info(f"Consolidation scheduler started (interval: {self.interval})")

    async def stop(self) -> None:
        """Stop the consolidation scheduler."""
        self._running = False
        logger.info("Consolidation scheduler stopped")

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

        logger.info(
            f"Consolidation complete: reviewed={result.items_reviewed}, "
            f"promoted={result.items_promoted}, duration={result.duration_ms}ms"
        )

        return result
