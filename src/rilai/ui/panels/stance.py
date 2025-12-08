"""Stance panel widget."""

from textual.widgets import Static
from rich.table import Table
from rich.text import Text


class StancePanel(Static):
    """Panel showing stance vector."""

    def __init__(self, **kwargs):
        super().__init__("No stance data", **kwargs)
        self._stance = {}
        self._changes = {}

    def update_stance(self, stance: dict, changes: dict = None) -> None:
        """Update stance display."""
        self._stance = stance
        self._changes = changes or {}
        self._refresh_display()

    def _refresh_display(self) -> None:
        """Render the stance table."""
        if not self._stance:
            self.update("No stance data")
            return

        table = Table(title="Stance", box=None, padding=(0, 1))
        table.add_column("Dim", style="cyan", width=10)
        table.add_column("Value", justify="center", width=12)
        table.add_column("Δ", justify="right", width=6)

        for dim in ["valence", "arousal", "strain", "closeness", "certainty", "safety", "curiosity", "control"]:
            value = self._stance.get(dim, 0.0)
            change = self._changes.get(dim, 0.0)

            # Visual bar
            bar_pos = int((value + 1) * 5) if dim == "valence" else int(value * 10)
            bar_pos = max(0, min(10, bar_pos))
            bar = "─" * bar_pos + "●" + "─" * (10 - bar_pos)

            # Change indicator
            if change > 0.01:
                change_text = Text(f"+{change:.2f}", style="green")
            elif change < -0.01:
                change_text = Text(f"{change:.2f}", style="red")
            else:
                change_text = Text("", style="dim")

            table.add_row(dim[:8], bar, change_text)

        self.update(table)
