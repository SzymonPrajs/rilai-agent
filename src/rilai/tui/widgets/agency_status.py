"""Agency status widget for Rilai TUI.

Displays live status of all agencies and their agents.
"""

from dataclasses import dataclass
from datetime import datetime

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static


@dataclass
class AgencyState:
    """State of a single agency."""

    agency_id: str
    status: str  # "idle", "running", "completed", "error"
    processing_time_ms: int = 0
    agent_count: int = 0
    active_agents: int = 0
    u_max: int = 0
    last_run: datetime | None = None


class AgencyItem(Static):
    """Display for a single agency."""

    def __init__(self, agency_id: str, **kwargs):
        super().__init__(**kwargs)
        self.agency_id = agency_id
        self._status = "idle"
        self._time_ms = 0
        self._u_max = 0

    def update_state(self, state: AgencyState) -> None:
        """Update the agency state."""
        self._status = state.status
        self._time_ms = state.processing_time_ms
        self._u_max = state.u_max
        self.refresh()

    def render(self) -> Text:
        """Render the agency status."""
        # Status indicator
        indicators = {
            "idle": ("○", "dim"),
            "running": ("●", "yellow"),
            "completed": ("●", "green"),
            "error": ("●", "red"),
        }
        indicator, style = indicators.get(self._status, ("○", "dim"))

        # Format name
        name = self.agency_id.capitalize()

        # Format time
        if self._time_ms > 0:
            time_str = f"[{self._time_ms / 1000:.1f}s]"
        else:
            time_str = "[---]"

        # Status symbol
        if self._status == "completed":
            status_sym = "✓"
        elif self._status == "running":
            status_sym = "..."
        elif self._status == "error":
            status_sym = "✗"
        else:
            status_sym = ""

        text = Text()
        text.append(f" {indicator} ", style=style)
        text.append(f"{name:<12}", style="bold" if self._status == "running" else "")
        text.append(f" {time_str:<8}", style="dim")
        text.append(f" {status_sym}", style=style)

        return text


class AgencyStatus(Vertical):
    """Agency status panel."""

    DEFAULT_CSS = """
    AgencyStatus {
        height: auto;
        border: solid $primary;
        padding: 0;
    }

    AgencyStatus > Static.panel-title {
        dock: top;
        height: 1;
        background: $primary;
        color: $text;
        text-style: bold;
        padding: 0 1;
    }

    AgencyStatus .collapsible-title {
        padding: 0 1;
        background: $surface-darken-1;
    }

    AgencyStatus AgencyItem {
        height: 1;
        padding: 0 1;
    }
    """

    # Default agencies to display
    DEFAULT_AGENCIES = [
        "planning",
        "emotion",
        "social",
        "reasoning",
        "creative",
        "self",
        "resource",
        "inhibition",
        "monitoring",
        "execution",
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._agency_items: dict[str, AgencyItem] = {}
        self._expanded = True

    def compose(self) -> ComposeResult:
        """Create agency status components."""
        yield Static("▼ Agencies", classes="panel-title", id="agencies-title")

        for agency_id in self.DEFAULT_AGENCIES:
            item = AgencyItem(agency_id)
            self._agency_items[agency_id] = item
            yield item

    def update_agency(self, state: AgencyState) -> None:
        """Update a specific agency's state."""
        if state.agency_id in self._agency_items:
            self._agency_items[state.agency_id].update_state(state)

    def set_running(self, agency_id: str) -> None:
        """Mark an agency as running."""
        if agency_id in self._agency_items:
            state = AgencyState(agency_id=agency_id, status="running")
            self._agency_items[agency_id].update_state(state)

    def set_completed(
        self, agency_id: str, time_ms: int = 0, u_max: int = 0
    ) -> None:
        """Mark an agency as completed."""
        if agency_id in self._agency_items:
            state = AgencyState(
                agency_id=agency_id,
                status="completed",
                processing_time_ms=time_ms,
                u_max=u_max,
            )
            self._agency_items[agency_id].update_state(state)

    def set_error(self, agency_id: str) -> None:
        """Mark an agency as errored."""
        if agency_id in self._agency_items:
            state = AgencyState(agency_id=agency_id, status="error")
            self._agency_items[agency_id].update_state(state)

    def reset_all(self) -> None:
        """Reset all agencies to idle."""
        for agency_id in self._agency_items:
            state = AgencyState(agency_id=agency_id, status="idle")
            self._agency_items[agency_id].update_state(state)

    def toggle(self) -> None:
        """Toggle panel expansion."""
        self._expanded = not self._expanded
        title = self.query_one("#agencies-title", Static)

        if self._expanded:
            title.update("▼ Agencies")
            for item in self._agency_items.values():
                item.display = True
        else:
            title.update("▶ Agencies")
            for item in self._agency_items.values():
                item.display = False
