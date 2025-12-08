"""TUI widgets."""

from .agency_status import AgencyStatus
from .chat import ChatInput, ChatPanel, MessageLog
from .modulators import ModulatorsPanel
from .thinking import ThinkingPanel
from .state_inspector import (
    StateInspector,
    StanceVectorWidget,
    SensorPanelWidget,
    MicroAgentsTree,
    WorkspaceCollapsible,
    CriticsCollapsible,
    MemoryCollapsible,
    TurnState,
)

__all__ = [
    # Legacy widgets
    "AgencyStatus",
    "ChatInput",
    "ChatPanel",
    "MessageLog",
    "ModulatorsPanel",
    "ThinkingPanel",
    # New state inspector widgets
    "StateInspector",
    "StanceVectorWidget",
    "SensorPanelWidget",
    "MicroAgentsTree",
    "WorkspaceCollapsible",
    "CriticsCollapsible",
    "MemoryCollapsible",
    "TurnState",
]
