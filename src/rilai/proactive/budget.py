"""
Interrupt Budget

Manages interrupt budget to prevent notification fatigue.
Limits interruptions per hour and per day.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from rilai.proactive.ladder import InterventionLevel

logger = logging.getLogger(__name__)


@dataclass
class InterruptBudget:
    """Manages interrupt budget to prevent notification fatigue.

    Features:
    - Hourly and daily budget limits
    - Per-level costs (urgent costs more)
    - Emergency override for truly critical items
    - Budget replenishment over time
    """

    # Budget pools
    hourly_budget: float = 3.0  # Max interrupts per hour
    daily_budget: float = 12.0  # Max interrupts per day

    # Current state
    hourly_spent: float = 0.0
    daily_spent: float = 0.0

    # Timestamps for reset
    hour_start: datetime = field(default_factory=datetime.now)
    day_start: datetime = field(default_factory=datetime.now)

    # Cost per level (L3 and L4 only use budget)
    LEVEL_COSTS = {
        InterventionLevel.NUDGE: 1.0,
        InterventionLevel.URGENT: 2.0,
    }

    # Emergency threshold (can exceed budget)
    emergency_threshold: float = 0.95

    # Statistics
    total_interrupts: int = 0
    total_suppressed: int = 0

    def can_interrupt(self, level: InterventionLevel, score: float = 0.0) -> bool:
        """Check if we have budget for this interrupt.

        Args:
            level: Intervention level
            score: Calibrated intervention score (for emergency override)

        Returns:
            True if interrupt is allowed
        """
        # Only L3/L4 use budget
        if level < InterventionLevel.NUDGE:
            return True

        self._maybe_reset()

        # Emergency override for truly critical
        if score >= self.emergency_threshold:
            logger.info(f"Emergency override: score {score:.2f} >= threshold")
            return True

        cost = self.LEVEL_COSTS.get(level, 1.0)

        # Check both budgets
        hourly_ok = (self.hourly_spent + cost) <= self.hourly_budget
        daily_ok = (self.daily_spent + cost) <= self.daily_budget

        if not hourly_ok:
            logger.debug(
                f"Hourly budget depleted: {self.hourly_spent:.1f}/{self.hourly_budget:.1f}"
            )
        if not daily_ok:
            logger.debug(
                f"Daily budget depleted: {self.daily_spent:.1f}/{self.daily_budget:.1f}"
            )

        return hourly_ok and daily_ok

    def spend(self, level: InterventionLevel) -> None:
        """Deduct from budget after successful interrupt.

        Args:
            level: Intervention level that was used
        """
        if level < InterventionLevel.NUDGE:
            return

        cost = self.LEVEL_COSTS.get(level, 1.0)
        self.hourly_spent += cost
        self.daily_spent += cost
        self.total_interrupts += 1

        logger.debug(
            f"Budget spent: {cost:.1f} (hourly: {self.hourly_spent:.1f}/{self.hourly_budget:.1f}, "
            f"daily: {self.daily_spent:.1f}/{self.daily_budget:.1f})"
        )

    def record_suppressed(self) -> None:
        """Record a suppressed interrupt."""
        self.total_suppressed += 1

    def _maybe_reset(self) -> None:
        """Reset budgets if time windows have passed."""
        now = datetime.now()

        # Hourly reset
        if (now - self.hour_start).total_seconds() >= 3600:
            self.hourly_spent = 0.0
            self.hour_start = now
            logger.debug("Hourly budget reset")

        # Daily reset (at midnight or 24h)
        if now.date() != self.day_start.date():
            self.daily_spent = 0.0
            self.day_start = now
            logger.debug("Daily budget reset")

    def get_remaining(self) -> dict:
        """Get remaining budget for UI display.

        Returns:
            Dictionary with remaining hourly and daily budget
        """
        self._maybe_reset()
        return {
            "hourly": max(0, self.hourly_budget - self.hourly_spent),
            "daily": max(0, self.daily_budget - self.daily_spent),
            "hourly_pct": max(
                0, (self.hourly_budget - self.hourly_spent) / self.hourly_budget * 100
            ),
            "daily_pct": max(
                0, (self.daily_budget - self.daily_spent) / self.daily_budget * 100
            ),
        }

    def replenish_partial(self, amount: float = 0.5) -> None:
        """Partial replenishment (e.g., after user engages positively).

        Args:
            amount: Amount to replenish
        """
        self.hourly_spent = max(0, self.hourly_spent - amount)
        logger.debug(f"Budget replenished by {amount:.1f}")

    def get_stats(self) -> dict:
        """Get budget statistics.

        Returns:
            Dictionary of statistics
        """
        remaining = self.get_remaining()
        return {
            "hourly_spent": self.hourly_spent,
            "daily_spent": self.daily_spent,
            "hourly_remaining": remaining["hourly"],
            "daily_remaining": remaining["daily"],
            "total_interrupts": self.total_interrupts,
            "total_suppressed": self.total_suppressed,
            "suppression_rate": (
                self.total_suppressed / (self.total_interrupts + self.total_suppressed)
                if (self.total_interrupts + self.total_suppressed) > 0
                else 0.0
            ),
        }

    def downgrade_level(self, level: InterventionLevel) -> InterventionLevel:
        """Downgrade level if budget is depleted.

        Args:
            level: Original intervention level

        Returns:
            Same level if budget available, or lower level
        """
        if level < InterventionLevel.NUDGE:
            return level

        if self.can_interrupt(level):
            return level

        # Try to downgrade
        if level == InterventionLevel.URGENT:
            if self.can_interrupt(InterventionLevel.NUDGE):
                logger.info("Downgrading URGENT to NUDGE (budget)")
                return InterventionLevel.NUDGE

        # Further downgrade to ON_OPEN (no budget needed)
        logger.info(f"Downgrading {level.name} to ON_OPEN (budget depleted)")
        return InterventionLevel.ON_OPEN
