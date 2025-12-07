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

    def __init__(
        self,
        agent_id: str,
        thinking: str,
        voice: str = "",
        deliberation_round: int | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.agent_id = agent_id
        self.thinking = thinking
        self.voice = voice
        self.deliberation_round = deliberation_round

    def compose(self) -> ComposeResult:
        """Render the thinking entry."""
        # Format agent name
        if "." in self.agent_id:
            agency, agent = self.agent_id.split(".", 1)
            header = f"{agency}/{agent}"
        else:
            header = self.agent_id

        # Add round indicator if in deliberation
        if self.deliberation_round is not None:
            header = f"[R{self.deliberation_round}] {header}"

        yield Static(Text(f"▸ {header}", style="bold cyan"), classes="thinking-header")

        # Show voice (what the agent said) - this is the important part
        if self.voice:
            voice_content = self.voice
            if len(voice_content) > 300:
                voice_content = voice_content[:300] + "..."
            yield Static(voice_content, classes="thinking-voice")

        # Truncate long thinking
        if self.thinking:
            content = self.thinking
            if len(content) > 500:
                content = content[:500] + "..."
            yield Static(
                Text(f"💭 {content}", style="dim"), classes="thinking-content"
            )


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

    ThinkingLog .thinking-voice {
        padding-left: 2;
        color: $text;
    }

    ThinkingLog .thinking-content {
        padding-left: 2;
        color: $text-muted;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._entries: list[ThinkingEntry] = []

    def add_entry(
        self,
        agent_id: str,
        thinking: str,
        voice: str = "",
        deliberation_round: int | None = None,
    ) -> None:
        """Add a thinking entry."""
        entry = ThinkingEntry(agent_id, thinking, voice, deliberation_round)
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

    def add_thinking(
        self,
        agent_id: str,
        thinking: str,
        voice: str = "",
        deliberation_round: int | None = None,
    ) -> None:
        """Add a thinking entry."""
        if self._log:
            self._log.add_entry(agent_id, thinking, voice, deliberation_round)
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
