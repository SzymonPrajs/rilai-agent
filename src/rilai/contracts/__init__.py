"""Rilai v3 Contracts - All typed schemas for the system."""

from rilai.contracts.events import EngineEvent, EventKind
from rilai.contracts.agent import (
    AgentOutput,
    AgentManifest,
    AgentPriority,
    AgentSafetyProfile,
    Claim,
    ClaimType,
)
from rilai.contracts.sensor import SensorOutput, SENSOR_NAMES
from rilai.contracts.workspace import (
    WorkspaceState,
    StanceVector,
    GlobalModulators,
    Goal,
)
from rilai.contracts.council import (
    CouncilDecision,
    SpeechAct,
    VoiceResult,
    CriticResult,
    ResponseUrgency,
)
from rilai.contracts.memory import (
    MemoryCandidate,
    EpisodicEvent,
    UserFact,
)
from rilai.contracts.workspace import Goal

# Rebuild AgentOutput to resolve forward reference to MemoryCandidate
from rilai.contracts.agent import _rebuild_models
_rebuild_models()

__all__ = [
    # Events
    "EngineEvent",
    "EventKind",
    # Agent
    "AgentOutput",
    "AgentManifest",
    "AgentPriority",
    "AgentSafetyProfile",
    "Claim",
    "ClaimType",
    # Sensor
    "SensorOutput",
    "SENSOR_NAMES",
    # Workspace
    "WorkspaceState",
    "StanceVector",
    "GlobalModulators",
    "Goal",
    # Council
    "CouncilDecision",
    "SpeechAct",
    "VoiceResult",
    "CriticResult",
    "ResponseUrgency",
    # Memory
    "MemoryCandidate",
    "EpisodicEvent",
    "UserFact",
    "Goal",
]
