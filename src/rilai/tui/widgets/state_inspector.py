"""
State Inspector Widget

Hierarchical inspector for all cognitive states in the two-pass pipeline.
Provides expandable views of stance, sensors, agents, workspace, critics, and memory.
"""

from textual.app import ComposeResult
from textual.containers import ScrollableContainer
from textual.widgets import Collapsible, Static, Tree

from rilai.core.turn_state import TurnState
from rilai.tui.theme import (
    BAR_EMPTY,
    BAR_FILLED,
    make_bar,
)


class StanceVectorWidget(Static):
    """Real-time stance vector visualization with bar charts."""

    DEFAULT_CSS = """
    StanceVectorWidget {
        border: solid $secondary;
        border-title-color: $secondary;
        padding: 0 1;
        height: auto;
        margin-bottom: 1;
    }
    """

    def __init__(self, **kwargs):
        super().__init__("No stance data", **kwargs)
        self.border_title = "▼ STANCE VECTOR"
        self._stance: dict = {}

    def update_stance(self, stance: dict) -> None:
        """Update the stance display."""
        self._stance = stance

        if not self._stance:
            self.update("No stance data")
            return

        lines = []
        dimensions = [
            ("valence", -1, 1),
            ("arousal", 0, 1),
            ("control", 0, 1),
            ("certainty", 0, 1),
            ("safety", 0, 1),
            ("closeness", 0, 1),
            ("curiosity", 0, 1),
            ("strain", 0, 1),
        ]

        for dim, min_val, max_val in dimensions:
            value = self._stance.get(dim, 0)
            bar = make_bar(value, 10, min_val, max_val)
            if min_val < 0:
                lines.append(f"  {dim:<10} {bar} {value:+.2f}")
            else:
                lines.append(f"  {dim:<10} {bar}  {value:.2f}")

        # Derived quantities
        readiness = self._stance.get("readiness_to_speak", 0)
        suppression = self._stance.get("advice_suppression", 0)
        lines.append("  ─" * 12)
        lines.append(f"  readiness: {readiness:.2f}  suppression: {suppression:.2f}")

        self.update("\n".join(lines))


class SensorPanelWidget(Static):
    """Sensor probabilities display."""

    DEFAULT_CSS = """
    SensorPanelWidget {
        border: solid $success;
        border-title-color: $success;
        padding: 0 1;
        height: auto;
        margin-bottom: 1;
    }
    """

    def __init__(self, **kwargs):
        super().__init__("No sensor data", **kwargs)
        self.border_title = "▼ SENSORS (9)"
        self._sensors = {}

    def update_sensors(self, sensors: dict) -> None:
        """Update sensor display."""
        self._sensors = sensors

        if not self._sensors:
            self.update("No sensor data")
            return

        lines = []
        # Sort by probability descending
        sorted_sensors = sorted(self._sensors.items(), key=lambda x: -x[1])

        for sensor, prob in sorted_sensors:
            bar = BAR_FILLED * int(prob * 4) + BAR_EMPTY * (4 - int(prob * 4))
            lines.append(f"  {sensor:<18} {bar} {prob:.2f}")

        self.update("\n".join(lines))


