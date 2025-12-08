"""Critics - post-generation validation."""

from dataclasses import dataclass
from typing import Callable, List, TYPE_CHECKING
from enum import Enum

from rilai.contracts.events import EngineEvent, EventKind

if TYPE_CHECKING:
    from rilai.runtime.workspace import Workspace
    from rilai.contracts.council import CouncilDecision


class CriticSeverity(str, Enum):
    """Severity levels for critic findings."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    BLOCK = "block"


@dataclass
class CriticFinding:
    """Result from a single critic."""
    critic_id: str
    passed: bool
    severity: CriticSeverity
    message: str | None = None
    suggestion: str | None = None


class Critics:
    """Post-generation validation critics.

    Critics run after voice rendering to validate the response.
    They can:
    - Pass (response is fine)
    - Warn (log but allow)
    - Block (require regeneration)
    """

    def __init__(self, emit_fn: Callable[[EventKind, dict], EngineEvent]):
        self.emit_fn = emit_fn
        self._critics = [
            self._safety_policy_critic,
            self._coherence_critic,
            self._over_advice_critic,
            self._tone_mismatch_critic,
            self._length_critic,
        ]

    async def validate(
        self,
        response_text: str,
        workspace: "Workspace",
        decision: "CouncilDecision",
    ) -> tuple[bool, List[CriticFinding]]:
        """Run all critics on response.

        Args:
            response_text: Generated response
            workspace: Current workspace state
            decision: Council decision that guided generation

        Returns:
            Tuple of (all_passed, list of results)
        """
        results = []

        for critic_fn in self._critics:
            result = await critic_fn(response_text, workspace, decision)
            results.append(result)

        # Check for blocking results
        all_passed = all(r.passed or r.severity != CriticSeverity.BLOCK for r in results)

        # Emit event
        self.emit_fn(
            EventKind.CRITICS_UPDATED,
            {
                "passed": all_passed,
                "results": [
                    {
                        "critic_id": r.critic_id,
                        "passed": r.passed,
                        "severity": r.severity.value,
                        "message": r.message,
                    }
                    for r in results
                ],
            },
        )

        return all_passed, results

    async def _safety_policy_critic(
        self,
        text: str,
        workspace: "Workspace",
        decision: "CouncilDecision",
    ) -> CriticFinding:
        """Check for safety policy violations.

        Always-on critic that blocks unsafe content.
        """
        # Simple keyword-based check (would use LLM in production)
        unsafe_patterns = [
            "kill yourself",
            "harm yourself",
            "end your life",
            "suicide method",
        ]

        text_lower = text.lower()
        for pattern in unsafe_patterns:
            if pattern in text_lower:
                return CriticFinding(
                    critic_id="safety_policy",
                    passed=False,
                    severity=CriticSeverity.BLOCK,
                    message=f"Unsafe pattern detected: {pattern}",
                    suggestion="Regenerate with safety-focused guidance",
                )

        return CriticFinding(
            critic_id="safety_policy",
            passed=True,
            severity=CriticSeverity.INFO,
        )

    async def _coherence_critic(
        self,
        text: str,
        workspace: "Workspace",
        decision: "CouncilDecision",
    ) -> CriticFinding:
        """Check response coherence with conversation."""
        # Check if response acknowledges user's topic
        user_words = set(workspace.user_message.lower().split())
        response_words = set(text.lower().split())

        # Very basic coherence check
        common_words = user_words & response_words
        # Filter out common stop words
        stop_words = {"i", "you", "the", "a", "an", "is", "are", "was", "were", "to", "of"}
        meaningful_common = common_words - stop_words

        if len(user_words) > 5 and len(meaningful_common) == 0:
            return CriticFinding(
                critic_id="coherence",
                passed=False,
                severity=CriticSeverity.WARNING,
                message="Response may not address user's message",
                suggestion="Ensure response relates to user's topic",
            )

        return CriticFinding(
            critic_id="coherence",
            passed=True,
            severity=CriticSeverity.INFO,
        )

    async def _over_advice_critic(
        self,
        text: str,
        workspace: "Workspace",
        decision: "CouncilDecision",
    ) -> CriticFinding:
        """Detect unsolicited advice."""
        # Check if we're supposed to be witnessing but giving advice
        if decision.speech_act and decision.speech_act.intent == "witness":
            advice_markers = [
                "you should",
                "you need to",
                "you must",
                "try to",
                "make sure",
                "don't forget to",
                "remember to",
            ]

            text_lower = text.lower()
            for marker in advice_markers:
                if marker in text_lower:
                    return CriticFinding(
                        critic_id="over_advice",
                        passed=False,
                        severity=CriticSeverity.WARNING,
                        message=f"Unsolicited advice detected: '{marker}'",
                        suggestion="Witness intent should acknowledge, not advise",
                    )

        return CriticFinding(
            critic_id="over_advice",
            passed=True,
            severity=CriticSeverity.INFO,
        )

    async def _tone_mismatch_critic(
        self,
        text: str,
        workspace: "Workspace",
        decision: "CouncilDecision",
    ) -> CriticFinding:
        """Check for tone mismatches."""
        stance = workspace.stance

        # If user is stressed, response shouldn't be overly enthusiastic
        if stance.strain > 0.5:
            enthusiasm_markers = ["!", "amazing", "awesome", "fantastic", "great news"]
            text_lower = text.lower()

            excessive_enthusiasm = sum(1 for m in enthusiasm_markers if m in text_lower)
            if excessive_enthusiasm >= 2:
                return CriticFinding(
                    critic_id="tone_mismatch",
                    passed=False,
                    severity=CriticSeverity.WARNING,
                    message="Overly enthusiastic tone for stressed user",
                    suggestion="Soften tone to match user's emotional state",
                )

        return CriticFinding(
            critic_id="tone_mismatch",
            passed=True,
            severity=CriticSeverity.INFO,
        )

    async def _length_critic(
        self,
        text: str,
        workspace: "Workspace",
        decision: "CouncilDecision",
    ) -> CriticFinding:
        """Check response length."""
        word_count = len(text.split())

        # Very short responses might be insufficient
        if word_count < 3:
            return CriticFinding(
                critic_id="length",
                passed=False,
                severity=CriticSeverity.WARNING,
                message="Response too short",
                suggestion="Elaborate slightly",
            )

        # Very long responses might be overwhelming
        if word_count > 100:
            return CriticFinding(
                critic_id="length",
                passed=False,
                severity=CriticSeverity.WARNING,
                message="Response too long",
                suggestion="Be more concise",
            )

        return CriticFinding(
            critic_id="length",
            passed=True,
            severity=CriticSeverity.INFO,
        )
