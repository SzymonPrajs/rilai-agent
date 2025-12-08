"""
Nudge Delivery

Handles rendering and delivery of proactive nudges.
Includes safe phrasing guidelines and macOS notification support.
"""

import asyncio
import logging
import platform
import subprocess
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Literal

from rilai.core.events import Event, EventType, event_bus
from rilai.proactive.budget import InterruptBudget
from rilai.proactive.ladder import InterventionLevel, InterventionScore
from rilai.proactive.store import ProactiveItem, ProactiveStore

logger = logging.getLogger(__name__)


# Safe phrasing templates for nudges
NUDGE_OPENERS = {
    "warm": [
        "Something's been on my mind...",
        "I wanted to gently bring up...",
        "This might be helpful to think about...",
    ],
    "direct": [
        "Quick thought:",
        "Worth noting:",
        "One thing to consider:",
    ],
    "playful": [
        "Random thought that popped up...",
        "Just a heads up...",
        "Not to be that guy, but...",
    ],
    "solemn": [
        "There's something I think deserves attention...",
        "I want to flag something carefully...",
        "This feels important to mention...",
    ],
}

# Phrases to NEVER use (surveillance vibes)
FORBIDDEN_PHRASES = [
    "I heard you say",
    "I noticed you mentioned",
    "Based on what you told me",
    "I've been tracking",
    "My analysis suggests",
    "I observed that you",
    "According to my records",
]


@dataclass
class NudgeDeliveryResult:
    """Result of nudge delivery attempt."""

    success: bool
    item_id: str
    level: InterventionLevel
    message: str
    delivery_method: Literal["inline", "banner", "notification"]
    timestamp: datetime
    error: str | None = None


