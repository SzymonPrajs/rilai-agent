"""Modulators display widget for Rilai TUI.

Shows global modulator values as progress bars.
"""

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static


class ModulatorBar(Static):
    """A single modulator display with progress bar."""

    def __init__(self, name: str, value: float = 0.0, **kwargs):
        super().__init__(**kwargs)
        self.name = name
        self._value = value

    def set_value(self, value: float) -> None:
        """Set the modulator value (0.0 to 1.0)."""
        self._value = max(0.0, min(1.0, value))
        self.refresh()

    def render(self) -> Text:
        """Render the modulator bar."""
        # Progress bar
        bar_width = 10
        filled = int(self._value * bar_width)
        empty = bar_width - filled

        # Color based on value
        if self._value < 0.3:
            style = "green"
        elif self._value < 0.6:
            style = "yellow"
        else:
            style = "red"

        text = Text()
        text.append(f"{self.name:<12}", style="bold")
        text.append(" [")
        text.append("█" * filled, style=style)
        text.append("░" * empty, style="dim")
        text.append("] ")
        text.append(f"{self._value:.2f}", style=style)

        return text


class ModulatorsPanel(Vertical):
    """Panel displaying all global modulators."""

    DEFAULT_CSS = """
    ModulatorsPanel {
        height: auto;
        border: solid $primary;
        padding: 0;
    }

    ModulatorsPanel > Static.panel-title {
        dock: top;
        height: 1;
        background: $primary;
        color: $text;
        text-style: bold;
        padding: 0 1;
    }

    ModulatorsPanel ModulatorBar {
        height: 1;
        padding: 0 1;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._bars: dict[str, ModulatorBar] = {}
        self._expanded = True

    def compose(self) -> ComposeResult:
        """Create modulator display components."""
        yield Static("▼ Modulators", classes="panel-title", id="modulators-title")

        modulators = [
            ("Arousal", 0.3),
            ("Fatigue", 0.0),
            ("Time press", 0.0),
            ("Social risk", 0.0),
        ]

        for name, default in modulators:
            bar = ModulatorBar(name, default)
            key = name.lower().replace(" ", "_")
            self._bars[key] = bar
            yield bar

    def update_modulators(
        self,
        arousal: float | None = None,
        fatigue: float | None = None,
        time_pressure: float | None = None,
        social_risk: float | None = None,
    ) -> None:
        """Update modulator values."""
        if arousal is not None and "arousal" in self._bars:
            self._bars["arousal"].set_value(arousal)
        if fatigue is not None and "fatigue" in self._bars:
            self._bars["fatigue"].set_value(fatigue)
        if time_pressure is not None and "time_press" in self._bars:
            self._bars["time_press"].set_value(time_pressure)
        if social_risk is not None and "social_risk" in self._bars:
            self._bars["social_risk"].set_value(social_risk)

    def update_from_dict(self, modulators: dict) -> None:
        """Update from a modulator dict."""
        self.update_modulators(
            arousal=modulators.get("arousal"),
            fatigue=modulators.get("fatigue"),
            time_pressure=modulators.get("time_pressure"),
            social_risk=modulators.get("social_risk"),
        )

    def toggle(self) -> None:
        """Toggle panel expansion."""
        self._expanded = not self._expanded
        title = self.query_one("#modulators-title", Static)

        if self._expanded:
            title.update("▼ Modulators")
            for bar in self._bars.values():
                bar.display = True
        else:
            title.update("▶ Modulators")
            for bar in self._bars.values():
                bar.display = False
