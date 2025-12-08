"""Chat panel widget."""

from textual.widgets import RichLog
from rich.text import Text


class ChatPanel(RichLog):
    """Chat panel showing conversation history."""

    def __init__(self, **kwargs):
        super().__init__(highlight=True, markup=True, **kwargs)

    def add_message(self, role: str, content: str) -> None:
        """Add a message to the chat."""
        if role == "user":
            prefix = Text("You: ", style="bold cyan")
        elif role == "assistant":
            prefix = Text("Rilai: ", style="bold green")
        else:
            prefix = Text("System: ", style="dim")

        self.write(prefix)
        self.write(content)
        self.write("")  # Blank line

    def clear_messages(self) -> None:
        """Clear all messages."""
        self.clear()
