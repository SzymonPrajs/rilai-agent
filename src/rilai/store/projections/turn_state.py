"""TurnStateProjection - maintains TUI-ready state from events."""

from dataclasses import dataclass, field
from typing import Literal, Any

from rilai.contracts.events import EngineEvent, EventKind
from rilai.store.projections.base import Projection


UIUpdateKind = Literal[
    "sensors",
    "stance",
    "agents",
    "workspace",
    "critics",
    "memory",
    "chat",
    "activity",
]


@dataclass
class UIUpdate:
    """A single UI update to apply."""

    kind: UIUpdateKind
    payload: dict[str, Any]


@dataclass
class TurnStateProjection(Projection):
    """Maintains TUI-ready state from event stream.

    This projection is designed for real-time UI updates.
    Each event produces zero or more UIUpdates that the TUI
    can apply immediately.
    """

    # Panel state
    sensors: dict[str, float] = field(default_factory=dict)
    stance: dict[str, float] = field(default_factory=dict)
    agent_logs: list[str] = field(default_factory=list)
    workspace: dict[str, Any] = field(default_factory=dict)
    critics: list[dict] = field(default_factory=list)
    memory: dict[str, Any] = field(default_factory=dict)

    # Turn state
    current_stage: str = "idle"
    current_turn_id: int = 0
    response: str = ""

    # Timing
    turn_start_time: float = 0.0
    stage_times: dict[str, float] = field(default_factory=dict)

    def reset(self) -> None:
        """Reset to initial state."""
        self.sensors.clear()
        self.stance.clear()
        self.agent_logs.clear()
        self.workspace.clear()
        self.critics.clear()
        self.memory.clear()
        self.current_stage = "idle"
        self.current_turn_id = 0
        self.response = ""
        self.turn_start_time = 0.0
        self.stage_times.clear()

    def reset_for_turn(self) -> None:
        """Reset transient state for a new turn."""
        self.agent_logs.clear()
        self.critics.clear()
        self.response = ""
        self.stage_times.clear()

    def apply(self, event: EngineEvent) -> list[UIUpdate]:
        """Apply event and return UI updates.

        This is the main method called by the TUI to process events.
        Each event can produce multiple UI updates.

        Args:
            event: The event to apply

        Returns:
            List of UI updates to apply
        """
        updates: list[UIUpdate] = []

        match event.kind:
            # ─────────────────────────────────────────────────────────────
            # Turn Lifecycle
            # ─────────────────────────────────────────────────────────────
            case EventKind.TURN_STARTED:
                self.reset_for_turn()
                self.current_turn_id = event.payload.get("turn_id", 0)
                self.turn_start_time = event.ts_monotonic
                updates.append(UIUpdate("activity", {"stage": "starting"}))

            case EventKind.TURN_STAGE_CHANGED:
                stage = event.payload.get("stage", "unknown")
                self.current_stage = stage
                self.stage_times[stage] = event.ts_monotonic
                updates.append(UIUpdate("activity", {"stage": stage}))

            case EventKind.TURN_COMPLETED:
                self.current_stage = "idle"
                self.response = event.payload.get("response", "")
                updates.append(UIUpdate("activity", {"stage": "idle"}))

            # ─────────────────────────────────────────────────────────────
            # Sensors
            # ─────────────────────────────────────────────────────────────
            case EventKind.SENSORS_FAST_UPDATED:
                self.sensors = event.payload.get("sensors", {})
                updates.append(UIUpdate("sensors", {"sensors": self.sensors}))

            # ─────────────────────────────────────────────────────────────
            # Agents
            # ─────────────────────────────────────────────────────────────
            case EventKind.AGENT_COMPLETED:
                agent_id = event.payload.get("agent_id", "?")
                observation = event.payload.get("observation", "")
                if observation and observation.lower() != "quiet":
                    line = f"{agent_id}: {observation[:100]}"
                    self.agent_logs.append(line)
                    updates.append(UIUpdate("agents", {"line": line}))

            case EventKind.AGENT_FAILED:
                agent_id = event.payload.get("agent_id", "?")
                error = event.payload.get("error", "Unknown error")
                line = f"[red]{agent_id}: FAILED - {error[:50]}[/]"
                self.agent_logs.append(line)
                updates.append(UIUpdate("agents", {"line": line}))

            # ─────────────────────────────────────────────────────────────
            # Workspace
            # ─────────────────────────────────────────────────────────────
            case EventKind.WORKSPACE_PATCHED:
                patch = event.payload.get("patch", {})
                self.workspace.update(patch)
                updates.append(UIUpdate("workspace", {"workspace": self.workspace}))

            case EventKind.STANCE_UPDATED:
                delta = event.payload.get("delta", {})
                current = event.payload.get("current", {})
                self.stance.update(current if current else delta)
                updates.append(UIUpdate("stance", {"stance": self.stance}))

            # ─────────────────────────────────────────────────────────────
            # Deliberation
            # ─────────────────────────────────────────────────────────────
            case EventKind.DELIB_ROUND_STARTED:
                round_num = event.payload.get("round", 0)
                line = f"[dim]Deliberation round {round_num} started[/]"
                self.agent_logs.append(line)
                updates.append(UIUpdate("agents", {"line": line}))

            case EventKind.CONSENSUS_UPDATED:
                level = event.payload.get("level", 0.0)
                self.workspace["consensus"] = level
                updates.append(UIUpdate("workspace", {"workspace": self.workspace}))

            # ─────────────────────────────────────────────────────────────
            # Council + Voice
            # ─────────────────────────────────────────────────────────────
            case EventKind.COUNCIL_DECISION_MADE:
                self.workspace["speak"] = event.payload.get("speak", False)
                self.workspace["urgency"] = event.payload.get("urgency", "medium")
                self.workspace["intent"] = event.payload.get("intent", "")
                updates.append(UIUpdate("workspace", {"workspace": self.workspace}))

            case EventKind.VOICE_RENDERED:
                text = event.payload.get("text", "")
                self.response = text
                updates.append(
                    UIUpdate("chat", {"text": text, "role": "assistant"})
                )

            # ─────────────────────────────────────────────────────────────
            # Critics
            # ─────────────────────────────────────────────────────────────
            case EventKind.CRITICS_UPDATED:
                self.critics = event.payload.get("results", [])
                updates.append(UIUpdate("critics", {"results": self.critics}))

            case EventKind.SAFETY_INTERRUPT:
                reason = event.payload.get("reason", "Unknown")
                self.critics.append({
                    "critic": "safety_interrupt",
                    "passed": False,
                    "reason": reason,
                })
                updates.append(UIUpdate("critics", {"results": self.critics}))
                updates.append(UIUpdate("activity", {"stage": "safety_interrupt"}))

            # ─────────────────────────────────────────────────────────────
            # Memory
            # ─────────────────────────────────────────────────────────────
            case EventKind.MEMORY_RETRIEVED:
                self.memory["retrieved"] = {
                    "episodes": len(event.payload.get("episodes", [])),
                    "user_facts": len(event.payload.get("user_facts", [])),
                    "open_threads": len(event.payload.get("open_threads", [])),
                }
                updates.append(UIUpdate("memory", {"memory": self.memory}))

            case EventKind.MEMORY_COMMITTED:
                self.memory["committed"] = event.payload.get("summary", {})
                updates.append(UIUpdate("memory", {"memory": self.memory}))

            # ─────────────────────────────────────────────────────────────
            # Daemon
            # ─────────────────────────────────────────────────────────────
            case EventKind.PROACTIVE_NUDGE:
                reason = event.payload.get("reason", "")
                suggestion = event.payload.get("suggestion", "")
                line = f"[yellow]Nudge ({reason}): {suggestion}[/]"
                self.agent_logs.append(line)
                updates.append(UIUpdate("agents", {"line": line}))

        return updates

    def get_elapsed_ms(self) -> int:
        """Get elapsed time since turn start."""
        import time
        if self.turn_start_time == 0:
            return 0
        return int((time.monotonic() - self.turn_start_time) * 1000)
