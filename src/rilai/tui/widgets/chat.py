"""Chat widget for Rilai TUI.

Provides:
- MessageLog: Scrolling message display
- ChatInput: Text input with slash command support
- ChatPanel: Container combining both
- NudgeMessage: Proactive nudge display with distinct styling
"""

from datetime import datetime
from typing import TYPE_CHECKING, Literal

from rich.markdown import Markdown
from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import ScrollableContainer, Vertical
from textual.message import Message
from textual.suggester import Suggester
from textual.widgets import Input, Static

if TYPE_CHECKING:
    from rilai.tui.app import RilaiApp

# Intervention level type for nudges
NudgeLevel = Literal["on_open", "nudge", "urgent"]


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


class NudgeMessage(Static):
    """A proactive nudge message with distinct styling.

    Nudges are displayed differently based on their intervention level:
    - L2 (on_open): Subtle, shown when TUI opens
    - L3 (nudge): Real-time inline nudge
    - L4 (urgent): Urgent interruption with warning styling
    """

    DEFAULT_CSS = """
    NudgeMessage {
        background: $surface-darken-1;
        border-left: thick $warning;
        padding: 1 2;
        margin: 1 0;
    }

    NudgeMessage.on_open {
        border-left: thick $primary;
        color: $text-muted;
    }

    NudgeMessage.nudge {
        border-left: thick $warning;
    }

    NudgeMessage.urgent {
        border-left: thick $error;
        background: $error 10%;
    }

    NudgeMessage .nudge-header {
        text-style: bold;
        margin-bottom: 0;
    }

    NudgeMessage .nudge-content {
        padding-left: 0;
    }

    NudgeMessage .nudge-meta {
        color: $text-muted;
        text-style: italic;
    }
    """

    def __init__(
        self,
        content: str,
        level: NudgeLevel = "nudge",
        timestamp: datetime | None = None,
        item_id: str | None = None,
    ):
        super().__init__()
        self.content = content
        self.level = level
        self.timestamp = timestamp or datetime.now()
        self.item_id = item_id
        self.add_class(level)

    def compose(self) -> ComposeResult:
        """Render the nudge message."""
        time_str = self.timestamp.strftime("%H:%M")

        # Level-specific header styling
        level_icons = {
            "on_open": "💭",
            "nudge": "💡",
            "urgent": "⚠️",
        }
        level_labels = {
            "on_open": "Thought",
            "nudge": "Nudge",
            "urgent": "Important",
        }

        icon = level_icons.get(self.level, "💡")
        label = level_labels.get(self.level, "Nudge")

        header = Text(f"{icon} {label}", style="bold")
        yield Static(header, classes="nudge-header")
        yield Static(Markdown(self.content), classes="nudge-content")
        yield Static(Text(f"[{time_str}]", style="dim"), classes="nudge-meta")


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

    def add_nudge(
        self,
        content: str,
        level: NudgeLevel = "nudge",
        timestamp: datetime | None = None,
        item_id: str | None = None,
    ) -> None:
        """Add a proactive nudge to the log.

        Args:
            content: Nudge message content
            level: Intervention level (on_open, nudge, urgent)
            timestamp: Optional timestamp
            item_id: Optional item ID for tracking
        """
        nudge = NudgeMessage(content, level, timestamp, item_id)
        self._messages.append(nudge)
        self.mount(nudge)
        self.scroll_end(animate=False)

    def clear_messages(self) -> None:
        """Clear all messages."""
        for msg in self._messages:
            msg.remove()
        self._messages.clear()


class SlashCommandSuggester(Suggester):
    """Suggester for slash commands."""

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

    async def get_suggestion(self, value: str) -> str | None:
        """Return a suggestion for the current input value."""
        if not value.startswith("/"):
            return None

        prefix = value[1:].lower()
        if not prefix:
            # Show first command when just "/" is typed
            return f"/{self.COMMANDS[0]}"

        for cmd in self.COMMANDS:
            if cmd.startswith(prefix) and cmd != prefix:
                return f"/{cmd}"

        return None


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

    def __init__(self, **kwargs):
        super().__init__(suggester=SlashCommandSuggester(case_sensitive=False), **kwargs)

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
        """Autocomplete slash commands (Tab accepts suggestion or shows matches)."""
        if not self.value.startswith("/"):
            return

        prefix = self.value[1:].lower()
        commands = SlashCommandSuggester.COMMANDS
        matches = [cmd for cmd in commands if cmd.startswith(prefix)]

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

    def add_nudge(
        self,
        content: str,
        level: NudgeLevel = "nudge",
        timestamp: datetime | None = None,
        item_id: str | None = None,
    ) -> None:
        """Add a proactive nudge to the log.

        Args:
            content: Nudge message content
            level: Intervention level (on_open, nudge, urgent)
            timestamp: Optional timestamp
            item_id: Optional item ID for tracking
        """
        if self.message_log:
            self.message_log.add_nudge(content, level, timestamp, item_id)

    def clear_messages(self) -> None:
        """Clear all messages."""
        if self.message_log:
            self.message_log.clear_messages()

    def focus_input(self) -> None:
        """Focus the chat input."""
        if self.chat_input:
            self.chat_input.focus()
