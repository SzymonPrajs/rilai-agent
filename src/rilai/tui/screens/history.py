"""History browser screen for Rilai TUI.

Shows conversation history with ability to inspect individual turns
and their associated agent assessments.
"""

from datetime import datetime

from rich.markdown import Markdown
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import ScrollableContainer, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from rilai.observability import get_store


class HistoryMessage(Static):
    """A single message in the history view."""

    DEFAULT_CSS = """
    HistoryMessage {
        margin-bottom: 1;
        padding-bottom: 1;
        border-bottom: dashed $surface-lighten-2;
    }

    HistoryMessage .msg-header {
        margin-bottom: 0;
    }

    HistoryMessage .msg-content {
        padding-left: 2;
    }
    """

    def __init__(
        self,
        role: str,
        content: str,
        timestamp: str | None = None,
        urgency: str | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.role = role
        self.message_content = content
        self.timestamp = timestamp
        self.urgency = urgency

    def compose(self) -> ComposeResult:
        """Render the history message."""
        # Parse timestamp
        time_str = ""
        if self.timestamp:
            try:
                dt = datetime.fromisoformat(self.timestamp)
                time_str = dt.strftime("%Y-%m-%d %H:%M")
            except (ValueError, TypeError):
                time_str = self.timestamp[:16] if len(self.timestamp) >= 16 else self.timestamp

        # Style based on role
        if self.role == "user":
            header_style = "bold cyan"
            role_display = "You"
        elif self.role == "assistant":
            urgency_colors = {
                "critical": "bold red",
                "high": "red",
                "medium": "yellow",
                "low": "green",
            }
            header_style = f"bold {urgency_colors.get(self.urgency, 'green')}"
            role_display = "Rilai"
        elif self.role == "system":
            header_style = "dim"
            role_display = "System"
        else:
            header_style = "bold"
            role_display = self.role.capitalize()

        header = Text()
        header.append(f"[{time_str}] ", style="dim")
        header.append(f"{role_display}", style=header_style)
        if self.urgency and self.role == "assistant":
            header.append(f" [{self.urgency}]", style="dim")

        yield Static(header, classes="msg-header")
        yield Static(Markdown(self.message_content), classes="msg-content")


class HistoryLog(ScrollableContainer):
    """Scrollable container for history messages."""

    DEFAULT_CSS = """
    HistoryLog {
        height: 1fr;
        scrollbar-size: 1 1;
        background: $surface;
        padding: 1;
    }
    """


class HistoryStats(Static):
    """Statistics panel for history."""

    DEFAULT_CSS = """
    HistoryStats {
        height: auto;
        padding: 1;
        background: $surface-darken-1;
        border-bottom: solid $primary;
    }
    """

    def __init__(self, stats: dict, **kwargs):
        super().__init__(**kwargs)
        self.stats = stats

    def render(self) -> Text:
        """Render the stats."""
        text = Text()
        text.append("Session Statistics\n", style="bold")

        msg_count = self.stats.get("message_count", 0)
        turns = self.stats.get("turns", 0)
        agent_calls = self.stats.get("agent_calls", 0)
        avg_time = self.stats.get("avg_turn_time_ms", 0)

        text.append(f"Messages: {msg_count}  ", style="cyan")
        text.append(f"Turns: {turns}  ", style="cyan")
        text.append(f"Agent Calls: {agent_calls}  ", style="cyan")
        text.append(f"Avg Turn: {avg_time:.0f}ms", style="cyan")

        return text


class ConfirmScreen(Screen):
    """Simple confirmation screen."""

    BINDINGS = [
        Binding("y", "confirm", "Yes"),
        Binding("n", "cancel", "No"),
        Binding("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = """
    ConfirmScreen {
        align: center middle;
    }

    ConfirmScreen > Vertical {
        width: 50;
        height: auto;
        border: solid $error;
        background: $surface;
        padding: 1 2;
    }

    ConfirmScreen .confirm-message {
        text-align: center;
        margin-bottom: 1;
    }

    ConfirmScreen .confirm-hint {
        text-align: center;
        color: $text-muted;
    }
    """

    def __init__(self, message: str, callback, **kwargs):
        super().__init__(**kwargs)
        self.message = message
        self.callback = callback

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self.message, classes="confirm-message")
            yield Static("[Y]es / [N]o", classes="confirm-hint")

    def action_confirm(self) -> None:
        """Confirm the action."""
        self.app.pop_screen()
        self.callback(True)

    def action_cancel(self) -> None:
        """Cancel the action."""
        self.app.pop_screen()
        self.callback(False)


class HistoryScreen(Screen):
    """Screen for browsing conversation history."""

    BINDINGS = [
        Binding("escape", "dismiss", "Back"),
        Binding("q", "dismiss", "Back"),
        Binding("r", "refresh", "Refresh"),
        Binding("c", "clear_history", "Clear"),
        Binding("e", "export", "Export"),
        Binding("home", "scroll_top", "Top"),
        Binding("end", "scroll_bottom", "Bottom"),
    ]

    DEFAULT_CSS = """
    HistoryScreen {
        align: center middle;
    }

    HistoryScreen > Vertical {
        width: 90%;
        height: 90%;
        border: solid $primary;
        background: $surface;
    }

    HistoryScreen .screen-title {
        dock: top;
        height: 1;
        background: $primary;
        color: $text;
        text-style: bold;
        padding: 0 1;
    }

    HistoryScreen .empty-message {
        padding: 2;
        text-align: center;
        color: $text-muted;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._history_log: HistoryLog | None = None
        self._stats_panel: HistoryStats | None = None

    def compose(self) -> ComposeResult:
        """Create the history browser view."""
        yield Header()

        with Vertical():
            yield Static("Conversation History", classes="screen-title")

            # Stats panel
            stats = self._get_stats()
            self._stats_panel = HistoryStats(stats)
            yield self._stats_panel

            # History log
            self._history_log = HistoryLog()
            yield self._history_log

        yield Footer()

    def on_mount(self) -> None:
        """Load history when screen is mounted."""
        self._load_history()

    def _get_stats(self) -> dict:
        """Get session statistics."""
        store = get_store()
        stats = store.get_stats(24)
        history = store.get_conversation_history(limit=1000)
        stats["message_count"] = len(history)
        return stats

    def _load_history(self, limit: int = 100) -> None:
        """Load conversation history from the store."""
        store = get_store()
        history = store.get_conversation_history(limit=limit)

        if not history:
            if self._history_log:
                self._history_log.mount(
                    Static(
                        "No conversation history found.\nStart chatting to see messages here.",
                        classes="empty-message",
                    )
                )
            return

        # Reverse to show oldest first (chronological order)
        history = list(reversed(history))

        if self._history_log:
            for msg in history:
                item = HistoryMessage(
                    role=msg.get("role", "unknown"),
                    content=msg.get("content", ""),
                    timestamp=msg.get("timestamp"),
                    urgency=msg.get("urgency"),
                )
                self._history_log.mount(item)

            # Scroll to bottom (most recent)
            self._history_log.scroll_end(animate=False)

    def _clear_log(self) -> None:
        """Clear the history log widget."""
        if self._history_log:
            for child in list(self._history_log.children):
                child.remove()

    def action_refresh(self) -> None:
        """Refresh the history."""
        self._clear_log()
        self._load_history()

        # Update stats
        if self._stats_panel:
            stats = self._get_stats()
            self._stats_panel.stats = stats
            self._stats_panel.refresh()

        self.notify("History refreshed")

    def action_clear_history(self) -> None:
        """Clear conversation history (with confirmation)."""

        def confirm_clear(confirmed: bool) -> None:
            if confirmed:
                store = get_store()
                store.clear_current()
                self._clear_log()
                self._load_history()
                self.notify("History cleared")

        self.app.push_screen(
            ConfirmScreen("Clear all conversation history?", confirm_clear)
        )

    def action_export(self) -> None:
        """Export history to markdown."""
        store = get_store()
        content = store.export_markdown()
        if content:
            self.notify(f"Exported {len(content)} characters to markdown")
        else:
            self.notify("No history to export", severity="warning")

    def action_scroll_top(self) -> None:
        """Scroll to top of history."""
        if self._history_log:
            self._history_log.scroll_home(animate=True)

    def action_scroll_bottom(self) -> None:
        """Scroll to bottom of history."""
        if self._history_log:
            self._history_log.scroll_end(animate=True)

    def action_dismiss(self) -> None:
        """Close the screen."""
        self.app.pop_screen()
