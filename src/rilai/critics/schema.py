"""
Critic Output Schema

All critics use this unified schema for their outputs.
Critics are "boxed" - they see the candidate and workspace, and output pass/fail.
"""

from dataclasses import dataclass, field
import json


@dataclass
class CriticOutput:
    """
    Unified output schema for all critics.

    Each critic outputs:
        - critic: Name of the critic
        - passed: Whether the candidate passes this check
        - reason: Explanation if failed (max 20 words)
        - severity: How bad the violation is [0, 1]
        - quote: The problematic text if failed
    """
    critic: str
    passed: bool
    reason: str = ""
    severity: float = 0.0
    quote: str = ""

    def to_dict(self) -> dict:
        return {
            "critic": self.critic,
            "passed": self.passed,
            "reason": self.reason,
            "severity": self.severity,
            "quote": self.quote,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: dict) -> "CriticOutput":
        return cls(
            critic=data.get("critic", "unknown"),
            passed=data.get("passed", True),
            reason=data.get("reason", ""),
            severity=data.get("severity", 0.0),
            quote=data.get("quote", ""),
        )

    @classmethod
    def from_json(cls, json_str: str, critic_name: str = "unknown") -> "CriticOutput":
        """Parse critic output from JSON string."""
        try:
            data = json.loads(json_str)
            data["critic"] = data.get("critic", critic_name)
            return cls.from_dict(data)
        except json.JSONDecodeError:
            return cls(critic=critic_name, passed=True, reason="Parse error")


@dataclass
class CriticEnsembleResult:
    """
    Aggregated result from running all critics.
    """
    critic_outputs: list[CriticOutput] = field(default_factory=list)
    all_passed: bool = True
    total_severity: float = 0.0
    blocking_critics: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "critic_outputs": [c.to_dict() for c in self.critic_outputs],
            "all_passed": self.all_passed,
            "total_severity": self.total_severity,
            "blocking_critics": self.blocking_critics,
        }


# List of all critic names
CRITIC_NAMES = [
    "advice_reflex",      # Fail if premature advice when vulnerability high
    "truthfulness",       # Fail if claims human feelings/body/consciousness
    "evidence_honesty",   # Fail if references past not supported by evidence
    "calibration",        # Fail if over-intimate or dependency-encouraging
    "cliche",             # Fail if generic therapist wording
    "coherence",          # Fail if internal contradictions
]


def aggregate_critic_outputs(outputs: list[CriticOutput]) -> CriticEnsembleResult:
    """Aggregate critic outputs into ensemble result."""
    all_passed = all(o.passed for o in outputs)
    total_severity = sum(o.severity for o in outputs if not o.passed)
    blocking = [o.critic for o in outputs if not o.passed and o.severity >= 0.5]

    return CriticEnsembleResult(
        critic_outputs=outputs,
        all_passed=all_passed,
        total_severity=total_severity,
        blocking_critics=blocking,
    )
