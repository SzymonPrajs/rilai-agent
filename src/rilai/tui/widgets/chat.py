"""Chat widget for Rilai TUI.

Provides:
- MessageLog: Scrolling message display
- ChatInput: Text input with slash command support
- ChatPanel: Container combining both
"""

from datetime import datetime
from typing import TYPE_CHECKING

from rich.markdown import Markdown
from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import ScrollableContainer, Vertical
from textual.message import Message
from textual.widgets import Input, Static

if TYPE_CHECKING:
    from rilai.tui.app import RilaiApp


class ChatMessage(Static):
    """A single chat message."""

    def __init__(
        self,
        role: str,
        content: str,
        timestamp: datetime | None = None,
        urgency: str | None = None,
    ):
        super().__init__()
        self.role = role
        self.content = content
        self.timestamp = timestamp or datetime.now()
        self.urgency = urgency

    def compose(self) -> ComposeResult:
        """Render the message."""
        time_str = self.timestamp.strftime("%H:%M")

        if self.role == "user":
            header = Text(f"[{time_str}] You: ", style="bold cyan")
        elif self.role == "assistant":
            urgency_style = {
                "critical": "bold red",
                "high": "red",
                "medium": "yellow",
                "low": "green",
            }.get(self.urgency, "green")
            header = Text(f"[{time_str}] Rilai: ", style=f"bold {urgency_style}")
        elif self.role == "system":
            header = Text(f"[{time_str}] System: ", style="dim")
        else:
            header = Text(f"[{time_str}] {self.role}: ", style="bold")

        yield Static(header, classes="message-header")
        yield Static(Markdown(self.content), classes="message-content")


class MessageLog(ScrollableContainer):
    """Scrollable container for chat messages."""

    DEFAULT_CSS = """
    MessageLog {
        height: 1fr;
        scrollbar-size: 1 1;
        background: $surface;
        padding: 1;
    }

    MessageLog ChatMessage {
        margin-bottom: 1;
    }

    MessageLog .message-header {
        margin-bottom: 0;
    }

    MessageLog .message-content {
        padding-left: 2;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._messages: list[ChatMessage] = []

    def add_message(
        self,
        role: str,
        content: str,
        timestamp: datetime | None = None,
        urgency: str | None = None,
    ) -> None:
        """Add a message to the log."""
        msg = ChatMessage(role, content, timestamp, urgency)
        self._messages.append(msg)
        self.mount(msg)
        self.scroll_end(animate=False)

    def clear_messages(self) -> None:
        """Clear all messages."""
        for msg in self._messages:
            msg.remove()
        self._messages.clear()


class ChatInput(Input):
    """Chat input with slash command autocomplete."""

    DEFAULT_CSS = """
    ChatInput {
        dock: bottom;
        margin: 0 1;
    }
    """

    BINDINGS = [
        ("tab", "autocomplete", "Autocomplete"),
    ]

    # Available slash commands
    COMMANDS = [
        "help",
        "clear",
        "status",
        "query",
        "export",
        "agencies",
        "thinking",
        "history",
        "daemon",
        "config",
        "quiet",
    ]

    class ChatSubmitted(Message):
        """Message sent when chat input is submitted."""

        def __init__(self, value: str, is_command: bool = False):
            self.value = value
            self.is_command = is_command
            super().__init__()

    @on(Input.Submitted)
    def on_submit(self, event: Input.Submitted) -> None:
        """Handle input submission."""
        value = event.value.strip()
        if not value:
            return

        is_command = value.startswith("/")
        self.post_message(self.ChatSubmitted(value, is_command))
        self.value = ""

    def action_autocomplete(self) -> None:
        """Autocomplete slash commands."""
        if not self.value.startswith("/"):
            return

        prefix = self.value[1:].lower()
        matches = [cmd for cmd in self.COMMANDS if cmd.startswith(prefix)]

        if len(matches) == 1:
            self.value = f"/{matches[0]} "
            self.cursor_position = len(self.value)
        elif matches:
            self.app.notify(f"Commands: {', '.join(matches)}")


class ChatPanel(Vertical):
    """Chat panel combining message log and input."""

    DEFAULT_CSS = """
    ChatPanel {
        height: 100%;
        border: solid $primary;
        padding: 0;
    }

    ChatPanel > Static.panel-title {
        dock: top;
        height: 1;
        background: $primary;
        color: $text;
        text-style: bold;
        padding: 0 1;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.message_log: MessageLog | None = None
        self.chat_input: ChatInput | None = None

    def compose(self) -> ComposeResult:
        """Create chat panel components."""
        yield Static("Chat", classes="panel-title")
        self.message_log = MessageLog()
        yield self.message_log
        self.chat_input = ChatInput(placeholder="Type a message... (/ for commands)")
        yield self.chat_input

    def add_message(
        self,
        role: str,
        content: str,
        timestamp: datetime | None = None,
        urgency: str | None = None,
    ) -> None:
        """Add a message to the log."""
        if self.message_log:
            self.message_log.add_message(role, content, timestamp, urgency)

    def clear_messages(self) -> None:
        """Clear all messages."""
        if self.message_log:
            self.message_log.clear_messages()

    def focus_input(self) -> None:
        """Focus the chat input."""
        if self.chat_input:
            self.chat_input.focus()
