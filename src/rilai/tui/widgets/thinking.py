"""Thinking display widget for Rilai TUI.

Shows agent reasoning and thinking steps.
"""

from rich.markdown import Markdown
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import ScrollableContainer, Vertical
from textual.widgets import Static


class ThinkingEntry(Static):
    """A single thinking entry."""

    def __init__(self, agent_id: str, thinking: str, **kwargs):
        super().__init__(**kwargs)
        self.agent_id = agent_id
        self.thinking = thinking

    def compose(self) -> ComposeResult:
        """Render the thinking entry."""
        # Format agent name
        if "." in self.agent_id:
            agency, agent = self.agent_id.split(".", 1)
            header = f"{agency}/{agent}"
        else:
            header = self.agent_id

        yield Static(Text(f"▸ {header}", style="bold cyan"), classes="thinking-header")

        # Truncate long thinking
        content = self.thinking
        if len(content) > 500:
            content = content[:500] + "..."

        yield Static(content, classes="thinking-content")


class ThinkingLog(ScrollableContainer):
    """Scrollable container for thinking entries."""

    DEFAULT_CSS = """
    ThinkingLog {
        height: 1fr;
        scrollbar-size: 1 1;
        background: $surface;
        padding: 1;
    }

    ThinkingLog ThinkingEntry {
        margin-bottom: 1;
    }

    ThinkingLog .thinking-header {
        margin-bottom: 0;
    }

    ThinkingLog .thinking-content {
        padding-left: 2;
        color: $text-muted;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._entries: list[ThinkingEntry] = []

    def add_entry(self, agent_id: str, thinking: str) -> None:
        """Add a thinking entry."""
        entry = ThinkingEntry(agent_id, thinking)
        self._entries.append(entry)

        # Keep only last 20 entries
        while len(self._entries) > 20:
            old = self._entries.pop(0)
            old.remove()

        self.mount(entry)
        self.scroll_end(animate=False)

    def clear_entries(self) -> None:
        """Clear all entries."""
        for entry in self._entries:
            entry.remove()
        self._entries.clear()


class ThinkingPanel(Vertical):
    """Panel displaying agent thinking/reasoning."""

    DEFAULT_CSS = """
    ThinkingPanel {
        height: auto;
        min-height: 5;
        max-height: 15;
        border: solid $primary;
        padding: 0;
    }

    ThinkingPanel > Static.panel-title {
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
        self._log: ThinkingLog | None = None
        self._expanded = True
        self._last_agent: str | None = None
        self._last_thinking: str | None = None

    def compose(self) -> ComposeResult:
        """Create thinking panel components."""
        yield Static("▼ Agent Thinking", classes="panel-title", id="thinking-title")
        self._log = ThinkingLog()
        yield self._log

    def add_thinking(self, agent_id: str, thinking: str) -> None:
        """Add a thinking entry."""
        if self._log:
            self._log.add_entry(agent_id, thinking)
            self._last_agent = agent_id
            self._last_thinking = thinking

    def set_last_thinking(self, agent_id: str, thinking: str) -> None:
        """Set the last agent's thinking (for quick display)."""
        self._last_agent = agent_id
        self._last_thinking = thinking

    def clear(self) -> None:
        """Clear all thinking entries."""
        if self._log:
            self._log.clear_entries()

    def toggle(self) -> None:
        """Toggle panel expansion."""
        self._expanded = not self._expanded
        title = self.query_one("#thinking-title", Static)

        if self._expanded:
            title.update("▼ Agent Thinking")
            if self._log:
                self._log.display = True
        else:
            title.update("▶ Agent Thinking")
            if self._log:
                self._log.display = False
