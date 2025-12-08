"""Agent scheduler - decides which agents to run."""

from typing import TYPE_CHECKING

from rilai.contracts.agent import AgentPriority, AgentManifest
from rilai.contracts.workspace import GlobalModulators

if TYPE_CHECKING:
    from rilai.agents.registry import AgentRegistry


class Scheduler:
    """Schedules agents based on sensors, modulators, and budgets.

    Replaces v2's GenericAgency gating with explicit scheduling.
    """

    def __init__(
        self,
        registry: "AgentRegistry | None" = None,
        max_agents_per_wave: int = 10,
        token_budget: int = 10000,
    ):
        self.registry = registry
        self.max_agents_per_wave = max_agents_per_wave
        self.token_budget = token_budget

        # Cooldown tracking
        self._cooldowns: dict[str, float] = {}

    def get_agent_waves(
        self,
        sensors: dict[str, float],
        modulators: GlobalModulators,
    ) -> list[list[str]]:
        """Get agents to run organized into waves.

        Wave 0: Always-on agents (censor, trigger_watcher, etc.)
        Wave 1+: Scheduled agents based on sensors/modulators

        Returns:
            List of waves, each wave is a list of agent_ids
        """
        if self.registry is None:
            # Return placeholder if no registry
            return [
                ["inhibition.censor", "monitoring.trigger_watcher", "monitoring.anomaly_detector"],
                ["emotion.stress", "emotion.wellbeing"],
            ]

        waves = []

        # Wave 0: Always-on agents
        always_on = [
            agent_id
            for agent_id, manifest in self.registry.manifests.items()
            if manifest.priority == AgentPriority.ALWAYS_ON
        ]
        if always_on:
            waves.append(always_on)

        # Wave 1: Scheduled based on sensors/modulators
        scheduled = self._schedule_agents(sensors, modulators)
        if scheduled:
            waves.append(scheduled)

        return waves

    def _schedule_agents(
        self,
        sensors: dict[str, float],
        modulators: GlobalModulators,
    ) -> list[str]:
        """Schedule agents based on current state."""
        if self.registry is None:
            return []

        candidates: list[tuple[str, float]] = []  # (agent_id, priority_score)

        for agent_id, manifest in self.registry.manifests.items():
            if manifest.priority == AgentPriority.ALWAYS_ON:
                continue  # Already in wave 0

            # Check cooldown
            if self._is_on_cooldown(agent_id):
                continue

            # Calculate priority score
            score = self._calculate_priority(agent_id, manifest, sensors, modulators)
            if score > 0:
                candidates.append((agent_id, score))

        # Sort by score and take top N
        candidates.sort(key=lambda x: x[1], reverse=True)
        return [agent_id for agent_id, _ in candidates[: self.max_agents_per_wave]]

    def _calculate_priority(
        self,
        agent_id: str,
        manifest: AgentManifest,
        sensors: dict[str, float],
        modulators: GlobalModulators,
    ) -> float:
        """Calculate priority score for an agent."""
        score = 0.0
        agency = manifest.agency_id

        # Sensor-based activation
        if agency == "emotion" and sensors.get("vulnerability", 0) > 0.3:
            score += sensors["vulnerability"]
        if agency == "reasoning" and sensors.get("advice_requested", 0) > 0.3:
            score += sensors["advice_requested"]
        if agency == "social" and sensors.get("relational_bid", 0) > 0.3:
            score += sensors["relational_bid"]

        # Modulator-based activation
        if agency in ("emotion", "monitoring") and modulators.arousal > 0.6:
            score += 0.3
        if agency == "planning" and modulators.time_pressure > 0.5:
            score += 0.3
        if agency in ("social", "inhibition") and modulators.social_risk > 0.5:
            score += 0.3

        # Monitor agents get a base score
        if manifest.priority == AgentPriority.MONITOR:
            score += 0.2

        return score

    def _is_on_cooldown(self, agent_id: str) -> bool:
        """Check if agent is on cooldown."""
        import time
        cooldown_until = self._cooldowns.get(agent_id, 0)
        return time.time() < cooldown_until

    def mark_fired(self, agent_id: str, cooldown_seconds: float = 30.0) -> None:
        """Mark an agent as fired and set cooldown."""
        import time
        self._cooldowns[agent_id] = time.time() + cooldown_seconds
