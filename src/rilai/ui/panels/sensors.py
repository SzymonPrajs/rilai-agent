"""Sensors panel widget."""

from textual.widgets import Static
from rich.table import Table


class SensorsPanel(Static):
    """Panel showing fast sensor readings."""

    def __init__(self, **kwargs):
        super().__init__("No sensors", **kwargs)
        self._sensors = {}

    def update_sensors(self, sensors: dict) -> None:
        """Update sensor display."""
        self._sensors.update(sensors)
        self._refresh_display()

    def _refresh_display(self) -> None:
        """Render the sensors table."""
        if not self._sensors:
            self.update("No sensors")
            return

        table = Table(title="Sensors", box=None, padding=(0, 1))
        table.add_column("Sensor", style="cyan")
        table.add_column("Value", justify="right")

        for sensor, value in sorted(self._sensors.items()):
            # Format as percentage or bar
            if isinstance(value, float):
                bar_len = int(value * 10)
                bar = "█" * bar_len + "░" * (10 - bar_len)
                display = f"{bar} {value:.0%}"
            else:
                display = str(value)

            table.add_row(sensor, display)

        self.update(table)