class NudgeDelivery:
    """Handles rendering and delivery of proactive nudges.

    Responsibilities:
    - Render nudge messages with safe phrasing
    - Check budget before delivery
    - Deliver via appropriate channel (inline, banner, notification)
    - Track delivery status
    """

    def __init__(
        self,
        budget: InterruptBudget,
        store: ProactiveStore,
        on_nudge: Callable[[str, InterventionLevel], None] | None = None,
    ):
        """Initialize nudge delivery.

        Args:
            budget: Interrupt budget manager
            store: Proactive store
            on_nudge: Callback for nudge delivery (for TUI integration)
        """
        self.budget = budget
        self.store = store
        self._on_nudge = on_nudge

        # Settings
        self.notifications_enabled = True
        self.audio_enabled = True
        self.quiet_hours: tuple[int, int] = (22, 8)  # 10pm-8am

    def render_nudge(
        self,
        content: str,
        tone: Literal["warm", "direct", "playful", "solemn"] = "direct",
        level: InterventionLevel = InterventionLevel.NUDGE,
    ) -> str:
        """Render a nudge message with safe phrasing.

        Args:
            content: Core content of the nudge
            tone: Desired tone
            level: Intervention level (affects length)

        Returns:
            Rendered nudge message
        """
        # Check for forbidden phrases
        content_lower = content.lower()
        for phrase in FORBIDDEN_PHRASES:
            if phrase.lower() in content_lower:
                logger.warning(f"Nudge contains forbidden phrase: {phrase}")
                # Try to remove it
                content = content.replace(phrase, "").strip()

        # Get opener based on tone
        openers = NUDGE_OPENERS.get(tone, NUDGE_OPENERS["direct"])
        opener = openers[0]  # Use first opener for consistency

        # Level-specific formatting
        if level == InterventionLevel.NUDGE:
            # L3: Keep it to one sentence
            if not content.endswith((".", "!", "?")):
                content += "."
            return f"{opener} {content}"

        elif level == InterventionLevel.URGENT:
            # L4: Can be two sentences, more direct
            return content  # Skip opener for urgency

        else:
            # Lower levels: just the content
            return content

    async def deliver(
        self,
        item: ProactiveItem,
        force: bool = False,
    ) -> NudgeDeliveryResult:
        """Deliver a proactive nudge.

        Args:
            item: Proactive item to deliver
            force: Force delivery even if budget depleted

        Returns:
            NudgeDeliveryResult
        """
        level = item.level

        # Check quiet hours for L3/L4
        if level >= InterventionLevel.NUDGE and self._in_quiet_hours():
            logger.info("In quiet hours, downgrading nudge")
            level = InterventionLevel.ON_OPEN
            item.level = level
            self.store.add_item(item)
            return NudgeDeliveryResult(
                success=False,
                item_id=item.item_id,
                level=level,
                message=item.message,
                delivery_method="inline",
                timestamp=datetime.now(),
                error="quiet_hours",
            )

        # Check budget for L3/L4
        if level >= InterventionLevel.NUDGE and not force:
            if not self.budget.can_interrupt(level, item.intervention_score.calibrated_score):
                # Downgrade
                new_level = self.budget.downgrade_level(level)
                self.budget.record_suppressed()

                if new_level < InterventionLevel.NUDGE:
                    # Queue for later
                    item.level = new_level
                    self.store.add_item(item)
                    return NudgeDeliveryResult(
                        success=False,
                        item_id=item.item_id,
                        level=new_level,
                        message=item.message,
                        delivery_method="inline",
                        timestamp=datetime.now(),
                        error="budget_depleted",
                    )

                level = new_level

        # Determine delivery method
        if level == InterventionLevel.URGENT:
            delivery_method = "notification"
        elif level == InterventionLevel.NUDGE:
            delivery_method = "inline"
        else:
            delivery_method = "banner"

        # Deliver
        try:
            if delivery_method == "notification":
                await self._deliver_notification(item.message)
            elif delivery_method == "inline":
                await self._deliver_inline(item.message, level)
            else:
                await self._deliver_banner(item.message)

            # Spend budget
            if level >= InterventionLevel.NUDGE:
                self.budget.spend(level)

            # Mark delivered
            self.store.mark_delivered(item.item_id)

            # Emit event
            await event_bus.emit(
                Event(
                    EventType.NUDGE_DELIVERED
                    if hasattr(EventType, "NUDGE_DELIVERED")
                    else EventType.PROCESSING_COMPLETED,
                    {
                        "item_id": item.item_id,
                        "level": level.value,
                        "message": item.message,
                        "method": delivery_method,
                    },
                )
            )

            return NudgeDeliveryResult(
                success=True,
                item_id=item.item_id,
                level=level,
                message=item.message,
                delivery_method=delivery_method,
                timestamp=datetime.now(),
            )

        except Exception as e:
            logger.error(f"Failed to deliver nudge: {e}")
            return NudgeDeliveryResult(
                success=False,
                item_id=item.item_id,
                level=level,
                message=item.message,
                delivery_method=delivery_method,
                timestamp=datetime.now(),
                error=str(e),
            )

    async def _deliver_inline(self, message: str, level: InterventionLevel) -> None:
        """Deliver inline nudge to TUI."""
        if self._on_nudge:
            self._on_nudge(message, level)
        logger.info(f"Inline nudge: {message[:50]}...")

    async def _deliver_banner(self, message: str) -> None:
        """Deliver banner notification to TUI."""
        if self._on_nudge:
            self._on_nudge(message, InterventionLevel.ON_OPEN)
        logger.info(f"Banner nudge: {message[:50]}...")

    async def _deliver_notification(self, message: str, title: str = "Rilai") -> None:
        """Send macOS system notification.

        Args:
            message: Notification message
            title: Notification title
        """
        if not self.notifications_enabled:
            logger.debug("Notifications disabled")
            return

        if platform.system() != "Darwin":
            logger.debug("System notifications only supported on macOS")
            return

        # Use osascript for macOS notifications
        script = f'display notification "{message}" with title "{title}"'
        try:
            subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                timeout=5,
            )
            logger.info(f"System notification sent: {message[:50]}...")

            # Optional audio cue
            if self.audio_enabled:
                self._play_sound(InterventionLevel.URGENT)

        except subprocess.TimeoutExpired:
            logger.warning("Notification timed out")
        except Exception as e:
            logger.error(f"Failed to send notification: {e}")

    def _play_sound(self, level: InterventionLevel) -> None:
        """Play audio cue for nudge.

        Args:
            level: Intervention level
        """
        if platform.system() != "Darwin":
            return

        sounds = {
            InterventionLevel.NUDGE: "/System/Library/Sounds/Pop.aiff",
            InterventionLevel.URGENT: "/System/Library/Sounds/Sosumi.aiff",
        }

        sound_path = sounds.get(level)
        if sound_path:
            try:
                subprocess.run(
                    ["afplay", sound_path],
                    capture_output=True,
                    timeout=2,
                )
            except Exception:
                pass  # Audio is best-effort

    def _in_quiet_hours(self) -> bool:
        """Check if current time is in quiet hours."""
        hour = datetime.now().hour
        start, end = self.quiet_hours

        if start > end:  # Spans midnight
            return hour >= start or hour < end
        return start <= hour < end

    def set_on_nudge_callback(
        self, callback: Callable[[str, InterventionLevel], None]
    ) -> None:
        """Set callback for nudge delivery.

        Args:
            callback: Function(message, level) to call on delivery
        """
        self._on_nudge = callback

    async def process_pending_on_open(self) -> list[NudgeDeliveryResult]:
        """Process all pending L2 items when TUI opens.

        Returns:
            List of delivery results
        """
        items = self.store.get_on_open_items()
        results = []

        for item in items:
            result = await self.deliver(item)
            results.append(result)

        return results
