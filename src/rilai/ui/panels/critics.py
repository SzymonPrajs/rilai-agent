"""Critics panel widget."""

from textual.widgets import Static
from rich.table import Table
from rich.text import Text


class CriticsPanel(Static):
    """Panel showing critic validation results."""

    def __init__(self, **kwargs):
        super().__init__("No critic results", **kwargs)
        self._results = []
        self._passed = True

    def update_results(self, results: list, passed: bool) -> None:
        """Update critic results."""
        self._results = results
        self._passed = passed
        self._refresh_display()

    def _refresh_display(self) -> None:
        """Render the critics table."""
        if not self._results:
            self.update(Text("No critic results", style="dim"))
            return

        table = Table(box=None, padding=(0, 1))
        table.add_column("Critic", style="cyan", width=15)
        table.add_column("Status", width=6)
        table.add_column("Message", width=30)

        for result in self._results:
            critic_id = result.get("critic_id", "?")
            passed = result.get("passed", True)
            severity = result.get("severity", "info")
            message = result.get("message", "")

            if passed:
                status = Text("✓", style="green")
            elif severity == "block":
                status = Text("✗", style="bold red")
            elif severity == "warning":
                status = Text("!", style="yellow")
            else:
                status = Text("?", style="dim")

            table.add_row(critic_id, status, message[:28] if message else "")

        self.update(table)
