"""Agents panel widget."""

from textual.widgets import RichLog
from rich.text import Text


class AgentsPanel(RichLog):
    """Panel showing agent activity."""

    def __init__(self, **kwargs):
        super().__init__(max_lines=50, **kwargs)
        self._active = set()

    def agent_started(self, agent_id: str) -> None:
        """Mark agent as started."""
        self._active.add(agent_id)
        self.write(Text(f"▶ {agent_id}", style="dim"))

    def agent_completed(self, log_entry: dict) -> None:
        """Show agent completion."""
        agent_id = log_entry.get("agent_id", "?")
        observation = log_entry.get("observation", "")[:60]
        urgency = log_entry.get("urgency", 0)

        self._active.discard(agent_id)

        # Style based on urgency
        if urgency >= 2:
            style = "bold yellow"
        elif urgency >= 1:
            style = "white"
        else:
            style = "dim"

        urgency_marker = "!" * urgency
        text = Text(f"✓ {agent_id}: {observation} {urgency_marker}", style=style)
        self.write(text)

    def agent_failed(self, agent_id: str, error: str) -> None:
        """Show agent failure."""
        self._active.discard(agent_id)
        self.write(Text(f"✗ {agent_id}: {error[:40]}", style="red"))
