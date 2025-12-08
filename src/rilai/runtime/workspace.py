"""Workspace - global blackboard for agent coordination."""

import time
from typing import Any

from rilai.contracts.workspace import (
    StanceVector,
    GlobalModulators,
    Goal,
    WorkspaceState,
)
from rilai.contracts.agent import AgentOutput, Claim


class Workspace:
    """Global workspace / blackboard state.

    All agents read from this, and propose updates through AgentOutput.
    The reducer merges proposals deterministically.
    """

    def __init__(self):
        self._state = WorkspaceState()
        self._active_claims: list[Claim] = []
        self._stance_before: dict[str, float] = {}
        self._sensors: dict[str, float] = {}
        self._pending_asks: list[str] = []

    # ─────────────────────────────────────────────────────────────────────
    # Context Slots (set at turn start)
    # ─────────────────────────────────────────────────────────────────────

    @property
    def user_message(self) -> str:
        return self._state.user_message

    def set_user_message(self, message: str) -> None:
        """Set the current user message and update timestamp."""
        self._state.user_message = message
        self._state.last_user_message_time = time.time()
        self._stance_before = self._state.stance.to_dict()

    @property
    def turn_id(self) -> int:
        return self._state.turn_id

    @turn_id.setter
    def turn_id(self, value: int) -> None:
        self._state.turn_id = value

    @property
    def conversation_history(self) -> list[dict[str, Any]]:
        return self._state.conversation_history

    @property
    def retrieved_episodes(self) -> list[dict]:
        return self._state.retrieved_episodes

    @retrieved_episodes.setter
    def retrieved_episodes(self, value: list[dict]) -> None:
        self._state.retrieved_episodes = value

    @property
    def user_facts(self) -> list[dict]:
        return self._state.user_facts

    @user_facts.setter
    def user_facts(self, value: list[dict]) -> None:
        self._state.user_facts = value

    @property
    def open_threads(self) -> list[Goal]:
        return self._state.open_threads

    @open_threads.setter
    def open_threads(self, value: list[Goal]) -> None:
        self._state.open_threads = value

    # ─────────────────────────────────────────────────────────────────────
    # Live State (updated by reducer)
    # ─────────────────────────────────────────────────────────────────────

    @property
    def stance(self) -> StanceVector:
        return self._state.stance

    @property
    def modulators(self) -> GlobalModulators:
        return self._state.modulators

    @property
    def active_claims(self) -> list[Claim]:
        return self._active_claims

    @property
    def consensus_level(self) -> float:
        return self._state.consensus_level

    @consensus_level.setter
    def consensus_level(self, value: float) -> None:
        self._state.consensus_level = value

    @property
    def sensors(self) -> dict[str, float]:
        """Get sensors from workspace."""
        return self._sensors

    @sensors.setter
    def sensors(self, value: dict[str, float]) -> None:
        self._sensors = value

    # ─────────────────────────────────────────────────────────────────────
    # Decision Slots (set by council)
    # ─────────────────────────────────────────────────────────────────────

    @property
    def current_goal(self) -> str | None:
        return self._state.current_goal

    @current_goal.setter
    def current_goal(self, value: str | None) -> None:
        self._state.current_goal = value

    @property
    def constraints(self) -> list[str]:
        return self._state.constraints

    @constraints.setter
    def constraints(self, value: list[str]) -> None:
        self._state.constraints = value

    @property
    def pending_asks(self) -> list[str]:
        return self._pending_asks

    @pending_asks.setter
    def pending_asks(self, value: list[str]) -> None:
        self._pending_asks = value

    @property
    def current_response(self) -> str | None:
        return self._state.current_response

    @current_response.setter
    def current_response(self, value: str | None) -> None:
        self._state.current_response = value

    # ─────────────────────────────────────────────────────────────────────
    # Methods
    # ─────────────────────────────────────────────────────────────────────

    def reset_for_turn(self) -> None:
        """Reset transient state for a new turn."""
        self._active_claims.clear()
        self._state.consensus_level = 0.0
        self._state.current_goal = None
        self._state.constraints.clear()
        self._pending_asks.clear()
        self._state.current_response = None
        self._stance_before = self._state.stance.to_dict()

    def apply_agent_output(self, output: AgentOutput) -> None:
        """Apply an agent's output to the workspace.

        This is the main entry point for the reducer.
        """
        from rilai.runtime.reducer import apply_output
        apply_output(self, output)

    def get_stance_delta(self) -> dict[str, float] | None:
        """Get stance changes since turn start."""
        current = self._state.stance.to_dict()
        delta = {}
        for key, val in current.items():
            before = self._stance_before.get(key, val)
            if abs(val - before) > 0.01:
                delta[key] = val - before
        return delta if delta else None

    def to_prompt_context(self) -> str:
        """Format workspace for inclusion in agent prompts."""
        lines = [
            f"User message: {self.user_message}",
            "",
            "Recent conversation:",
        ]
        for msg in self.conversation_history[-5:]:
            role = msg.get("role", "?")
            content = msg.get("content", "")[:100]
            lines.append(f"  {role}: {content}")

        lines.append("")
        lines.append(f"Current stance: {self._state.stance.to_dict()}")
        lines.append(f"Modulators: {self._state.modulators.to_dict()}")

        if self._active_claims:
            lines.append("")
            lines.append(f"Active claims ({len(self._active_claims)}):")
            for claim in self._active_claims[:5]:
                lines.append(f"  - [{claim.type}] {claim.text}")

        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Export workspace state as dict."""
        return self._state.model_dump()
