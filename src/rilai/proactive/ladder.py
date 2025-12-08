"""
Proactive Ladder

Defines intervention levels L0-L4 and computes intervention scores.

Level 0 (L0): Silent logging - no user visibility
Level 1 (L1): Queued for daily digest
Level 2 (L2): Gentle ping when TUI opens
Level 3 (L3): Real-time nudge (one sentence)
Level 4 (L4): Urgent interruption (system notification)
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Literal

logger = logging.getLogger(__name__)


class InterventionLevel(IntEnum):
    """Intervention levels from silent to urgent."""

    SILENT = 0  # Silent logging only
    DIGEST = 1  # Daily/weekly digest
    ON_OPEN = 2  # Show when TUI opens
    NUDGE = 3  # Real-time nudge
    URGENT = 4  # Urgent interruption


@dataclass
class InterventionScore:
    """Computed score determining proactive intervention level.

    The intervention score combines:
    - Stakes: Consequence magnitude if wrong/missed (0.0-1.0)
    - Confidence: How sure we are about the observation (0.0-1.0)
    - Reversibility gain: Benefit of early vs late intervention (0.0-1.0)
    - Domain: Category for domain-specific calibration
    """

    stakes: float  # 0.0-1.0: consequence magnitude
    confidence: float  # 0.0-1.0: how sure we are
    reversibility_gain: float  # 0.0-1.0: benefit of early intervention
    domain: str  # health, financial, social, scheduling, work, general

    # Optional metadata
    source_agents: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)

    # Domain-specific multipliers (health issues get priority)
    DOMAIN_MULTIPLIERS = {
        "health": 1.3,
        "financial": 1.2,
        "social": 1.0,
        "scheduling": 0.9,
        "work": 1.1,
        "general": 0.8,
    }

    @property
    def raw_score(self) -> float:
        """Raw intervention score before domain calibration.

        Formula: stakes * 0.5 + confidence * 0.3 + reversibility * 0.2
        """
        return (
            self.stakes * 0.5 + self.confidence * 0.3 + self.reversibility_gain * 0.2
        )

    @property
    def calibrated_score(self) -> float:
        """Score after domain-specific calibration."""
        multiplier = self.DOMAIN_MULTIPLIERS.get(self.domain, 0.8)
        return min(1.0, self.raw_score * multiplier)

    def get_level(self) -> InterventionLevel:
        """Determine intervention level (0-4).

        L0: score < 0.2 OR confidence < 0.3
        L1: 0.2 <= score < 0.4
        L2: 0.4 <= score < 0.6
        L3: 0.6 <= score < 0.8
        L4: score >= 0.8 AND confidence >= 0.7
        """
        score = self.calibrated_score

        if score < 0.2 or self.confidence < 0.3:
            return InterventionLevel.SILENT

        if score < 0.4:
            return InterventionLevel.DIGEST

        if score < 0.6:
            return InterventionLevel.ON_OPEN

        if score < 0.8:
            return InterventionLevel.NUDGE

        # L4 requires high confidence
        if self.confidence >= 0.7:
            return InterventionLevel.URGENT

        return InterventionLevel.NUDGE

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "stakes": self.stakes,
            "confidence": self.confidence,
            "reversibility_gain": self.reversibility_gain,
            "domain": self.domain,
            "raw_score": self.raw_score,
            "calibrated_score": self.calibrated_score,
            "level": self.get_level().value,
            "source_agents": self.source_agents,
            "evidence_ids": self.evidence_ids,
            "timestamp": self.timestamp.isoformat(),
        }


class StakesEstimator:
    """Estimates stakes for proactive observations."""

    # Domain-specific base stakes
    DOMAIN_BASE_STAKES = {
        "health": 0.6,
        "financial": 0.5,
        "social": 0.4,
        "work": 0.4,
        "scheduling": 0.3,
        "general": 0.2,
    }

    # Urgency from agents maps to stakes boost
    URGENCY_STAKES_MAP = {
        0: 0.0,
        1: 0.1,
        2: 0.25,
        3: 0.5,
    }

    def estimate(
        self,
        domain: str,
        max_urgency: int = 0,
        context_signals: dict | None = None,
    ) -> float:
        """Estimate stakes from domain and signals.

        Args:
            domain: Domain category
            max_urgency: Maximum urgency from agents (0-3)
            context_signals: Additional context signals

        Returns:
            Stakes estimate (0.0 to 1.0)
        """
        context_signals = context_signals or {}

        base = self.DOMAIN_BASE_STAKES.get(domain, 0.2)
        urgency_boost = self.URGENCY_STAKES_MAP.get(max_urgency, 0)

        # Context signals can modify stakes
        multiplier = 1.0

        if context_signals.get("involves_other_people"):
            multiplier *= 1.2
        if context_signals.get("has_deadline"):
            multiplier *= 1.15
        if context_signals.get("financial_amount_high"):
            multiplier *= 1.3
        if context_signals.get("user_emotional"):
            multiplier *= 1.1
        if context_signals.get("action_about_to_happen"):
            multiplier *= 1.25

        return min(1.0, (base + urgency_boost) * multiplier)


class ReversibilityEstimator:
    """Estimates how much benefit early intervention provides."""

    def estimate(
        self,
        domain: str,
        time_sensitivity: float = 0.3,
        context_signals: dict | None = None,
    ) -> float:
        """Estimate reversibility gain.

        Args:
            domain: Domain category
            time_sensitivity: How time-sensitive (0.0-1.0)
            context_signals: Additional context signals

        Returns:
            Reversibility gain (0.0 to 1.0)
        """
        context_signals = context_signals or {}

        base = 0.3

        # Time-sensitive items benefit more from early intervention
        base += time_sensitivity * 0.4

        # Domain adjustments
        domain_factors = {
            "health": 0.15,  # Health issues compound
            "social": 0.1,  # Relationships can repair
            "financial": 0.2,  # Financial mistakes can be costly
            "scheduling": 0.0,  # Usually recoverable
        }
        base += domain_factors.get(domain, 0)

        # Context adjustments
        if context_signals.get("deadline_imminent"):
            base += 0.2
        if context_signals.get("action_about_to_happen"):
            base += 0.25  # "Before you send that email..."

        return min(1.0, base)


class DomainClassifier:
    """Classifies observations into domains for calibration."""

    DOMAIN_KEYWORDS = {
        "health": [
            "sleep",
            "tired",
            "exhausted",
            "sick",
            "pain",
            "headache",
            "exercise",
            "eat",
            "meal",
            "medication",
            "doctor",
            "stress",
            "anxiety",
            "overwhelmed",
            "burned out",
            "therapy",
        ],
        "financial": [
            "money",
            "budget",
            "expense",
            "cost",
            "pay",
            "salary",
            "investment",
            "savings",
            "debt",
            "loan",
            "purchase",
            "afford",
        ],
        "social": [
            "friend",
            "family",
            "relationship",
            "partner",
            "meeting",
            "conversation",
            "they said",
            "feel judged",
            "conflict",
            "argument",
        ],
        "scheduling": [
            "deadline",
            "meeting",
            "calendar",
            "tomorrow",
            "appointment",
            "schedule",
            "time",
            "date",
            "event",
            "reminder",
        ],
        "work": [
            "project",
            "task",
            "work",
            "job",
            "client",
            "boss",
            "presentation",
            "report",
            "email",
            "colleague",
        ],
    }

    def classify(self, content: str, agent_signals: dict | None = None) -> str:
        """Classify content into a domain.

        Args:
            content: Text content to classify
            agent_signals: Signals from agents

        Returns:
            Domain string
        """
        agent_signals = agent_signals or {}
        content_lower = content.lower()

        # Count keyword matches per domain
        scores = {}
        for domain, keywords in self.DOMAIN_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in content_lower)
            scores[domain] = score

        # Agent signals can override
        if agent_signals.get("stress_high"):
            scores["health"] = scores.get("health", 0) + 2
        if agent_signals.get("social_context"):
            scores["social"] = scores.get("social", 0) + 2

        if not scores or max(scores.values()) == 0:
            return "general"

        return max(scores.items(), key=lambda x: x[1])[0]


class ProactiveLadder:
    """Proactive ladder with five intervention levels.

    Computes intervention scores and determines appropriate level.
    """

    def __init__(self):
        self.stakes_estimator = StakesEstimator()
        self.reversibility_estimator = ReversibilityEstimator()
        self.domain_classifier = DomainClassifier()

    def compute_score(
        self,
        content: str,
        confidence: float,
        max_urgency: int = 0,
        context_signals: dict | None = None,
        agent_signals: dict | None = None,
        source_agents: list[str] | None = None,
        evidence_ids: list[str] | None = None,
    ) -> InterventionScore:
        """Compute full intervention score.

        Args:
            content: Text content to analyze
            confidence: Confidence in the observation (0.0-1.0)
            max_urgency: Maximum agent urgency (0-3)
            context_signals: Context-derived signals
            agent_signals: Agent-derived signals
            source_agents: Agents that contributed to this observation
            evidence_ids: Evidence IDs supporting this observation

        Returns:
            InterventionScore with computed values
        """
        context_signals = context_signals or {}
        agent_signals = agent_signals or {}

        # Classify domain
        domain = self.domain_classifier.classify(content, agent_signals)

        # Estimate stakes
        stakes = self.stakes_estimator.estimate(
            domain=domain,
            max_urgency=max_urgency,
            context_signals=context_signals,
        )

        # Estimate reversibility gain
        time_sensitivity = context_signals.get("time_sensitivity", 0.3)
        reversibility = self.reversibility_estimator.estimate(
            domain=domain,
            time_sensitivity=time_sensitivity,
            context_signals=context_signals,
        )

        return InterventionScore(
            stakes=stakes,
            confidence=confidence,
            reversibility_gain=reversibility,
            domain=domain,
            source_agents=source_agents or [],
            evidence_ids=evidence_ids or [],
        )

    def should_intervene(
        self, score: InterventionScore, min_level: InterventionLevel = InterventionLevel.NUDGE
    ) -> bool:
        """Check if we should intervene at or above a minimum level.

        Args:
            score: Intervention score
            min_level: Minimum level to intervene

        Returns:
            True if should intervene
        """
        return score.get_level() >= min_level
