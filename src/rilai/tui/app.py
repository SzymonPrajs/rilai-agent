"""Main Rilai TUI application."""

from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, Static


class RilaiApp(App):
    """Rilai v2 Terminal User Interface."""

    TITLE = "Rilai v2"
    CSS = """
    Screen {
        layout: grid;
        grid-size: 2;
        grid-columns: 3fr 1fr;
    }

    #chat-panel {
        row-span: 2;
    }

    #status-panel {
        height: 100%;
    }
    """

    BINDINGS = [
        ("ctrl+d", "quit", "Quit"),
        ("ctrl+a", "toggle_agencies", "Agencies"),
        ("ctrl+t", "toggle_thinking", "Thinking"),
    ]

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header()
        yield Static("Chat panel - coming soon", id="chat-panel")
        yield Static("Status panel - coming soon", id="status-panel")
        yield Footer()

    def action_toggle_agencies(self) -> None:
        """Toggle agency status panel visibility."""
        self.notify("Agency panel toggle - coming soon")

    def action_toggle_thinking(self) -> None:
        """Toggle thinking panel visibility."""
        self.notify("Thinking panel toggle - coming soon")
