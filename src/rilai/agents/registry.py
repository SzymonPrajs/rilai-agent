"""Agent registry - loads and manages agents."""

from pathlib import Path
from typing import Dict

from rilai.contracts.agent import AgentManifest, AgentPriority
from rilai.agents.base_v3 import BaseAgent
from rilai.agents.manifest import discover_agents


class AgentRegistry:
    """Registry of all available agents."""

    def __init__(self):
        self.manifests: Dict[str, AgentManifest] = {}
        self._agents: Dict[str, BaseAgent] = {}

    def load_from_directory(self, prompts_dir: Path) -> None:
        """Load all agents from prompts directory."""
        agents = discover_agents(prompts_dir)

        for manifest, prompt_text in agents:
            self.manifests[manifest.id] = manifest
            self._agents[manifest.id] = BaseAgent(manifest, prompt_text)

    def register_agent(self, manifest: AgentManifest, prompt_text: str) -> None:
        """Register an agent manually."""
        self.manifests[manifest.id] = manifest
        self._agents[manifest.id] = BaseAgent(manifest, prompt_text)

    def get_agent(self, agent_id: str) -> BaseAgent | None:
        """Get agent by ID."""
        return self._agents.get(agent_id)

    def get_agents_by_agency(self, agency_id: str) -> list[BaseAgent]:
        """Get all agents for an agency."""
        return [
            agent
            for agent_id, agent in self._agents.items()
            if agent_id.startswith(f"{agency_id}.")
        ]

    def get_always_on_agents(self) -> list[str]:
        """Get IDs of always-on agents."""
        return [
            agent_id
            for agent_id, manifest in self.manifests.items()
            if manifest.priority == AgentPriority.ALWAYS_ON
        ]

    def list_agents(self) -> list[str]:
        """List all registered agent IDs."""
        return list(self._agents.keys())


# Global registry instance
_registry: AgentRegistry | None = None


def get_registry() -> AgentRegistry:
    """Get the global agent registry."""
    global _registry
    if _registry is None:
        _registry = AgentRegistry()
        # Try to load from default location
        prompts_dir = Path(__file__).parent.parent.parent.parent / "prompts"
        if prompts_dir.exists():
            _registry.load_from_directory(prompts_dir)
    return _registry


def reset_registry() -> None:
    """Reset the global registry (for testing)."""
    global _registry
    _registry = None
