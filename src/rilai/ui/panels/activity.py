"""Activity panel widget."""

from textual.widgets import Static
from rich.text import Text


class ActivityPanel(Static):
    """Panel showing current processing stage."""

    STAGE_NAMES = {
        "idle": "Ready",
        "starting": "Starting...",
        "ingest": "Ingesting",
        "sensing_fast": "Fast Sensors",
        "context": "Loading Context",
        "agents": "Running Agents",
        "deliberation": "Deliberating",
        "deliberation_r0": "Deliberation (Round 0)",
        "deliberation_r1": "Deliberation (Round 1)",
        "deliberation_r2": "Deliberation (Round 2)",
        "council": "Council Decision",
        "critics": "Critics Review",
        "memory_commit": "Saving Memory",
        "completed": "Completed",
    }

    STAGE_ICONS = {
        "idle": "○",
        "starting": "◐",
        "ingest": "↓",
        "sensing_fast": "⚡",
        "context": "📚",
        "agents": "🤖",
        "deliberation": "💭",
        "council": "👑",
        "critics": "🔍",
        "memory_commit": "💾",
        "completed": "✓",
    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._stage = "idle"
        self._processing = False
        self._last_time = None

    def update_state(self, payload: dict) -> None:
        """Update activity state."""
        if "stage" in payload:
            self._stage = payload["stage"]
        if "processing" in payload:
            self._processing = payload["processing"]
        if "total_time_ms" in payload:
            self._last_time = payload["total_time_ms"]

        self._render()

    def _render(self) -> None:
        """Render the activity indicator."""
        stage_name = self.STAGE_NAMES.get(self._stage, self._stage)
        icon = self.STAGE_ICONS.get(self._stage.split("_r")[0], "●")

        if self._processing:
            style = "bold cyan"
            suffix = "..."
        elif self._stage == "completed" and self._last_time:
            style = "green"
            suffix = f" ({self._last_time}ms)"
        else:
            style = "dim"
            suffix = ""

        text = Text(f"{icon} {stage_name}{suffix}", style=style)
        self.update(text)
