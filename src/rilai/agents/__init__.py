"""Agents module - LLM-based evaluators and micro-agents."""

# New micro-agent architecture (primary)
from .micro import (
    MicroAgentOutput,
    MicroHypothesis,
    MicroQuestion,
    merge_stance_deltas,
    select_top_agents,
    AGENT_GROUPS,
)
from .runner import MicroAgentRunner, run_agent_ensemble

# Legacy imports are deferred to avoid circular imports
# Use: from rilai.agents.base import LLMAgent
# Use: from rilai.agents.protocol import Agent, AgentConfig

__all__ = [
    # Micro-agents (new architecture)
    "MicroAgentOutput",
    "MicroHypothesis",
    "MicroQuestion",
    "merge_stance_deltas",
    "select_top_agents",
    "AGENT_GROUPS",
    "MicroAgentRunner",
    "run_agent_ensemble",
]
