"""Agent detail screen for Rilai TUI.

Shows detailed information about a specific agent including
recent calls, prompt content, and statistics.
"""

from rich.markdown import Markdown
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import ScrollableContainer, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Static


class AgentCallItem(Static):
    """Display for a single agent call."""

    DEFAULT_CSS = """
    AgentCallItem {
        margin-bottom: 1;
    }

    AgentCallItem .call-header {
        margin-bottom: 0;
    }

    AgentCallItem .call-output {
        padding-left: 2;
        color: $text-muted;
    }
    """

    def __init__(self, call_data: dict, **kwargs):
        super().__init__(**kwargs)
        self.call_data = call_data

    def compose(self) -> ComposeResult:
        """Render the agent call."""
        time_str = self.call_data.get("created_at", "")[:19]
        urgency = self.call_data.get("urgency", 0)
        confidence = self.call_data.get("confidence", 0)
        time_ms = self.call_data.get("time_ms", 0)
        output = self.call_data.get("output", "")[:150]

        # Header with metadata
        header = Text()
        header.append(f"[{time_str}] ", style="dim")
        header.append(f"U:{urgency} C:{confidence} ", style="cyan")
        header.append(f"({time_ms}ms)", style="dim")

        yield Static(header, classes="call-header")
        yield Static(output, classes="call-output")


class AgentCallLog(ScrollableContainer):
    """Scrollable container for agent call history."""

    DEFAULT_CSS = """
    AgentCallLog {
        height: 1fr;
        scrollbar-size: 1 1;
        background: $surface;
        padding: 1;
    }
    """


class AgentDetailScreen(Screen):
    """Screen showing detailed agent information."""

    BINDINGS = [
        Binding("escape", "dismiss", "Back"),
        Binding("q", "dismiss", "Back"),
        Binding("r", "refresh", "Refresh"),
    ]

    DEFAULT_CSS = """
    AgentDetailScreen {
        align: center middle;
    }

    AgentDetailScreen > Vertical {
        width: 90%;
        height: 90%;
        border: solid $primary;
        background: $surface;
    }

    AgentDetailScreen .screen-title {
        dock: top;
        height: 1;
        background: $primary;
        color: $text;
        text-style: bold;
        padding: 0 1;
    }

    AgentDetailScreen .section-title {
        background: $surface-darken-1;
        padding: 0 1;
        margin-top: 1;
        text-style: bold;
    }

    AgentDetailScreen .agent-meta {
        padding: 0 1;
    }

    AgentDetailScreen .agent-prompt {
        padding: 1;
        background: $surface-darken-1;
        max-height: 15;
        overflow: auto;
    }
    """

    def __init__(self, agent_id: str, **kwargs):
        super().__init__(**kwargs)
        self.agent_id = agent_id
        self._call_log: AgentCallLog | None = None

        # Parse agent info
        parts = agent_id.split(".", 1)
        self.agency_id = parts[0] if parts else ""
        self.agent_name = parts[1] if len(parts) > 1 else agent_id

    def compose(self) -> ComposeResult:
        """Create the agent detail view."""
        yield Header()

        with Vertical():
            yield Static(f"Agent: {self.agent_id}", classes="screen-title")

            # Agent metadata section
            yield Static("Metadata", classes="section-title")
            meta_content = self._build_metadata()
            yield Static(meta_content, classes="agent-meta")

            # Prompt section
            yield Static("System Prompt", classes="section-title")
            prompt_content = self._load_prompt()
            truncated = prompt_content[:2000] + ("..." if len(prompt_content) > 2000 else "")
            yield Static(
                Markdown(truncated),
                classes="agent-prompt",
            )

            # Recent calls section
            yield Static("Recent Calls", classes="section-title")
            self._call_log = AgentCallLog()
            yield self._call_log

        yield Footer()

    def on_mount(self) -> None:
        """Load data when screen is mounted."""
        self._load_calls()

    def _build_metadata(self) -> Text:
        """Build agent metadata display."""
        from rilai.agencies.registry import AGENCY_CONFIGS

        text = Text()

        # Get agency config
        agency_config = AGENCY_CONFIGS.get(self.agency_id)
        if agency_config:
            text.append("Agency: ", style="bold")
            text.append(f"{agency_config.display_name}\n")
            text.append("Agency Purpose: ", style="bold")
            text.append(f"{agency_config.description}\n")
            text.append("Value: ", style="bold")
            text.append(f"{agency_config.value.value}\n")

            # Find agent config
            for agent_config in agency_config.agents:
                if agent_config.name == self.agent_name:
                    if agent_config.always_on:
                        text.append("Always On: ", style="bold")
                        text.append("Yes (runs on every tick)\n", style="green")
                    break
        else:
            text.append("Agency: ", style="bold")
            text.append(f"{self.agency_id} (not found in registry)\n")

        text.append("Full ID: ", style="bold")
        text.append(f"{self.agent_id}\n")

        return text

    def _load_prompt(self) -> str:
        """Load the agent's prompt file."""
        from rilai.agents.protocol import PROMPTS_DIR

        prompt_path = PROMPTS_DIR / self.agency_id / f"{self.agent_name}.md"
        if prompt_path.exists():
            return prompt_path.read_text()
        return f"(Prompt file not found: {prompt_path})"

    def _load_calls(self) -> None:
        """Load recent calls from the store."""
        from rilai.observability import get_store

        store = get_store()
        calls = store.get_recent_agent_calls(agent_id=self.agent_id, limit=20)

        if self._call_log:
            if not calls:
                self._call_log.mount(
                    Static("No recent calls for this agent.", classes="empty-message")
                )
                return

            for call in calls:
                item = AgentCallItem(call)
                self._call_log.mount(item)

    def action_refresh(self) -> None:
        """Refresh the call log."""
        if self._call_log:
            # Clear existing
            for child in list(self._call_log.children):
                child.remove()
            # Reload
            self._load_calls()
            self.notify("Refreshed agent calls")

    def action_dismiss(self) -> None:
        """Close the screen."""
        self.app.pop_screen()
