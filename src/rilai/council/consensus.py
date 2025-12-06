"""Consensus detection for multi-round deliberation.

Provides algorithms for detecting consensus among agent voices
and determining when to exit deliberation early.
"""

from dataclasses import dataclass
from typing import Literal

from rilai.config import get_config


@dataclass
class ConsensusResult:
    """Result of consensus analysis."""

    level: float  # 0.0 to 1.0
    speaking_pressure: float  # 0.0 to 1.0
    dominant_stance: Literal["maintain", "adjust", "defer", "dissent"]
    has_critical_urgency: bool
    all_deferred: bool
    should_exit_early: bool
    exit_reason: str | None


@dataclass
class AgentVoiceView:
    """Simplified view of an agent voice for consensus analysis."""

    agent_id: str
    stance: Literal["maintain", "adjust", "defer", "dissent"]
    urgency: int
    confidence: int


class ConsensusDetector:
    """Detects consensus among deliberating agents.

    Consensus is measured on multiple dimensions:
    - Stance alignment (maintain/adjust vs dissent)
    - Urgency convergence
    - Deference patterns
    """

    def __init__(
        self,
        consensus_threshold: float | None = None,
        speaking_pressure_threshold: float | None = None,
    ):
        config = get_config()
        self.consensus_threshold = (
            consensus_threshold or config.DELIBERATION_CONSENSUS_THRESHOLD
        )
        self.speaking_pressure_threshold = speaking_pressure_threshold or 0.5

    def analyze(self, voices: dict[str, "AgentVoiceView"]) -> ConsensusResult:
        """Analyze consensus among voices.

        Args:
            voices: Map of agent_id to their voice view

        Returns:
            ConsensusResult with analysis
        """
        if not voices:
            return ConsensusResult(
                level=0.0,
                speaking_pressure=0.0,
                dominant_stance="maintain",
                has_critical_urgency=False,
                all_deferred=False,
                should_exit_early=False,
                exit_reason=None,
            )

        # Count stances
        stance_counts = {"maintain": 0, "adjust": 0, "defer": 0, "dissent": 0}
        for voice in voices.values():
            stance_counts[voice.stance] = stance_counts.get(voice.stance, 0) + 1

        # Calculate consensus level
        consensus = self._compute_consensus_level(voices, stance_counts)

        # Calculate speaking pressure
        pressure = self._compute_speaking_pressure(voices)

        # Determine dominant stance
        dominant = max(stance_counts, key=stance_counts.get)

        # Check for critical urgency
        has_critical = any(v.urgency >= 3 for v in voices.values())

        # Check if all deferred
        all_deferred = all(v.stance == "defer" for v in voices.values())

        # Determine early exit
        should_exit, exit_reason = self._should_exit_early(
            consensus, pressure, has_critical, all_deferred
        )

        return ConsensusResult(
            level=consensus,
            speaking_pressure=pressure,
            dominant_stance=dominant,
            has_critical_urgency=has_critical,
            all_deferred=all_deferred,
            should_exit_early=should_exit,
            exit_reason=exit_reason,
        )

    def _compute_consensus_level(
        self,
        voices: dict[str, "AgentVoiceView"],
        stance_counts: dict[str, int],
    ) -> float:
        """Compute consensus level from stances.

        Returns: 0.0 to 1.0, where 1.0 is perfect consensus
        """
        total = len(voices)
        if total == 0:
            return 0.0

        dissent_count = stance_counts.get("dissent", 0)
        defer_count = stance_counts.get("defer", 0)

        # High dissent = low consensus
        if dissent_count > 0:
            return max(0.0, 1.0 - (dissent_count / total))

        # High defer = high consensus (agents stepping back)
        if defer_count >= total * 0.5:
            return 0.9

        # Mostly maintain/adjust = moderate consensus
        return 0.5 + (defer_count / total) * 0.3

    def _compute_speaking_pressure(
        self, voices: dict[str, "AgentVoiceView"]
    ) -> float:
        """Compute speaking pressure from urgency signals.

        Returns: 0.0 to 1.0
        """
        if not voices:
            return 0.0

        max_urgency = 0
        total_urgency = 0
        for voice in voices.values():
            max_urgency = max(max_urgency, voice.urgency)
            total_urgency += voice.urgency

        # Combine max and average (max weighted higher)
        avg_urgency = total_urgency / len(voices)
        return (max_urgency / 3.0 * 0.7) + (avg_urgency / 3.0 * 0.3)

    def _should_exit_early(
        self,
        consensus: float,
        pressure: float,
        has_critical: bool,
        all_deferred: bool,
    ) -> tuple[bool, str | None]:
        """Determine if deliberation should exit early.

        Returns:
            Tuple of (should_exit, reason)
        """
        # Critical urgency = speak immediately
        if has_critical:
            return True, "critical_urgency"

        # All deferred = stay silent
        if all_deferred:
            return True, "all_deferred"

        # High consensus + sufficient pressure = speak
        if consensus >= self.consensus_threshold:
            if pressure >= self.speaking_pressure_threshold:
                return True, "consensus_reached"

        return False, None


def voices_to_view(
    voices: dict[str, any]
) -> dict[str, AgentVoiceView]:
    """Convert AgentVoice objects to AgentVoiceView for consensus analysis.

    Args:
        voices: Dict of agent_id to AgentVoice (from deliberation)

    Returns:
        Dict of agent_id to AgentVoiceView
    """
    result = {}
    for agent_id, voice in voices.items():
        # Handle both dataclass and dict formats
        if hasattr(voice, "stance"):
            stance = voice.stance
            salience = voice.salience
            urgency = salience.urgency if salience else 0
            confidence = salience.confidence if salience else 0
        else:
            stance = voice.get("stance", "maintain")
            urgency = voice.get("urgency", 0)
            confidence = voice.get("confidence", 0)

        result[agent_id] = AgentVoiceView(
            agent_id=agent_id,
            stance=stance,
            urgency=urgency,
            confidence=confidence,
        )
    return result
