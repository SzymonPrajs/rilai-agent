"""TurnStateProjection - maintains UI state from event stream."""

from dataclasses import dataclass, field
from typing import Literal, List, Dict, Any

from rilai.contracts.events import EngineEvent, EventKind


UIUpdateKind = Literal[
    "sensors", "stance", "agents", "workspace",
    "critics", "memory", "chat", "activity", "claims"
]


@dataclass
class UIUpdate:
    """A single UI update to apply."""
    kind: UIUpdateKind
    payload: Dict[str, Any]


@dataclass
class TurnStateProjection:
    """Maintains TUI-ready state from event stream.

    This is the core of the projection-based UI. It receives events
    and produces UI updates. The app simply applies these updates
    to widgets.
    """

    # Sensor state
    sensors: Dict[str, float] = field(default_factory=dict)

    # Stance state
    stance: Dict[str, float] = field(default_factory=dict)
    stance_changes: Dict[str, float] = field(default_factory=dict)

    # Agent activity
    agent_logs: List[Dict[str, Any]] = field(default_factory=list)
    active_agents: List[str] = field(default_factory=list)

    # Workspace
    workspace: Dict[str, Any] = field(default_factory=dict)
    claims: List[Dict[str, Any]] = field(default_factory=list)
    consensus: float = 0.0

    # Critics
    critics: List[Dict[str, Any]] = field(default_factory=list)

    # Memory
    memory_summary: Dict[str, Any] = field(default_factory=dict)

    # Chat
    messages: List[Dict[str, str]] = field(default_factory=list)

    # Activity
    current_stage: str = "idle"
    turn_id: int = 0
    processing: bool = False

    def apply_event(self, event: EngineEvent) -> List[UIUpdate]:
        """Apply event and return UI updates.

        This is the main entry point. Each event type produces
        zero or more UI updates.
        """
        updates = []

        match event.kind:
            # Turn lifecycle
            case EventKind.TURN_STARTED:
                self.processing = True
                self.turn_id = event.payload.get("turn_id", 0)
                user_input = event.payload.get("user_input", "")
                self.messages.append({"role": "user", "content": user_input})
                updates.append(UIUpdate("chat", {"role": "user", "content": user_input}))
                updates.append(UIUpdate("activity", {"stage": "starting", "processing": True}))

            case EventKind.TURN_STAGE_CHANGED:
                self.current_stage = event.payload.get("stage", "idle")
                updates.append(UIUpdate("activity", {"stage": self.current_stage}))

            case EventKind.TURN_COMPLETED:
                self.processing = False
                total_time = event.payload.get("total_time_ms", 0)
                updates.append(UIUpdate("activity", {
                    "stage": "completed",
                    "processing": False,
                    "total_time_ms": total_time,
                }))

            # Sensors
            case EventKind.SENSORS_FAST_UPDATED:
                new_sensors = event.payload.get("sensors", {})
                self.sensors.update(new_sensors)
                updates.append(UIUpdate("sensors", {"sensors": self.sensors}))

            # Stance
            case EventKind.STANCE_UPDATED:
                delta = event.payload.get("delta", {})
                for key, change in delta.items():
                    old_val = self.stance.get(key, 0.0)
                    self.stance[key] = old_val + change
                    self.stance_changes[key] = change
                updates.append(UIUpdate("stance", {
                    "stance": self.stance,
                    "changes": self.stance_changes,
                }))

            # Agents
            case EventKind.AGENT_STARTED:
                agent_id = event.payload.get("agent_id", "?")
                self.active_agents.append(agent_id)
                updates.append(UIUpdate("agents", {"started": agent_id}))

            case EventKind.AGENT_COMPLETED:
                agent_id = event.payload.get("agent_id", "?")
                observation = event.payload.get("observation", "")
                salience = event.payload.get("salience", 0.0)
                urgency = event.payload.get("urgency", 0)
                processing_time = event.payload.get("processing_time_ms", 0)

                if agent_id in self.active_agents:
                    self.active_agents.remove(agent_id)

                # Only log non-quiet observations
                if observation and observation.lower() != "quiet":
                    log_entry = {
                        "agent_id": agent_id,
                        "observation": observation,
                        "salience": salience,
                        "urgency": urgency,
                        "time_ms": processing_time,
                    }
                    self.agent_logs.append(log_entry)
                    updates.append(UIUpdate("agents", {"completed": log_entry}))

            case EventKind.AGENT_FAILED:
                agent_id = event.payload.get("agent_id", "?")
                error = event.payload.get("error", "Unknown error")
                if agent_id in self.active_agents:
                    self.active_agents.remove(agent_id)
                updates.append(UIUpdate("agents", {"failed": agent_id, "error": error}))

            # Workspace
            case EventKind.WORKSPACE_PATCHED:
                patch = event.payload.get("patch", {})
                self.workspace.update(patch)
                updates.append(UIUpdate("workspace", {"patch": patch}))

            # Deliberation
            case EventKind.DELIB_ROUND_STARTED:
                round_num = event.payload.get("round", 0)
                updates.append(UIUpdate("activity", {"stage": f"deliberation_r{round_num}"}))

            case EventKind.CONSENSUS_UPDATED:
                self.consensus = event.payload.get("score", 0.0)
                updates.append(UIUpdate("workspace", {"consensus": self.consensus}))

            # Council
            case EventKind.COUNCIL_DECISION_MADE:
                decision = {
                    "speak": event.payload.get("speak", False),
                    "urgency": event.payload.get("urgency", "low"),
                    "intent": event.payload.get("intent"),
                }
                updates.append(UIUpdate("workspace", {"decision": decision}))

            # Voice
            case EventKind.VOICE_RENDERED:
                text = event.payload.get("text", "")
                if text:
                    self.messages.append({"role": "assistant", "content": text})
                    updates.append(UIUpdate("chat", {"role": "assistant", "content": text}))

            # Critics
            case EventKind.CRITICS_UPDATED:
                self.critics = event.payload.get("results", [])
                passed = event.payload.get("passed", True)
                updates.append(UIUpdate("critics", {
                    "results": self.critics,
                    "passed": passed,
                }))

            # Memory
            case EventKind.MEMORY_COMMITTED:
                self.memory_summary = event.payload.get("summary", {})
                updates.append(UIUpdate("memory", {"summary": self.memory_summary}))

            # Safety
            case EventKind.SAFETY_INTERRUPT:
                reason = event.payload.get("reason", "Unknown")
                updates.append(UIUpdate("activity", {"safety_interrupt": reason}))

            # Daemon
            case EventKind.PROACTIVE_NUDGE:
                nudge = event.payload
                updates.append(UIUpdate("chat", {
                    "role": "system",
                    "content": f"[Nudge: {nudge.get('reason', '?')}]",
                }))

        return updates

    def reset_for_turn(self) -> None:
        """Reset transient state for new turn."""
        self.agent_logs.clear()
        self.active_agents.clear()
        self.claims.clear()
        self.critics.clear()
        self.stance_changes.clear()
        self.consensus = 0.0
        self.current_stage = "idle"

    def get_agent_summary(self) -> str:
        """Get summary of agent activity for display."""
        if not self.agent_logs:
            return "No agent activity"

        lines = []
        for log in self.agent_logs[-10:]:
            urgency_marker = "!" * log.get("urgency", 0)
            lines.append(f"{log['agent_id']}: {log['observation'][:60]} {urgency_marker}")

        return "\n".join(lines)
