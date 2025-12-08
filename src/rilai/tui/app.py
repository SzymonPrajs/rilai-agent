"""Main Rilai TUI application.

Split-screen layout with conversation panel and cognitive state inspector.
Based on Industrial/Neuroscience Dashboard aesthetic.
"""

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from textual import on
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Static

from .commands import handle_command
from .widgets import (
    AgencyStatus, ChatInput, ChatPanel, ModulatorsPanel, ThinkingPanel,
    StateInspector, TurnState,
)

from rilai.core.engine import Engine
from rilai.core.events import event_bus, Event, EventType


class RilaiApp(App):
    """Rilai v2 Terminal User Interface.

    Split-screen layout:
    - Left (50%): Conversation panel
    - Right (50%): Cognitive state inspector

    The state inspector shows hierarchical views of:
    - Stance Vector (affective state)
    - Sensors (9 input detectors)
    - Micro-Agents (30 cognitive processes)
    - Workspace Packet (global broadcast)
    - Critics (validation layer)
    - Relational Memory (evidence-linked)
    """

    TITLE = "Rilai v2"
    SUB_TITLE = "Two-Pass Broadcast Architecture"

    CSS = """
    Screen {
        layout: horizontal;
        background: #1A1A2E;
    }

    /* Split-screen layout: 50/50 */
    #conversation-panel {
        width: 50%;
        height: 100%;
        border-right: solid #2E2E4D;
    }

    #state-inspector {
        width: 50%;
        height: 100%;
        background: #16213E;
        overflow-y: auto;
        padding: 0 1;
    }

    /* Chat styling */
    ChatPanel {
        height: 100%;
        background: #16213E;
    }

    /* Status bar at top */
    #status-bar {
        dock: top;
        height: 1;
        background: #0F0F1A;
        color: #6B7280;
        padding: 0 1;
    }

    /* State inspector sections */
    StanceVectorWidget {
        border: solid #F5A623;
        border-title-color: #F5A623;
        margin-bottom: 1;
    }

    SensorPanelWidget {
        border: solid #7ED321;
        border-title-color: #7ED321;
        margin-bottom: 1;
    }

    MicroAgentsTree {
        border: solid #50E3C2;
        border-title-color: #50E3C2;
        margin-bottom: 1;
        height: auto;
        max-height: 15;
    }

    WorkspaceCollapsible {
        border: solid #F8E71C;
        border-title-color: #F8E71C;
        margin-bottom: 1;
    }

    CriticsCollapsible {
        border: solid #BD10E0;
        border-title-color: #BD10E0;
        margin-bottom: 1;
    }

    MemoryCollapsible {
        border: solid #4A90D9;
        border-title-color: #4A90D9;
        margin-bottom: 1;
    }

    /* Legacy sidebar (hidden by default, can be toggled) */
    #legacy-sidebar {
        display: none;
        width: 0;
    }

    #legacy-sidebar.visible {
        display: block;
        width: 30;
    }
    """

    BINDINGS = [
        ("ctrl+d", "quit", "Quit"),
        ("ctrl+i", "toggle_inspector", "Inspector"),
        ("ctrl+l", "toggle_legacy", "Legacy View"),
        ("ctrl+h", "toggle_history", "History"),
        ("escape", "focus_input", "Focus Input"),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._chat_panel: Optional[ChatPanel] = None
        self._state_inspector: Optional[StateInspector] = None
        self._status_bar: Optional[Static] = None

        # Legacy widgets (optional)
        self._agency_status: Optional[AgencyStatus] = None
        self._modulators: Optional[ModulatorsPanel] = None
        self._thinking: Optional[ThinkingPanel] = None

        # State
        self.daemon_running = False
        self.quiet_mode = False
        self._engine = None
        self._current_turn_state = TurnState()

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header()

        # Status bar
        self._status_bar = Static(
            "Turn: 0 | Stance: neutral | Goal: witness",
            id="status-bar"
        )
        yield self._status_bar

        with Horizontal():
            # Left: Conversation panel
            with Vertical(id="conversation-panel"):
                self._chat_panel = ChatPanel()
                yield self._chat_panel

            # Right: State inspector
            self._state_inspector = StateInspector(id="state-inspector")
            yield self._state_inspector

            # Legacy sidebar (hidden by default)
            with Vertical(id="legacy-sidebar"):
                self._agency_status = AgencyStatus()
                yield self._agency_status
                self._modulators = ModulatorsPanel()
                yield self._modulators
                self._thinking = ThinkingPanel()
                yield self._thinking

        yield Footer()

    async def on_mount(self) -> None:
        """Handle app mount."""
        # Initialize and start engine
        self._engine = Engine()
        await self._engine.start()

        # Subscribe to events for real-time UI updates
        event_bus.subscribe(EventType.AGENCY_STARTED, self._handle_agency_started)
        event_bus.subscribe(EventType.AGENCY_COMPLETED, self._handle_agency_completed)
        event_bus.subscribe(EventType.AGENT_COMPLETED, self._handle_agent_completed)

        # Focus the chat input
        if self._chat_panel:
            self._chat_panel.focus_input()

        # Show welcome message
        self.show_system_message(
            "Welcome to Rilai v2. Type a message or use `/help` for commands."
        )

    @on(ChatInput.ChatSubmitted)
    async def on_chat_submitted(self, event: ChatInput.ChatSubmitted) -> None:
        """Handle chat input submission."""
        if event.is_command:
            await handle_command(self, event.value)
        else:
            await self.process_message(event.value)

    async def process_message(self, message: str) -> None:
        """Process a user message through the engine."""
        # Add user message to chat
        if self._chat_panel:
            self._chat_panel.add_message("user", message)

        # Show processing indicator
        self.show_system_message("Processing...")

        # Reset agency status
        if self._agency_status:
            self._agency_status.reset_all()

        try:
            # Process through the engine
            response = await self._engine.process_message(message)

            # Display response
            if self._chat_panel and response:
                self._chat_panel.add_message("assistant", response)

        except Exception as e:
            self.show_system_message(f"Error: {e}")

    async def _simulate_processing(self, message: str) -> None:
        """Simulate processing for demonstration."""
        import asyncio

        # Simulate agency processing
        if self._agency_status:
            for agency in ["planning", "emotion", "social"]:
                self._agency_status.set_running(agency)
                await asyncio.sleep(0.2)
                self._agency_status.set_completed(agency, time_ms=200, u_max=1)

        # Simulate response
        if self._chat_panel:
            self._chat_panel.add_message(
                "assistant",
                f"I received your message: '{message}'. The actual processing pipeline is being wired up.",
                urgency="low",
            )

    def show_system_message(self, content: str) -> None:
        """Show a system message in the chat."""
        if self._chat_panel:
            self._chat_panel.add_message("system", content)

    def clear_chat(self) -> None:
        """Clear the chat panel."""
        if self._chat_panel:
            self._chat_panel.clear_messages()

    # Panel toggles

    def toggle_inspector(self) -> None:
        """Toggle state inspector visibility."""
        inspector = self.query_one("#state-inspector", StateInspector)
        if inspector:
            inspector.display = not inspector.display

    def toggle_legacy(self) -> None:
        """Toggle legacy sidebar visibility."""
        sidebar = self.query_one("#legacy-sidebar")
        if sidebar:
            sidebar.toggle_class("visible")

    def toggle_quiet_mode(self) -> None:
        """Toggle quiet mode."""
        self.quiet_mode = not self.quiet_mode

    # Actions

    def action_toggle_inspector(self) -> None:
        """Toggle state inspector visibility."""
        self.toggle_inspector()

    def action_toggle_legacy(self) -> None:
        """Toggle legacy sidebar visibility."""
        self.toggle_legacy()

    def action_toggle_history(self) -> None:
        """Open history browser."""
        from rilai.tui.screens.history import HistoryScreen
        self.push_screen(HistoryScreen())

    def action_focus_input(self) -> None:
        """Focus the chat input."""
        if self._chat_panel:
            self._chat_panel.focus_input()

    # State inspector updates

    def update_turn_state(self, state: TurnState) -> None:
        """Update the state inspector with new turn state."""
        if self._state_inspector:
            self._state_inspector.update_turn_state(state)

        # Update status bar
        if self._status_bar:
            goal = state.workspace.get("goal", "witness") if state.workspace else "witness"
            stance_summary = "neutral"
            if state.stance:
                valence = state.stance.get("valence", 0)
                if valence > 0.3:
                    stance_summary = "positive"
                elif valence < -0.3:
                    stance_summary = "negative"
            self._status_bar.update(
                f"Turn: {state.turn_id} | Stance: {stance_summary} | Goal: {goal}"
            )

    # Event handlers for engine integration

    def on_agency_started(self, agency_id: str) -> None:
        """Handle agency started event."""
        if self._agency_status:
            self._agency_status.set_running(agency_id)

    def on_agency_completed(
        self, agency_id: str, time_ms: int, u_max: int
    ) -> None:
        """Handle agency completed event."""
        if self._agency_status:
            self._agency_status.set_completed(agency_id, time_ms, u_max)

    def on_modulators_updated(self, modulators: dict) -> None:
        """Handle modulators updated event."""
        if self._modulators:
            self._modulators.update_from_dict(modulators)

    def on_thinking_received(
        self, agent_id: str, thinking: str, voice: str = "", deliberation_round: int | None = None
    ) -> None:
        """Handle thinking received event."""
        if self._thinking:
            self._thinking.add_thinking(agent_id, thinking, voice, deliberation_round)

    def on_proactive_message(self, message: str, urgency: str) -> None:
        """Handle proactive message from daemon."""
        if not self.quiet_mode and self._chat_panel:
            self._chat_panel.add_message("assistant", message, urgency=urgency)

    def open_agent_detail(self, agent_id: str) -> None:
        """Open the agent detail screen for a specific agent."""
        from rilai.tui.screens.agent_detail import AgentDetailScreen
        self.push_screen(AgentDetailScreen(agent_id))

    # Async event bus handlers (wrap the sync methods above)

    async def _handle_agency_started(self, event: Event) -> None:
        """Handle AGENCY_STARTED event from event bus."""
        agency_id = event.data.get("agency_id", "")
        self.on_agency_started(agency_id)

    async def _handle_agency_completed(self, event: Event) -> None:
        """Handle AGENCY_COMPLETED event from event bus."""
        agency_id = event.data.get("agency_id", "")
        time_ms = event.data.get("time_ms", 0)
        u_max = event.data.get("u_max", 0)
        self.on_agency_completed(agency_id, time_ms, u_max)

    async def _handle_agent_completed(self, event: Event) -> None:
        """Handle AGENT_COMPLETED event from event bus."""
        agent_id = event.data.get("agent_id", "")
        thinking = event.data.get("thinking", "")
        voice = event.data.get("voice", "")
        deliberation_round = event.data.get("deliberation_round")
        if thinking or voice:
            self.on_thinking_received(agent_id, thinking, voice, deliberation_round)

    async def on_unmount(self) -> None:
        """Handle app unmount - cleanup engine."""
        if self._engine:
            await self._engine.stop()


def run():
    """Run the Rilai TUI."""
    app = RilaiApp()
    app.run()


if __name__ == "__main__":
    run()
