"""
Mode Manager

State machine for managing operating modes in ambient cognitive processing.

Modes:
- AMBIENT_INGEST: Continuous low-power monitoring
- IDLE_DAYDREAM: Background hypothesis generation
- INTERACTIVE_ASSIST: Full agent pipeline (user interaction)
- PROACTIVE_NUDGE: Generating proactive nudges
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Callable, Literal

from rilai.core.events import Event, EventType, event_bus

logger = logging.getLogger(__name__)


class OperatingMode(Enum):
    """Operating modes for the ambient cognitive co-processor."""

    AMBIENT_INGEST = "ambient_ingest"
    """Continuous monitoring with tiny models. Low power, always-on."""

    IDLE_DAYDREAM = "idle_daydream"
    """Background reflection and hypothesis generation. Runs when idle."""

    INTERACTIVE_ASSIST = "interactive_assist"
    """Full agent pipeline for user interaction. High power."""

    PROACTIVE_NUDGE = "proactive_nudge"
    """Generating and delivering proactive nudges. Medium power."""


@dataclass
class ModeState:
    """Current state of the mode manager."""

    current_mode: OperatingMode
    entered_at: datetime
    last_user_interaction: datetime | None = None
    accumulated_stakes: float = 0.0  # Rolling max of stakes estimates
    pending_nudges: list[str] = field(default_factory=list)
    active_hypotheses: int = 0

    def time_in_mode(self) -> timedelta:
        """Get time spent in current mode."""
        return datetime.now() - self.entered_at

    def time_since_user_interaction(self) -> timedelta | None:
        """Get time since last user interaction."""
        if self.last_user_interaction:
            return datetime.now() - self.last_user_interaction
        return None


@dataclass
class ModeTransition:
    """Record of a mode transition."""

    from_mode: OperatingMode
    to_mode: OperatingMode
    trigger: str
    timestamp: datetime = field(default_factory=datetime.now)


class ModeManager:
    """Orchestrates mode transitions and resource allocation.

    The mode manager determines which operating mode the system should be in
    based on various signals:
    - Stakes level from ambient processing
    - User interaction patterns
    - Hypothesis confidence levels
    - Time-based transitions
    """

    # Transition thresholds
    STAKES_THRESHOLD = 0.7  # Stakes level to escalate to interactive
    NUDGE_CONFIDENCE_THRESHOLD = 0.8  # Confidence needed for proactive nudge
    DAYDREAM_TIMEOUT = timedelta(seconds=60)  # Idle time before daydreaming
    USER_IDLE_TIMEOUT = timedelta(seconds=30)  # User idle time

    # Resource allocation per mode
    RESOURCE_BUDGETS = {
        OperatingMode.AMBIENT_INGEST: {
            "model_tier": "tiny",
            "max_concurrent_calls": 3,
            "timeout_ms": 2000,
            "agencies_active": ["monitoring"],
        },
        OperatingMode.IDLE_DAYDREAM: {
            "model_tier": "small",
            "max_concurrent_calls": 2,
            "timeout_ms": 5000,
            "agencies_active": ["planning", "self", "reasoning"],
        },
        OperatingMode.INTERACTIVE_ASSIST: {
            "model_tier": "medium",
            "max_concurrent_calls": 10,
            "timeout_ms": 15000,
            "agencies_active": "all",
        },
        OperatingMode.PROACTIVE_NUDGE: {
            "model_tier": "medium",
            "max_concurrent_calls": 3,
            "timeout_ms": 10000,
            "agencies_active": ["planning", "social", "execution"],
        },
    }

    def __init__(
        self,
        initial_mode: OperatingMode = OperatingMode.IDLE_DAYDREAM,
        on_transition: Callable[[ModeTransition], None] | None = None,
    ):
        """Initialize mode manager.

        Args:
            initial_mode: Starting operating mode
            on_transition: Callback for mode transitions
        """
        self._state = ModeState(
            current_mode=initial_mode,
            entered_at=datetime.now(),
        )
        self._on_transition = on_transition
        self._transition_history: list[ModeTransition] = []

    @property
    def current_mode(self) -> OperatingMode:
        """Get current operating mode."""
        return self._state.current_mode

    @property
    def state(self) -> ModeState:
        """Get current state."""
        return self._state

    @property
    def resource_budget(self) -> dict:
        """Get resource budget for current mode."""
        return self.RESOURCE_BUDGETS.get(
            self._state.current_mode,
            self.RESOURCE_BUDGETS[OperatingMode.IDLE_DAYDREAM],
        )

    def should_escalate_to_interactive(
        self, stakes: float | None = None, user_addressed: bool = False
    ) -> bool:
        """Check if we should escalate to interactive mode.

        Args:
            stakes: Current stakes estimate (0.0-1.0)
            user_addressed: Whether user explicitly addressed the assistant

        Returns:
            True if should escalate
        """
        if user_addressed:
            return True

        if stakes is not None and stakes > self.STAKES_THRESHOLD:
            return True

        return False

    def should_enter_daydream(self) -> bool:
        """Check if we should enter daydream mode.

        Returns:
            True if should enter daydream mode
        """
        # Must be in ambient ingest mode
        if self._state.current_mode != OperatingMode.AMBIENT_INGEST:
            return False

        # Check time in mode
        if self._state.time_in_mode() < self.DAYDREAM_TIMEOUT:
            return False

        # Stakes should be low
        if self._state.accumulated_stakes > 0.3:
            return False

        return True

    def should_generate_nudge(self, hypothesis_confidence: float) -> bool:
        """Check if we should generate a proactive nudge.

        Args:
            hypothesis_confidence: Confidence of the hypothesis

        Returns:
            True if should generate nudge
        """
        return hypothesis_confidence >= self.NUDGE_CONFIDENCE_THRESHOLD

    async def transition_to(
        self, mode: OperatingMode, trigger: str = "manual"
    ) -> bool:
        """Transition to a new operating mode.

        Args:
            mode: Target mode
            trigger: What triggered the transition

        Returns:
            True if transition occurred, False if already in mode
        """
        if mode == self._state.current_mode:
            return False

        # Record transition
        transition = ModeTransition(
            from_mode=self._state.current_mode,
            to_mode=mode,
            trigger=trigger,
        )
        self._transition_history.append(transition)

        # Update state
        old_mode = self._state.current_mode
        self._state.current_mode = mode
        self._state.entered_at = datetime.now()

        # Reset stakes when entering ambient mode
        if mode == OperatingMode.AMBIENT_INGEST:
            self._state.accumulated_stakes = 0.0

        logger.info(
            f"Mode transition: {old_mode.value} -> {mode.value} (trigger: {trigger})"
        )

        # Emit event
        await event_bus.emit(
            Event(
                EventType.MODE_TRANSITION
                if hasattr(EventType, "MODE_TRANSITION")
                else EventType.PROCESSING_STARTED,
                {
                    "from_mode": old_mode.value,
                    "to_mode": mode.value,
                    "trigger": trigger,
                    "timestamp": datetime.now().isoformat(),
                },
            )
        )

        # Call callback
        if self._on_transition:
            self._on_transition(transition)

        return True

    def record_user_interaction(self) -> None:
        """Record a user interaction."""
        self._state.last_user_interaction = datetime.now()

    def update_stakes(self, stakes: float) -> None:
        """Update accumulated stakes.

        Args:
            stakes: New stakes estimate (0.0-1.0)
        """
        # Keep rolling max
        self._state.accumulated_stakes = max(
            self._state.accumulated_stakes * 0.9,  # Decay
            stakes,
        )

    def add_pending_nudge(self, nudge_id: str) -> None:
        """Add a pending nudge.

        Args:
            nudge_id: ID of the pending nudge
        """
        self._state.pending_nudges.append(nudge_id)

    def remove_pending_nudge(self, nudge_id: str) -> None:
        """Remove a pending nudge.

        Args:
            nudge_id: ID of the nudge to remove
        """
        if nudge_id in self._state.pending_nudges:
            self._state.pending_nudges.remove(nudge_id)

    def update_hypothesis_count(self, count: int) -> None:
        """Update active hypothesis count.

        Args:
            count: Number of active hypotheses
        """
        self._state.active_hypotheses = count

    def get_transition_history(
        self, limit: int = 10
    ) -> list[ModeTransition]:
        """Get recent transition history.

        Args:
            limit: Maximum transitions to return

        Returns:
            List of recent transitions
        """
        return self._transition_history[-limit:]

    def get_mode_stats(self) -> dict:
        """Get statistics about mode usage.

        Returns:
            Dictionary of mode statistics
        """
        mode_counts = {mode.value: 0 for mode in OperatingMode}
        for transition in self._transition_history:
            mode_counts[transition.to_mode.value] += 1

        return {
            "current_mode": self._state.current_mode.value,
            "time_in_mode_seconds": self._state.time_in_mode().total_seconds(),
            "total_transitions": len(self._transition_history),
            "transition_counts": mode_counts,
            "accumulated_stakes": self._state.accumulated_stakes,
            "pending_nudges": len(self._state.pending_nudges),
            "active_hypotheses": self._state.active_hypotheses,
        }

    async def auto_transition(
        self,
        stakes: float | None = None,
        user_addressed: bool = False,
        hypothesis_confidence: float | None = None,
    ) -> OperatingMode | None:
        """Automatically determine and execute appropriate transition.

        Args:
            stakes: Current stakes estimate
            user_addressed: Whether user explicitly addressed assistant
            hypothesis_confidence: Confidence of a pending hypothesis

        Returns:
            New mode if transition occurred, None otherwise
        """
        current = self._state.current_mode

        # Interactive takes priority
        if self.should_escalate_to_interactive(stakes, user_addressed):
            if current != OperatingMode.INTERACTIVE_ASSIST:
                trigger = "user_addressed" if user_addressed else "high_stakes"
                await self.transition_to(OperatingMode.INTERACTIVE_ASSIST, trigger)
                return OperatingMode.INTERACTIVE_ASSIST

        # Check for daydream entry
        if current == OperatingMode.AMBIENT_INGEST and self.should_enter_daydream():
            await self.transition_to(OperatingMode.IDLE_DAYDREAM, "idle_timeout")
            return OperatingMode.IDLE_DAYDREAM

        # Check for nudge generation
        if (
            current == OperatingMode.IDLE_DAYDREAM
            and hypothesis_confidence is not None
            and self.should_generate_nudge(hypothesis_confidence)
        ):
            await self.transition_to(OperatingMode.PROACTIVE_NUDGE, "high_confidence_hypothesis")
            return OperatingMode.PROACTIVE_NUDGE

        # Return to daydream after nudge
        if current == OperatingMode.PROACTIVE_NUDGE:
            if not self._state.pending_nudges:
                await self.transition_to(OperatingMode.IDLE_DAYDREAM, "nudge_complete")
                return OperatingMode.IDLE_DAYDREAM

        return None
