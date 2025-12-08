"""Rilai v3 TUI Application - Event-driven terminal interface."""

import asyncio
import uuid
from pathlib import Path
from typing import Callable

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Header, Footer, Input, TabbedContent, TabPane, Static

from rilai.ui.projection import TurnStateProjection, UIUpdate
from rilai.ui.panels import (
    ChatPanel,
    SensorsPanel,
    StancePanel,
    AgentsPanel,
    ActivityPanel,
    CriticsPanel,
)
from rilai.contracts.events import EngineEvent
from rilai.store import EventLogWriter
from rilai.runtime import TurnRunner, Workspace, Scheduler


class RilaiApp(App):
    """Rilai v3 TUI Application.

    Event-driven architecture:
    1. User input triggers TurnRunner.run_turn()
    2. TurnRunner yields EngineEvents
    3. TurnStateProjection converts events to UIUpdates
    4. App applies UIUpdates to widgets
    """

    CSS = """
    #main-container {
        layout: horizontal;
    }

    #chat-container {
        width: 60%;
        height: 100%;
        border: solid green;
    }

    #inspector-container {
        width: 40%;
        height: 100%;
    }

    #chat-panel {
        height: 1fr;
    }

    #input-container {
        height: auto;
        padding: 0 1;
    }

    #user-input {
        width: 100%;
    }

    #activity-bar {
        height: 3;
        padding: 0 1;
        background: $surface;
    }

    .panel-title {
        text-style: bold;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit"),
        Binding("ctrl+l", "clear", "Clear"),
        Binding("ctrl+d", "quit", "Quit"),
    ]

    def __init__(
        self,
        db_path: Path | str | None = None,
        on_nudge: Callable[[dict], None] | None = None,
    ):
        """Initialize the Rilai TUI.

        Args:
            db_path: Path to SQLite database for event log
            on_nudge: Callback for proactive nudges
        """
        super().__init__()

        # Default paths
        if db_path is None:
            db_path = Path("data/events.db")

        # Initialize v3 components
        self.event_log = EventLogWriter(db_path)
        self.workspace = Workspace()
        self.scheduler = Scheduler()
        self.turn_runner = TurnRunner(
            event_log=self.event_log,
            workspace=self.workspace,
            scheduler=self.scheduler,
        )

        # Session management
        self.session_id = str(uuid.uuid4())[:8]
        self.turn_runner.set_session(self.session_id)

        # UI state projection
        self.projection = TurnStateProjection()

        # Processing state
        self._processing = False

        # Nudge callback
        self._on_nudge = on_nudge

        # Daemon reference (set in on_mount)
        self._daemon = None

    def compose(self) -> ComposeResult:
        """Compose the application layout."""
        yield Header()

        with Horizontal(id="main-container"):
            # Left: Chat panel
            with Vertical(id="chat-container"):
                yield ChatPanel(id="chat-panel")
                yield ActivityPanel(id="activity-bar")
                with Container(id="input-container"):
                    yield Input(placeholder="Type a message... (/help for commands)", id="user-input")

            # Right: Inspector panels
            with Vertical(id="inspector-container"):
                with TabbedContent(initial="sensors"):
                    with TabPane("Sensors", id="sensors"):
                        yield SensorsPanel(id="sensors-panel")
                    with TabPane("Stance", id="stance"):
                        yield StancePanel(id="stance-panel")
                    with TabPane("Agents", id="agents"):
                        yield AgentsPanel(id="agents-panel")
                    with TabPane("Critics", id="critics"):
                        yield CriticsPanel(id="critics-panel")

        yield Footer()

    async def on_mount(self) -> None:
        """Start daemon when app mounts."""
        # Focus input
        self.query_one("#user-input", Input).focus()

        # Start daemon if available
        try:
            from rilai.daemon import BrainDaemon

            self._daemon = BrainDaemon(
                workspace=self.workspace,
                tick_interval=30.0,
                nudge_callback=self._handle_nudge,
            )
            await self._daemon.start()
            self.log.info("Brain daemon started")
        except ImportError:
            self.log.warning("Brain daemon not available")
        except Exception as e:
            self.log.error(f"Failed to start daemon: {e}")

    async def on_unmount(self) -> None:
        """Stop daemon when app unmounts."""
        if self._daemon:
            await self._daemon.stop()
            self.log.info("Brain daemon stopped")

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle user input submission."""
        user_input = event.value.strip()
        if not user_input:
            return

        # Clear input
        event.input.value = ""

        # Handle slash commands
        if user_input.startswith("/"):
            await self._handle_command(user_input)
            return

        # Run turn
        await self._run_turn(user_input)

    async def _run_turn(self, user_input: str) -> None:
        """Execute a turn and stream events to UI."""
        if self._processing:
            self.notify("Still processing previous message...")
            return

        self._processing = True

        try:
            # Reset projection for new turn
            self.projection.reset_for_turn()

            # Stream events from turn runner
            async for event in self.turn_runner.run_turn(user_input):
                await self._apply_event(event)

        except Exception as e:
            self.log.error(f"Turn error: {e}")
            self.notify(f"Error: {e}", severity="error")

        finally:
            self._processing = False

    async def _apply_event(self, event: EngineEvent) -> None:
        """Apply engine event to UI via projection."""
        updates = self.projection.apply_event(event)

        for update in updates:
            await self._apply_update(update)

    async def _apply_update(self, update: UIUpdate) -> None:
        """Apply a single UI update to widgets."""
        match update.kind:
            case "chat":
                chat = self.query_one("#chat-panel", ChatPanel)
                role = update.payload.get("role", "system")
                content = update.payload.get("content", "")
                chat.add_message(role, content)

            case "sensors":
                panel = self.query_one("#sensors-panel", SensorsPanel)
                sensors = update.payload.get("sensors", {})
                panel.update_sensors(sensors)

            case "stance":
                panel = self.query_one("#stance-panel", StancePanel)
                stance = update.payload.get("stance", {})
                changes = update.payload.get("changes", {})
                panel.update_stance(stance, changes)

            case "agents":
                panel = self.query_one("#agents-panel", AgentsPanel)
                if "started" in update.payload:
                    panel.agent_started(update.payload["started"])
                elif "completed" in update.payload:
                    panel.agent_completed(update.payload["completed"])
                elif "failed" in update.payload:
                    panel.agent_failed(
                        update.payload["failed"],
                        update.payload.get("error", ""),
                    )

            case "critics":
                panel = self.query_one("#critics-panel", CriticsPanel)
                results = update.payload.get("results", [])
                passed = update.payload.get("passed", True)
                panel.update_results(results, passed)

            case "activity":
                panel = self.query_one("#activity-bar", ActivityPanel)
                panel.update_state(update.payload)

    async def _handle_command(self, command: str) -> None:
        """Handle slash commands."""
        parts = command.split()
        cmd = parts[0].lower()
        args = parts[1:]

        chat = self.query_one("#chat-panel", ChatPanel)

        match cmd:
            case "/help":
                chat.add_message("system", self._help_text())

            case "/clear":
                chat.clear_messages()
                self.projection.messages.clear()
                self.notify("Chat cleared")

            case "/status":
                status = self._get_status()
                chat.add_message("system", status)

            case "/session":
                chat.add_message("system", f"Session ID: {self.session_id}")

            case "/reset":
                self.workspace.reset()
                self.projection.reset_for_turn()
                chat.add_message("system", "Workspace reset")

            case _:
                chat.add_message("system", f"Unknown command: {cmd}. Type /help for help.")

    def _help_text(self) -> str:
        """Generate help text."""
        return """Commands:
/help   - Show this help
/clear  - Clear chat history
/status - Show system status
/session - Show session ID
/reset  - Reset workspace state

Keyboard shortcuts:
Ctrl+C or Ctrl+D - Quit
Ctrl+L - Clear chat"""

    def _get_status(self) -> str:
        """Generate status text."""
        lines = [
            f"Session: {self.session_id}",
            f"Turn: {self.turn_runner.turn_id}",
            f"Processing: {self._processing}",
            f"Daemon: {'running' if self._daemon and self._daemon._running else 'stopped'}",
            f"Sensors: {len(self.projection.sensors)} active",
            f"Messages: {len(self.projection.messages)}",
        ]
        return "\n".join(lines)

    async def _handle_nudge(self, nudge: dict) -> None:
        """Handle proactive nudge from daemon."""
        reason = nudge.get("reason", "unknown")
        suggestion = nudge.get("suggestion", "")

        chat = self.query_one("#chat-panel", ChatPanel)
        chat.add_message("system", f"[Nudge: {reason}] {suggestion}")

        if self._on_nudge:
            self._on_nudge(nudge)

    def action_clear(self) -> None:
        """Clear action for key binding."""
        chat = self.query_one("#chat-panel", ChatPanel)
        chat.clear_messages()

    def action_quit(self) -> None:
        """Quit action for key binding."""
        self.exit()


def create_app(db_path: Path | str | None = None) -> RilaiApp:
    """Factory function to create the app.

    Args:
        db_path: Optional path to database

    Returns:
        Configured RilaiApp instance
    """
    return RilaiApp(db_path=db_path)
