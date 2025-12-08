"""
Daydream Module

Hypothesis generation during idle time (IDLE_DAYDREAM mode).
Generates suggestions from accumulated evidence and queues them for later surfacing.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, TYPE_CHECKING

from rilai.core.events import Event, EventType, event_bus

if TYPE_CHECKING:
    from rilai.memory.relational import EvidenceShard, RelationalHypothesis

logger = logging.getLogger(__name__)


@dataclass
class Suggestion:
    """A suggestion generated during daydreaming.

    Suggestions are queued and only surfaced when:
    - User explicitly asks (UserQueryEvent)
    - High confidence + relevance to current context
    - High stakes situation
    """

    suggestion_id: str
    text: str
    confidence: float  # 0-1, how confident we are this is useful
    evidence_ids: list[str]  # Links to supporting evidence
    category: str  # "preference", "reminder", "insight", "warning"
    created_at: datetime = field(default_factory=datetime.now)

    # Surfacing metadata
    surfaced: bool = False
    surfaced_at: datetime | None = None
    dismissed: bool = False

    # Safe phrasing
    safe_phrasing: str | None = None  # Pre-generated safe version

    def to_dict(self) -> dict:
        return {
            "suggestion_id": self.suggestion_id,
            "text": self.text,
            "confidence": self.confidence,
            "evidence_ids": self.evidence_ids,
            "category": self.category,
            "created_at": self.created_at.isoformat(),
            "surfaced": self.surfaced,
            "surfaced_at": self.surfaced_at.isoformat() if self.surfaced_at else None,
            "dismissed": self.dismissed,
            "safe_phrasing": self.safe_phrasing,
        }


@dataclass
class DaydreamConfig:
    """Configuration for daydream processing."""

    # Minimum confidence to queue a suggestion
    min_confidence: float = 0.6

    # Maximum suggestions to generate per daydream cycle
    max_suggestions_per_cycle: int = 3

    # Categories to generate suggestions for
    enabled_categories: list[str] = field(
        default_factory=lambda: ["preference", "reminder", "insight", "warning"]
    )


class DaydreamProcessor:
    """Generates suggestions during idle time.

    Runs when the system is in IDLE_DAYDREAM mode.
    Processes accumulated evidence to generate useful suggestions
    that can be surfaced later when relevant.
    """

    def __init__(
        self,
        config: DaydreamConfig | None = None,
        on_suggestion: Callable[[Suggestion], None] | None = None,
    ):
        """Initialize the daydream processor.

        Args:
            config: Daydream configuration
            on_suggestion: Callback when a suggestion is generated
        """
        self.config = config or DaydreamConfig()
        self._on_suggestion = on_suggestion

        # Suggestion queue
        self._suggestions: dict[str, Suggestion] = {}

        # Statistics
        self._stats = {
            "cycles_run": 0,
            "suggestions_generated": 0,
            "suggestions_surfaced": 0,
            "suggestions_dismissed": 0,
        }

    @property
    def queued_suggestions(self) -> list[Suggestion]:
        """Get all queued (unsurfaced) suggestions."""
        return [s for s in self._suggestions.values() if not s.surfaced and not s.dismissed]

    @property
    def stats(self) -> dict:
        return self._stats.copy()

    async def process_evidence(
        self,
        evidence: list["EvidenceShard"],
        context: dict | None = None,
    ) -> list[Suggestion]:
        """Process evidence and generate suggestions.

        This is called during IDLE_DAYDREAM mode to generate
        suggestions from accumulated evidence.

        Args:
            evidence: List of evidence shards to process
            context: Optional context (current topics, time, etc.)

        Returns:
            List of generated suggestions
        """
        self._stats["cycles_run"] += 1
        generated = []

        # Group evidence by type
        by_type: dict[str, list] = {}
        for shard in evidence:
            if shard.type not in by_type:
                by_type[shard.type] = []
            by_type[shard.type].append(shard)

        # Generate suggestions for each category
        if "preference" in self.config.enabled_categories:
            suggestions = self._generate_preference_suggestions(
                by_type.get("preference", [])
            )
            generated.extend(suggestions)

        if "reminder" in self.config.enabled_categories:
            suggestions = self._generate_reminder_suggestions(
                by_type.get("commitment", [])
            )
            generated.extend(suggestions)

        if "warning" in self.config.enabled_categories:
            # High stakes evidence (boundaries, vulnerabilities)
            high_stakes = by_type.get("boundary", []) + by_type.get("vulnerability", [])
            suggestions = self._generate_warning_suggestions(high_stakes)
            generated.extend(suggestions)

        # Limit suggestions per cycle
        generated = generated[: self.config.max_suggestions_per_cycle]

        # Queue suggestions
        for suggestion in generated:
            self._suggestions[suggestion.suggestion_id] = suggestion
            self._stats["suggestions_generated"] += 1

            # Emit event
            await event_bus.emit(
                Event(
                    EventType.SUGGESTION_QUEUED,
                    {
                        "suggestion_id": suggestion.suggestion_id,
                        "category": suggestion.category,
                        "confidence": suggestion.confidence,
                    },
                )
            )

            # Callback
            if self._on_suggestion:
                self._on_suggestion(suggestion)

        logger.info(f"Daydream cycle: generated {len(generated)} suggestions")
        return generated

    def _generate_preference_suggestions(
        self, evidence: list["EvidenceShard"]
    ) -> list[Suggestion]:
        """Generate suggestions from preference evidence."""
        suggestions = []

        for shard in evidence:
            if shard.confidence < self.config.min_confidence:
                continue

            # Generate a suggestion that could be surfaced later
            suggestion = Suggestion(
                suggestion_id=str(uuid.uuid4()),
                text=f"User preference noted: {shard.quote[:100]}",
                confidence=shard.confidence,
                evidence_ids=[shard.shard_id],
                category="preference",
                # Safe phrasing - never say "I heard you say"
                safe_phrasing=self._make_safe_preference_phrasing(shard.quote),
            )
            suggestions.append(suggestion)

        return suggestions

    def _generate_reminder_suggestions(
        self, evidence: list["EvidenceShard"]
    ) -> list[Suggestion]:
        """Generate reminder suggestions from commitments."""
        suggestions = []

        for shard in evidence:
            if shard.confidence < self.config.min_confidence:
                continue

            suggestion = Suggestion(
                suggestion_id=str(uuid.uuid4()),
                text=f"Commitment to follow up: {shard.quote[:100]}",
                confidence=shard.confidence,
                evidence_ids=[shard.shard_id],
                category="reminder",
                safe_phrasing=self._make_safe_reminder_phrasing(shard.quote),
            )
            suggestions.append(suggestion)

        return suggestions

    def _generate_warning_suggestions(
        self, evidence: list["EvidenceShard"]
    ) -> list[Suggestion]:
        """Generate warning suggestions from high-stakes evidence."""
        suggestions = []

        for shard in evidence:
            # Warnings need higher confidence
            if shard.confidence < 0.7:
                continue

            suggestion = Suggestion(
                suggestion_id=str(uuid.uuid4()),
                text=f"High stakes item: {shard.quote[:100]}",
                confidence=shard.confidence,
                evidence_ids=[shard.shard_id],
                category="warning",
                safe_phrasing=self._make_safe_warning_phrasing(shard.quote),
            )
            suggestions.append(suggestion)

        return suggestions

    def _make_safe_preference_phrasing(self, quote: str) -> str:
        """Generate safe phrasing for a preference.

        NEVER: "I heard you say you like..."
        OK: "I have a note about... want me to include it?"
        """
        # Extract the key preference (simplified)
        key_words = quote.split()[:10]
        summary = " ".join(key_words)

        return f"I have a note from earlier: {summary}... — want to include this?"

    def _make_safe_reminder_phrasing(self, quote: str) -> str:
        """Generate safe phrasing for a reminder."""
        key_words = quote.split()[:10]
        summary = " ".join(key_words)

        return f"Quick reminder about: {summary}..."

    def _make_safe_warning_phrasing(self, quote: str) -> str:
        """Generate safe phrasing for a warning."""
        return "Something came up that might need attention."

    def mark_surfaced(self, suggestion_id: str) -> None:
        """Mark a suggestion as surfaced."""
        if suggestion_id in self._suggestions:
            self._suggestions[suggestion_id].surfaced = True
            self._suggestions[suggestion_id].surfaced_at = datetime.now()
            self._stats["suggestions_surfaced"] += 1

    def mark_dismissed(self, suggestion_id: str) -> None:
        """Mark a suggestion as dismissed."""
        if suggestion_id in self._suggestions:
            self._suggestions[suggestion_id].dismissed = True
            self._stats["suggestions_dismissed"] += 1

    def get_relevant_suggestions(
        self,
        query: str,
        max_results: int = 3,
    ) -> list[Suggestion]:
        """Get suggestions relevant to a query.

        Args:
            query: The user's query text
            max_results: Maximum suggestions to return

        Returns:
            List of relevant suggestions, sorted by confidence
        """
        query_lower = query.lower()
        relevant = []

        for suggestion in self.queued_suggestions:
            # Simple keyword matching (could be improved with embeddings)
            if any(word in suggestion.text.lower() for word in query_lower.split()):
                relevant.append(suggestion)

        # Sort by confidence
        relevant.sort(key=lambda s: s.confidence, reverse=True)

        return relevant[:max_results]

    def clear_old_suggestions(self, max_age_hours: int = 24) -> int:
        """Clear suggestions older than max_age_hours.

        Args:
            max_age_hours: Maximum age in hours

        Returns:
            Number of suggestions cleared
        """
        from datetime import timedelta

        cutoff = datetime.now() - timedelta(hours=max_age_hours)
        to_remove = []

        for sid, suggestion in self._suggestions.items():
            if suggestion.created_at < cutoff:
                to_remove.append(sid)

        for sid in to_remove:
            del self._suggestions[sid]

        return len(to_remove)