class MicroAgentsTree(Tree):
    """Expandable tree view of micro-agents."""

    DEFAULT_CSS = """
    MicroAgentsTree {
        border: solid $accent;
        border-title-color: $accent;
        height: auto;
        max-height: 15;
        margin-bottom: 1;
    }

    MicroAgentsTree > .tree--cursor {
        background: $accent 20%;
    }
    """

    def __init__(self, **kwargs):
        super().__init__("▼ MICRO-AGENTS", **kwargs)
        self._agents = []

    def on_mount(self) -> None:
        """Initialize the tree with a placeholder."""
        self.root.add_leaf("No agents active")

    def update_agents(self, agents: list) -> None:
        """Update agent tree from list of agent outputs."""
        self._agents = agents
        self._rebuild_tree()

    def _rebuild_tree(self) -> None:
        """Rebuild the tree from agent data."""
        self.clear()

        if not self._agents:
            self.root.add_leaf("No agents active")
            return

        # Sort by salience
        sorted_agents = sorted(self._agents, key=lambda x: -x.get("salience", 0))
        active_count = sum(1 for a in sorted_agents if a.get("salience", 0) > 0.1)
        self.root.label = f"▼ MICRO-AGENTS ({active_count} active)"

        for agent in sorted_agents[:10]:  # Top 10
            agent_name = agent.get("agent", "unknown")
            salience = agent.get("salience", 0)
            glimpse = agent.get("glimpse", "")

            # Create agent node
            label = f"{agent_name} [{salience:.2f}]"
            agent_node = self.root.add(label)

            # Add glimpse if present
            if glimpse:
                agent_node.add_leaf(f"💭 {glimpse[:50]}...")

            # Add stance delta if present
            delta = agent.get("stance_delta", {})
            if delta:
                delta_text = ", ".join(f"{k}:{v:+.2f}" for k, v in delta.items() if v != 0)
                if delta_text:
                    agent_node.add_leaf(f"Δ {delta_text}")

            # Add hypotheses
            hypotheses = agent.get("hypotheses", [])
            if hypotheses:
                for h in hypotheses[:2]:
                    h_text = h.get("h", h.get("text", ""))[:40]
                    h_p = h.get("p", 0)
                    agent_node.add_leaf(f"H: {h_text}... p={h_p:.2f}")

            # Add questions
            questions = agent.get("questions", [])
            if questions:
                for q in questions[:2]:
                    q_text = q.get("q", q.get("question", ""))[:40]
                    agent_node.add_leaf(f"Q: {q_text}...")


