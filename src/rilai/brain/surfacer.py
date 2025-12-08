"""
Surfacer Module

Decides when and how to surface queued suggestions to the user.
Respects interrupt budgets, quiet hours, and safe phrasing rules.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from rilai.core.events import Event, EventType, event_bus
from rilai.core.query import UserQueryEvent

if TYPE_CHECKING:
    from rilai.brain.daydream import DaydreamProcessor, Suggestion
    from rilai.proactive.budget import InterruptBudget

logger = logging.getLogger(__name__)


# Forbidden phrases that sound surveillance-like
FORBIDDEN_PHRASES = [
    "i heard you say",
    "i heard you tell",
    "i noticed you mentioned",
    "i noticed you said",
    "i've been tracking",
    "i've been listening",
    "i was listening when",
    "you told your",
    "you said to your",
    "i overheard",
]


@dataclass
class SurfacerConfig:
    """Configuration for the surfacer."""

    # Minimum confidence to surface without explicit query
    min_proactive_confidence: float = 0.8

    # Quiet hours (no proactive surfacing)
    quiet_hours_start: int = 22  # 10 PM
    quiet_hours_end: int = 8  # 8 AM

    # Maximum suggestions to surface per query
    max_per_query: int = 2

    # Whether to require explicit query for surfacing
    require_explicit_query: bool = False


@dataclass
class SurfaceResult:
    """Result of a surfacing decision."""

    should_surface: bool
    suggestions: list["Suggestion"] = field(default_factory=list)
    reason: str = ""
    safe_messages: list[str] = field(default_factory=list)


class Surfacer:
    """Decides when to surface suggestions to the user.

    Surfacing can happen:
    1. On explicit UserQueryEvent - check relevance and surface if relevant
    2. Proactively - only if high confidence AND respects budget/quiet hours
    3. On high stakes - urgent situations override normal rules
    """

    def __init__(
        self,
        daydream: "DaydreamProcessor",
        config: SurfacerConfig | None = None,
        budget: "InterruptBudget | None" = None,
    ):
        """Initialize the surfacer.

        Args:
            daydream: The daydream processor with queued suggestions
            config: Surfacer configuration
            budget: Optional interrupt budget for proactive surfacing
        """
        self.daydream = daydream
        self.config = config or SurfacerConfig()
        self.budget = budget

        # Statistics
        self._stats = {
            "queries_processed": 0,
            "suggestions_surfaced": 0,
            "suggestions_blocked": 0,
            "phrasing_violations": 0,
        }

    @property
    def stats(self) -> dict:
        return self._stats.copy()

    async def on_query(self, query: UserQueryEvent) -> SurfaceResult:
        """Handle a user query and decide what to surface.

        Args:
            query: The user's query

        Returns:
            SurfaceResult with suggestions to surface
        """
        self._stats["queries_processed"] += 1

        # Get relevant suggestions
        relevant = self.daydream.get_relevant_suggestions(
            query.text,
            max_results=self.config.max_per_query,
        )

        if not relevant:
            return SurfaceResult(
                should_surface=False,
                reason="no_relevant_suggestions",
            )

        # Validate phrasing for each suggestion
        safe_messages = []
        valid_suggestions = []

        for suggestion in relevant:
            phrasing = suggestion.safe_phrasing or suggestion.text

            if self._validate_phrasing(phrasing):
                safe_messages.append(phrasing)
                valid_suggestions.append(suggestion)
                self.daydream.mark_surfaced(suggestion.suggestion_id)
                self._stats["suggestions_surfaced"] += 1
            else:
                self._stats["phrasing_violations"] += 1
                logger.warning(f"Phrasing violation blocked: {phrasing[:50]}...")

        if not valid_suggestions:
            return SurfaceResult(
                should_surface=False,
                reason="all_blocked_by_phrasing",
            )

        # Emit event
        await event_bus.emit(
            Event(
                EventType.SUGGESTION_SURFACED,
                {
                    "query_id": query.query_id,
                    "suggestion_count": len(valid_suggestions),
                    "suggestion_ids": [s.suggestion_id for s in valid_suggestions],
                },
            )
        )

        return SurfaceResult(
            should_surface=True,
            suggestions=valid_suggestions,
            reason="relevant_to_query",
            safe_messages=safe_messages,
        )

    async def check_proactive(self) -> SurfaceResult:
        """Check if we should proactively surface any suggestions.

        This is called during idle time to see if any suggestions
        are confident enough to surface without explicit query.

        Returns:
            SurfaceResult with high-confidence suggestions
        """
        # Check quiet hours
        if self._is_quiet_hours():
            return SurfaceResult(
                should_surface=False,
                reason="quiet_hours",
            )

        # Check budget
        if self.budget and not self.budget.can_interrupt():
            return SurfaceResult(
                should_surface=False,
                reason="budget_exhausted",
            )

        # Get high-confidence suggestions
        high_confidence = [
            s for s in self.daydream.queued_suggestions
            if s.confidence >= self.config.min_proactive_confidence
        ]

        if not high_confidence:
            return SurfaceResult(
                should_surface=False,
                reason="no_high_confidence",
            )

        # Take the most confident one
        best = max(high_confidence, key=lambda s: s.confidence)
        phrasing = best.safe_phrasing or best.text

        if not self._validate_phrasing(phrasing):
            self._stats["phrasing_violations"] += 1
            return SurfaceResult(
                should_surface=False,
                reason="phrasing_violation",
            )

        # Consume budget
        if self.budget:
            self.budget.consume(1.0)  # Standard cost

        self.daydream.mark_surfaced(best.suggestion_id)
        self._stats["suggestions_surfaced"] += 1

        return SurfaceResult(
            should_surface=True,
            suggestions=[best],
            reason="proactive_high_confidence",
            safe_messages=[phrasing],
        )

    async def check_urgent(self, stakes: float) -> SurfaceResult:
        """Check if urgent situation requires immediate surfacing.

        Args:
            stakes: Current stakes level (0-1)

        Returns:
            SurfaceResult with urgent warnings if any
        """
        if stakes < 0.8:
            return SurfaceResult(
                should_surface=False,
                reason="stakes_not_urgent",
            )

        # Get warning suggestions
        warnings = [
            s for s in self.daydream.queued_suggestions
            if s.category == "warning"
        ]

        if not warnings:
            return SurfaceResult(
                should_surface=False,
                reason="no_warnings",
            )

        # Surface the most relevant warning
        best = max(warnings, key=lambda s: s.confidence)
        phrasing = best.safe_phrasing or best.text

        if not self._validate_phrasing(phrasing):
            # For urgent warnings, use a generic safe message
            phrasing = "Something important may need your attention."

        self.daydream.mark_surfaced(best.suggestion_id)
        self._stats["suggestions_surfaced"] += 1

        return SurfaceResult(
            should_surface=True,
            suggestions=[best],
            reason="urgent_warning",
            safe_messages=[phrasing],
        )

    def _validate_phrasing(self, text: str) -> bool:
        """Validate that phrasing doesn't sound surveillance-like.

        Args:
            text: The text to validate

        Returns:
            True if phrasing is safe, False if it violates rules
        """
        text_lower = text.lower()

        for forbidden in FORBIDDEN_PHRASES:
            if forbidden in text_lower:
                return False

        return True

    def _is_quiet_hours(self) -> bool:
        """Check if current time is in quiet hours."""
        hour = datetime.now().hour

        if self.config.quiet_hours_start > self.config.quiet_hours_end:
            # Spans midnight (e.g., 22:00 - 08:00)
            return hour >= self.config.quiet_hours_start or hour < self.config.quiet_hours_end
        else:
            # Same day (e.g., 00:00 - 06:00)
            return self.config.quiet_hours_start <= hour < self.config.quiet_hours_end

    def get_pending_count(self) -> int:
        """Get count of pending suggestions."""
        return len(self.daydream.queued_suggestions)

    def format_for_display(self, result: SurfaceResult) -> str:
        """Format a surface result for display to user.

        Args:
            result: The surface result

        Returns:
            Formatted string for display
        """
        if not result.should_surface:
            return ""

        lines = []
        for msg in result.safe_messages:
            lines.append(f"💡 {msg}")

        return "\n".join(lines)
