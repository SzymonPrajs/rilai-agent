"""AnalyticsProjection - token usage and latency tracking."""

from dataclasses import dataclass, field
from typing import Any

from rilai.contracts.events import EngineEvent, EventKind
from rilai.store.projections.base import Projection


@dataclass
class ModelCallStats:
    """Stats for a single model call."""

    model: str
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int
    latency_ms: int


@dataclass
class AnalyticsProjection(Projection):
    """Tracks token usage and latency metrics.

    Useful for cost tracking and performance optimization.
    """

    # Per-session totals
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_reasoning_tokens: int = 0
    total_latency_ms: int = 0

    # Per-turn stats
    turn_stats: dict[int, dict[str, Any]] = field(default_factory=dict)

    # Model breakdown
    model_usage: dict[str, dict[str, int]] = field(default_factory=dict)

    # Call history
    recent_calls: list[ModelCallStats] = field(default_factory=list)

    def reset(self) -> None:
        """Reset to initial state."""
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_reasoning_tokens = 0
        self.total_latency_ms = 0
        self.turn_stats.clear()
        self.model_usage.clear()
        self.recent_calls.clear()

    def apply(self, event: EngineEvent) -> None:
        """Apply event to update analytics."""
        match event.kind:
            case EventKind.MODEL_CALL_COMPLETED:
                model = event.payload.get("model", "unknown")
                prompt = event.payload.get("prompt_tokens", 0)
                completion = event.payload.get("completion_tokens", 0)
                reasoning = event.payload.get("reasoning_tokens", 0) or 0
                latency = event.payload.get("latency_ms", 0)

                # Update totals
                self.total_prompt_tokens += prompt
                self.total_completion_tokens += completion
                self.total_reasoning_tokens += reasoning
                self.total_latency_ms += latency

                # Update model breakdown
                if model not in self.model_usage:
                    self.model_usage[model] = {
                        "calls": 0,
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "reasoning_tokens": 0,
                        "latency_ms": 0,
                    }
                self.model_usage[model]["calls"] += 1
                self.model_usage[model]["prompt_tokens"] += prompt
                self.model_usage[model]["completion_tokens"] += completion
                self.model_usage[model]["reasoning_tokens"] += reasoning
                self.model_usage[model]["latency_ms"] += latency

                # Track call
                self.recent_calls.append(
                    ModelCallStats(
                        model=model,
                        prompt_tokens=prompt,
                        completion_tokens=completion,
                        reasoning_tokens=reasoning,
                        latency_ms=latency,
                    )
                )
                # Keep only recent calls
                if len(self.recent_calls) > 100:
                    self.recent_calls = self.recent_calls[-100:]

            case EventKind.TURN_COMPLETED:
                turn_id = event.turn_id
                total_time = event.payload.get("total_time_ms", 0)
                self.turn_stats[turn_id] = {
                    "total_time_ms": total_time,
                    "timestamp": event.ts_wall.isoformat(),
                }

    def get_summary(self) -> dict[str, Any]:
        """Get analytics summary."""
        return {
            "total_tokens": (
                self.total_prompt_tokens
                + self.total_completion_tokens
                + self.total_reasoning_tokens
            ),
            "prompt_tokens": self.total_prompt_tokens,
            "completion_tokens": self.total_completion_tokens,
            "reasoning_tokens": self.total_reasoning_tokens,
            "total_latency_ms": self.total_latency_ms,
            "model_count": len(self.model_usage),
            "call_count": len(self.recent_calls),
            "turn_count": len(self.turn_stats),
        }