class WorkspaceCollapsible(Collapsible):
    """Collapsible workspace packet view."""

    can_focus = True

    DEFAULT_CSS = """
    WorkspaceCollapsible {
        border: solid $warning;
        border-title-color: $warning;
        margin-bottom: 1;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(title="▶ WORKSPACE PACKET", **kwargs)
        self._content = Static("No workspace data")
        self._workspace = {}

    def compose(self) -> ComposeResult:
        yield self._content

    def update_workspace(self, workspace: dict) -> None:
        """Update workspace display."""
        self._workspace = workspace

        lines = []
        lines.append(f"  Goal: {workspace.get('goal', 'unknown').upper()}")
        lines.append(f"  Primary Q: {workspace.get('primary_question', '')[:50]}")

        constraints = workspace.get("constraints", [])
        if constraints:
            lines.append("  Constraints:")
            for c in constraints[:3]:
                lines.append(f"    • {c}")

        if workspace.get("escalate_to_large"):
            lines.append(f"  ⚠ ESCALATED: {workspace.get('escalation_reason', '')}")

        self._content.update("\n".join(lines))


class CriticsCollapsible(Collapsible):
    """Collapsible critics results view."""

    can_focus = True

    DEFAULT_CSS = """
    CriticsCollapsible {
        border: solid $error;
        border-title-color: $error;
        margin-bottom: 1;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(title="▶ CRITICS (6)", **kwargs)
        self._content = Static("No critic data")
        self._critics = []

    def compose(self) -> ComposeResult:
        yield self._content

    def update_critics(self, critics: list) -> None:
        """Update critics display."""
        self._critics = critics

        if not critics:
            self._content.update("No critic results")
            return

        lines = []
        for c in critics:
            critic_name = c.get("critic", "unknown")
            passed = c.get("passed", True)
            reason = c.get("reason", "")

            status = "✓" if passed else "✗"
            line = f"  {status} {critic_name}"
            if not passed and reason:
                line += f": {reason[:30]}"
            lines.append(line)

        passed_count = sum(1 for c in critics if c.get("passed", True))
        self.title = f"▶ CRITICS ({passed_count}/{len(critics)} pass)"

        self._content.update("\n".join(lines))


class MemoryCollapsible(Collapsible):
    """Collapsible relational memory view."""

    can_focus = True

    DEFAULT_CSS = """
    MemoryCollapsible {
        border: solid $primary;
        border-title-color: $primary;
        margin-bottom: 1;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(title="▶ RELATIONAL MEMORY", **kwargs)
        self._content = Static("No memory data")
        self._memory = {}

    def compose(self) -> ComposeResult:
        yield self._content

    def update_memory(self, memory: dict) -> None:
        """Update memory display."""
        self._memory = memory

        lines = []
        summary = memory.get("summary", "")
        if summary:
            lines.append(f"  Summary: {summary[:60]}...")

        evidence = memory.get("evidence", [])
        hypotheses = memory.get("hypotheses", [])

        lines.append(f"  Evidence: {len(evidence)} shards")
        lines.append(f"  Hypotheses: {len(hypotheses)} active")

        # Show top hypotheses
        if hypotheses:
            lines.append("  Top hypotheses:")
            for h in sorted(hypotheses, key=lambda x: -x.get("p", 0))[:3]:
                text = h.get("text", "")[:40]
                p = h.get("p", 0)
                lines.append(f"    • {text}... (p={p:.2f})")

        self._content.update("\n".join(lines))


class StateInspector(ScrollableContainer):
    """
    Hierarchical inspector for all cognitive states.

    Shows stance, sensors, agents, workspace, critics, and memory
    in an expandable tree structure.
    """

    BINDINGS = [
        ("up", "focus_previous", "Previous"),
        ("down", "focus_next", "Next"),
    ]

    DEFAULT_CSS = """
    StateInspector {
        width: 50%;
        height: 100%;
        border-left: solid $surface-darken-1;
        background: $surface;
        overflow-y: auto;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._stance_widget: StanceVectorWidget | None = None
        self._sensor_widget: SensorPanelWidget | None = None
        self._agents_tree: MicroAgentsTree | None = None
        self._workspace_widget: WorkspaceCollapsible | None = None
        self._critics_widget: CriticsCollapsible | None = None
        self._memory_widget: MemoryCollapsible | None = None

    def compose(self) -> ComposeResult:
        self._stance_widget = StanceVectorWidget()
        self._sensor_widget = SensorPanelWidget()
        self._agents_tree = MicroAgentsTree()
        self._workspace_widget = WorkspaceCollapsible()
        self._critics_widget = CriticsCollapsible()
        self._memory_widget = MemoryCollapsible()

        yield self._stance_widget
        yield self._sensor_widget
        yield self._agents_tree
        yield self._workspace_widget
        yield self._critics_widget
        yield self._memory_widget

    def get_focusable_children(self) -> list:
        """Return list of focusable child widgets in order."""
        return [
            self._agents_tree,
            self._workspace_widget,
            self._critics_widget,
            self._memory_widget,
        ]

    def action_focus_previous(self) -> None:
        """Focus the previous focusable section."""
        focusables = self.get_focusable_children()
        current = self.app.focused
        if current in focusables:
            idx = focusables.index(current)
            if idx > 0:
                focusables[idx - 1].focus()
                self.scroll_to_widget(focusables[idx - 1])

    def action_focus_next(self) -> None:
        """Focus the next focusable section."""
        focusables = self.get_focusable_children()
        current = self.app.focused
        if current in focusables:
            idx = focusables.index(current)
            if idx < len(focusables) - 1:
                focusables[idx + 1].focus()
                self.scroll_to_widget(focusables[idx + 1])

    def focus_first(self) -> None:
        """Focus the first focusable child."""
        if self._agents_tree:
            self._agents_tree.focus()
            self.scroll_to_widget(self._agents_tree)

    def update_turn_state(self, state: TurnState) -> None:
        """Update all widgets with new turn state."""
        if self._stance_widget and state.stance:
            self._stance_widget.update_stance(state.stance)

        if self._sensor_widget and state.sensors:
            self._sensor_widget.update_sensors(state.sensors)

        if self._agents_tree and state.agents:
            self._agents_tree.update_agents(state.agents)

        if self._workspace_widget and state.workspace:
            self._workspace_widget.update_workspace(state.workspace)

        if self._critics_widget and state.critics:
            self._critics_widget.update_critics(state.critics)

        if self._memory_widget and state.memory:
            self._memory_widget.update_memory(state.memory)

    def update_stance(self, stance: dict) -> None:
        """Update only the stance display."""
        if self._stance_widget:
            self._stance_widget.update_stance(stance)

    def update_sensors(self, sensors: dict) -> None:
        """Update only the sensors display."""
        if self._sensor_widget:
            self._sensor_widget.update_sensors(sensors)

    def update_agents(self, agents: list) -> None:
        """Update only the agents display."""
        if self._agents_tree:
            self._agents_tree.update_agents(agents)
