"""Core module - engine, events, sessions, stance, workspace, goal policy."""

from .engine import Engine
from .events import Event, EventBus, EventType, event_bus
from .session import Message, Session, SessionManager
from .stance import StanceVector, update_stance, create_default_stance
from .workspace import (
    WorkspacePacket,
    InteractionGoal,
    CueExtraction,
    AgentHighlight,
    Hypothesis,
    PrioritizedQuestion,
    create_empty_workspace,
)
from .goal_policy import select_goal, check_escalation_needed

__all__ = [
    # Engine
    "Engine",
    # Events
    "Event",
    "EventBus",
    "EventType",
    "event_bus",
    # Session
    "Message",
    "Session",
    "SessionManager",
    # Stance
    "StanceVector",
    "update_stance",
    "create_default_stance",
    # Workspace
    "WorkspacePacket",
    "InteractionGoal",
    "CueExtraction",
    "AgentHighlight",
    "Hypothesis",
    "PrioritizedQuestion",
    "create_empty_workspace",
    # Goal Policy
    "select_goal",
    "check_escalation_needed",
]
