"""Proactive nudge condition checking."""

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from rilai.runtime.workspace import Workspace


@dataclass
class NudgeCondition:
    """A condition that can trigger a proactive nudge."""
    id: str
    reason: str
    priority: int  # Higher = more important
    cooldown: float  # Seconds before can trigger again


class NudgeChecker:
    """Checks conditions for proactive nudges.

    Nudge conditions:
    1. High stress + user silent for extended time
    2. Open goal with approaching deadline
    3. Unresolved rupture in relationship
    4. Scheduled check-in time
    5. Long session without break reminder
    """

    # Thresholds
    SILENCE_THRESHOLD_STRESS = 300  # 5 minutes
    SILENCE_THRESHOLD_NORMAL = 1800  # 30 minutes
    DEADLINE_WARNING_HOURS = 1
    SESSION_BREAK_REMINDER = 3600  # 1 hour

    def __init__(self, workspace: "Workspace"):
        self.workspace = workspace
        self._last_nudge_times: dict[str, float] = {}
        self._session_start = time.time()

    async def check_all(self) -> Optional[dict]:
        """Check all nudge conditions.

        Returns:
            Nudge dict if condition met, None otherwise
        """
        now = time.time()

        # Check each condition in priority order
        conditions = [
            self._check_high_stress_silence,
            self._check_deadline_approaching,
            self._check_rupture_unresolved,
            self._check_session_break,
            self._check_idle_checkin,
        ]

        for check_fn in conditions:
            result = await check_fn(now)
            if result and self._can_nudge(result["condition_id"], now):
                self._last_nudge_times[result["condition_id"]] = now
                return result

        return None

    def _can_nudge(self, condition_id: str, now: float) -> bool:
        """Check if enough time has passed since last nudge."""
        last_time = self._last_nudge_times.get(condition_id, 0)
        cooldowns = {
            "high_stress_silence": 600,  # 10 min
            "deadline_approaching": 1800,  # 30 min
            "rupture_unresolved": 900,  # 15 min
            "session_break": 3600,  # 1 hour
            "idle_checkin": 1800,  # 30 min
        }
        cooldown = cooldowns.get(condition_id, 300)
        return now - last_time >= cooldown

    async def _check_high_stress_silence(self, now: float) -> Optional[dict]:
        """Check for high stress with user silence."""
        # Check strain level
        if self.workspace.stance.strain < 0.6:
            return None

        # Check silence duration
        last_msg_time = self.workspace.last_user_message_time
        if not last_msg_time:
            return None

        silence_duration = now - last_msg_time
        if silence_duration < self.SILENCE_THRESHOLD_STRESS:
            return None

        return {
            "condition_id": "high_stress_silence",
            "reason": "high_stress_silence",
            "suggestion": "gentle_checkin",
            "priority": 3,
            "context": {
                "strain": self.workspace.stance.strain,
                "silence_minutes": int(silence_duration / 60),
            },
            "message_hint": "I noticed you might be going through something. No pressure to share, but I'm here if you want to talk.",
        }

    async def _check_deadline_approaching(self, now: float) -> Optional[dict]:
        """Check for goals with approaching deadlines."""
        for goal in self.workspace.open_threads:
            if not goal.deadline:
                continue

            # Check if deadline is within warning window
            deadline_ts = goal.deadline.timestamp() if isinstance(goal.deadline, datetime) else goal.deadline
            hours_until = (deadline_ts - now) / 3600

            if 0 < hours_until <= self.DEADLINE_WARNING_HOURS:
                return {
                    "condition_id": "deadline_approaching",
                    "reason": "deadline_approaching",
                    "suggestion": "deadline_reminder",
                    "priority": 2,
                    "context": {
                        "goal": goal.text,
                        "hours_until": round(hours_until, 1),
                        "progress": goal.progress,
                    },
                    "message_hint": f"Quick heads up - your goal '{goal.text[:50]}' has a deadline coming up soon.",
                }

        return None

    async def _check_rupture_unresolved(self, now: float) -> Optional[dict]:
        """Check for unresolved relationship rupture."""
        # Check for recent negative valence + high strain combination
        if self.workspace.stance.valence > -0.3:
            return None
        if self.workspace.stance.strain < 0.5:
            return None
        if self.workspace.stance.closeness > 0.4:
            return None

        # Check if last message was recent (rupture context still relevant)
        last_msg_time = self.workspace.last_user_message_time
        if not last_msg_time:
            return None

        time_since = now - last_msg_time
        if time_since > 1800:  # 30 min - rupture context expired
            return None

        return {
            "condition_id": "rupture_unresolved",
            "reason": "rupture_unresolved",
            "suggestion": "repair_attempt",
            "priority": 4,  # High priority
            "context": {
                "valence": self.workspace.stance.valence,
                "strain": self.workspace.stance.strain,
                "closeness": self.workspace.stance.closeness,
            },
            "message_hint": "I sense things might have gotten tense. I want to understand better - can we talk about what happened?",
        }

    async def _check_session_break(self, now: float) -> Optional[dict]:
        """Check if user should take a break."""
        session_duration = now - self._session_start

        if session_duration < self.SESSION_BREAK_REMINDER:
            return None

        # Only suggest break if signs of fatigue
        if self.workspace.modulators.fatigue < 0.4:
            return None

        return {
            "condition_id": "session_break",
            "reason": "session_break",
            "suggestion": "break_reminder",
            "priority": 1,  # Low priority
            "context": {
                "session_minutes": int(session_duration / 60),
                "fatigue": self.workspace.modulators.fatigue,
            },
            "message_hint": "We've been chatting for a while. Maybe a good time for a short break?",
        }

    async def _check_idle_checkin(self, now: float) -> Optional[dict]:
        """Check for general idle check-in."""
        last_msg_time = self.workspace.last_user_message_time
        if not last_msg_time:
            return None

        silence_duration = now - last_msg_time
        if silence_duration < self.SILENCE_THRESHOLD_NORMAL:
            return None

        # Only check in if there's something to check in about
        if not self.workspace.open_threads and self.workspace.stance.strain < 0.3:
            return None

        return {
            "condition_id": "idle_checkin",
            "reason": "idle_checkin",
            "suggestion": "casual_checkin",
            "priority": 0,  # Lowest priority
            "context": {
                "silence_minutes": int(silence_duration / 60),
                "open_threads": len(self.workspace.open_threads),
            },
            "message_hint": "Hey, just checking in. How are things going?",
        }

    def reset_session(self) -> None:
        """Reset session start time (for new session)."""
        self._session_start = time.time()
        self._last_nudge_times.clear()
