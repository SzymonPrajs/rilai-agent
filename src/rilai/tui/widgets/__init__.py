"""TUI widgets."""

from .agency_status import AgencyStatus
from .chat import ChatInput, ChatPanel, MessageLog, NudgeMessage
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
)
# Re-export TurnState from core for backwards compatibility
from rilai.core.turn_state import TurnState

__all__ = [
    # Legacy widgets
    "AgencyStatus",
    "ChatInput",
    "ChatPanel",
    "MessageLog",
    "NudgeMessage",
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
