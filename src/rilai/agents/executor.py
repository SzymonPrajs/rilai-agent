"""Parallel agent execution."""

import asyncio
from typing import Callable, TYPE_CHECKING

from rilai.contracts.agent import AgentOutput
from rilai.contracts.events import EventKind

if TYPE_CHECKING:
    from rilai.agents.base_v3 import BaseAgent
    from rilai.runtime.workspace import Workspace


async def execute_agents(
    agent_ids: list[str],
    workspace: "Workspace",
    emit_fn: Callable | None = None,
    timeout_ms: int = 5000,
) -> list[AgentOutput]:
    """Execute multiple agents in parallel.

    Args:
        agent_ids: List of agent IDs to execute
        workspace: Current workspace
        emit_fn: Event emission function
        timeout_ms: Timeout per agent

    Returns:
        List of AgentOutput results
    """
    from rilai.agents.registry import get_registry

    registry = get_registry()
    tasks = []

    for agent_id in agent_ids:
        agent = registry.get_agent(agent_id)
        if agent is None:
            continue

        task = asyncio.create_task(
            _run_agent_safe(agent, workspace, emit_fn, timeout_ms)
        )
        tasks.append((agent_id, task))

    if not tasks:
        return []

    results = await asyncio.gather(*[t for _, t in tasks], return_exceptions=True)

    # Filter out exceptions
    outputs = []
    for i, result in enumerate(results):
        agent_id = tasks[i][0]
        if isinstance(result, Exception):
            if emit_fn:
                emit_fn(
                    EventKind.AGENT_FAILED,
                    {"agent_id": agent_id, "error": str(result)},
                )
        elif result is not None:
            outputs.append(result)

    return outputs


async def _run_agent_safe(
    agent: "BaseAgent",
    workspace: "Workspace",
    emit_fn: Callable | None,
    timeout_ms: int,
) -> AgentOutput | None:
    """Run an agent with timeout."""
    try:
        return await asyncio.wait_for(
            agent.assess(workspace, emit_fn),
            timeout=timeout_ms / 1000,
        )
    except asyncio.TimeoutError:
        return AgentOutput.quiet(agent.agent_id)
