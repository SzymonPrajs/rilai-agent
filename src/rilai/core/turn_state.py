"""Turn state data structures for TUI integration.

This module defines the data structures that flow from the Engine to the TUI
to populate the right-side panels (stance, sensors, agents, workspace, critics, memory).
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TurnState:
    """Complete state for a turn, used to update the TUI inspector panels."""

    turn_id: int = 0
    stance: dict = field(default_factory=dict)
    sensors: dict = field(default_factory=dict)
    agents: list = field(default_factory=list)
    workspace: dict = field(default_factory=dict)
    critics: list = field(default_factory=list)
    memory: dict = field(default_factory=dict)


@dataclass
class EngineResult:
    """Result from processing a message through the engine.

    Contains both the response string and the full turn state for TUI panels.
    """

    response: str
    turn_state: TurnState


def build_turn_state(
    turn_id: int,
    stance: dict | None = None,
    sensors: dict | None = None,
    agents: list | None = None,
    workspace: dict | None = None,
    critics: list | None = None,
    memory: dict | None = None,
) -> TurnState:
    """Build a TurnState from individual components.

    Args:
        turn_id: The current turn ID
        stance: Stance vector dict with dimensions (valence, arousal, etc.)
        sensors: Sensor probabilities dict (vulnerability, advice_requested, etc.)
        agents: List of agent dicts with salience, glimpse, etc.
        workspace: Workspace dict with goal, primary_question, constraints
        critics: List of critic result dicts with passed, reason, severity
        memory: Memory dict with summary, evidence, hypotheses

    Returns:
        A TurnState object ready for TUI display
    """
    return TurnState(
        turn_id=turn_id,
        stance=stance or {},
        sensors=sensors or {},
        agents=agents or [],
        workspace=workspace or {},
        critics=critics or [],
        memory=memory or {},
    )
