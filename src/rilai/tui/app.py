"""Main Rilai TUI application."""

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from textual import on
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Static

from .commands import handle_command
from .widgets import AgencyStatus, ChatInput, ChatPanel, ModulatorsPanel, ThinkingPanel


class RilaiApp(App):
    """Rilai v2 Terminal User Interface."""

    TITLE = "Rilai v2"
    SUB_TITLE = "Cognitive Architecture"

    CSS = """
    Screen {
        layout: horizontal;
    }

    #main-area {
        width: 3fr;
        height: 100%;
    }

    #sidebar {
        width: 1fr;
        min-width: 30;
        max-width: 40;
        height: 100%;
        padding: 0;
    }

    ChatPanel {
        height: 100%;
    }

    AgencyStatus {
        height: auto;
        max-height: 15;
    }

    ModulatorsPanel {
        height: auto;
    }

    ThinkingPanel {
        height: 1fr;
    }

    #daemon-status {
        dock: top;
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
        text-align: right;
    }
    """

    BINDINGS = [
        ("ctrl+d", "quit", "Quit"),
        ("ctrl+a", "toggle_agencies", "Agencies"),
        ("ctrl+t", "toggle_thinking", "Thinking"),
        ("ctrl+h", "toggle_history", "History"),
        ("escape", "focus_input", "Focus Input"),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._chat_panel: ChatPanel | None = None
        self._agency_status: AgencyStatus | None = None
        self._modulators: ModulatorsPanel | None = None
        self._thinking: ThinkingPanel | None = None
        self._daemon_status: Static | None = None

        # State
        self.daemon_running = False
        self.quiet_mode = False
        self._scheduler = None
        self._engine = None

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header()

        with Horizontal():
            # Main chat area
            with Vertical(id="main-area"):
                self._chat_panel = ChatPanel()
                yield self._chat_panel

            # Sidebar
            with Vertical(id="sidebar"):
                self._daemon_status = Static(
                    "[Daemon: ○]", id="daemon-status"
                )
                yield self._daemon_status

                self._agency_status = AgencyStatus()
                yield self._agency_status

                self._modulators = ModulatorsPanel()
                yield self._modulators

                self._thinking = ThinkingPanel()
                yield self._thinking

        yield Footer()

    def on_mount(self) -> None:
        """Handle app mount."""
        # Focus the chat input
        if self._chat_panel:
            self._chat_panel.focus_input()

        # Show welcome message
        self.show_system_message(
            "Welcome to Rilai v2. Type a message or use `/help` for commands."
        )

    @on(ChatInput.Submitted)
    async def on_chat_submitted(self, event: ChatInput.Submitted) -> None:
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
            # TODO: Wire up to actual engine
            # For now, just echo back
            await self._simulate_processing(message)

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

    def toggle_agencies(self) -> None:
        """Toggle agency panel."""
        if self._agency_status:
            self._agency_status.toggle()

    def toggle_thinking(self) -> None:
        """Toggle thinking panel."""
        if self._thinking:
            self._thinking.toggle()

    def toggle_quiet_mode(self) -> None:
        """Toggle quiet mode."""
        self.quiet_mode = not self.quiet_mode

    # Actions

    def action_toggle_agencies(self) -> None:
        """Toggle agency status panel visibility."""
        self.toggle_agencies()

    def action_toggle_thinking(self) -> None:
        """Toggle thinking panel visibility."""
        self.toggle_thinking()

    def action_toggle_history(self) -> None:
        """Open history browser."""
        self.notify("History browser - coming soon")

    def action_focus_input(self) -> None:
        """Focus the chat input."""
        if self._chat_panel:
            self._chat_panel.focus_input()

    # Daemon control

    async def start_daemon(self) -> None:
        """Start the background daemon."""
        # TODO: Wire up actual scheduler
        self.daemon_running = True
        if self._daemon_status:
            self._daemon_status.update("[Daemon: ●]")

    async def stop_daemon(self) -> None:
        """Stop the background daemon."""
        # TODO: Wire up actual scheduler
        self.daemon_running = False
        if self._daemon_status:
            self._daemon_status.update("[Daemon: ○]")

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

    def on_thinking_received(self, agent_id: str, thinking: str) -> None:
        """Handle thinking received event."""
        if self._thinking:
            self._thinking.add_thinking(agent_id, thinking)

    def on_proactive_message(self, message: str, urgency: str) -> None:
        """Handle proactive message from daemon."""
        if not self.quiet_mode and self._chat_panel:
            self._chat_panel.add_message("assistant", message, urgency=urgency)


def run():
    """Run the Rilai TUI."""
    app = RilaiApp()
    app.run()


if __name__ == "__main__":
    run()
