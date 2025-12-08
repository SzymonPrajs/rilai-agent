# Document 09: TUI

**Purpose:** Implement projection-based TUI with real-time streaming
**Execution:** One Claude Code session
**Dependencies:** 01-contracts, 02-event-store, 03-runtime-core

---

## Overview

The TUI is a pure projection from the event stream. It maintains no independent state - all state is derived from events. This enables:
- Real-time updates as events stream in
- Replayable UI state from event log
- Clean separation between runtime and display

---

## Files to Create

```
src/rilai/ui/
├── __init__.py
├── app.py              # Main Textual application
├── projection.py       # TurnStateProjection
├── panels/
│   ├── __init__.py
│   ├── chat.py         # Chat panel
│   ├── sensors.py      # Sensors display
│   ├── stance.py       # Stance vector display
│   ├── agents.py       # Agent activity log
│   ├── workspace.py    # Workspace state
│   ├── critics.py      # Critics results
│   └── activity.py     # Current stage indicator
└── styles.py           # CSS styles
```

---

## File: `src/rilai/ui/__init__.py`

```python
"""Rilai v3 TUI - Event-driven terminal interface."""

from rilai.ui.app import RilaiApp
from rilai.ui.projection import TurnStateProjection

__all__ = ["RilaiApp", "TurnStateProjection"]
```

---

## File: `src/rilai/ui/projection.py`

```python
"""TurnStateProjection - maintains UI state from event stream."""

from dataclasses import dataclass, field
from typing import Literal, List, Dict, Any

from rilai.contracts.events import EngineEvent, EventKind


UIUpdateKind = Literal[
    "sensors", "stance", "agents", "workspace",
    "critics", "memory", "chat", "activity", "claims"
]


@dataclass
class UIUpdate:
    """A single UI update to apply."""
    kind: UIUpdateKind
    payload: Dict[str, Any]


@dataclass
class TurnStateProjection:
    """Maintains TUI-ready state from event stream.

    This is the core of the projection-based UI. It receives events
    and produces UI updates. The app simply applies these updates
    to widgets.
    """

    # Sensor state
    sensors: Dict[str, float] = field(default_factory=dict)

    # Stance state
    stance: Dict[str, float] = field(default_factory=dict)
    stance_changes: Dict[str, float] = field(default_factory=dict)

    # Agent activity
    agent_logs: List[Dict[str, Any]] = field(default_factory=list)
    active_agents: List[str] = field(default_factory=list)

    # Workspace
    workspace: Dict[str, Any] = field(default_factory=dict)
    claims: List[Dict[str, Any]] = field(default_factory=list)
    consensus: float = 0.0

    # Critics
    critics: List[Dict[str, Any]] = field(default_factory=list)

    # Memory
    memory_summary: Dict[str, Any] = field(default_factory=dict)

    # Chat
    messages: List[Dict[str, str]] = field(default_factory=list)

    # Activity
    current_stage: str = "idle"
    turn_id: int = 0
    processing: bool = False

    def apply_event(self, event: EngineEvent) -> List[UIUpdate]:
        """Apply event and return UI updates.

        This is the main entry point. Each event type produces
        zero or more UI updates.
        """
        updates = []

        match event.kind:
            # Turn lifecycle
            case EventKind.TURN_STARTED:
                self.processing = True
                self.turn_id = event.payload.get("turn_id", 0)
                user_input = event.payload.get("user_input", "")
                self.messages.append({"role": "user", "content": user_input})
                updates.append(UIUpdate("chat", {"role": "user", "content": user_input}))
                updates.append(UIUpdate("activity", {"stage": "starting", "processing": True}))

            case EventKind.TURN_STAGE_CHANGED:
                self.current_stage = event.payload.get("stage", "idle")
                updates.append(UIUpdate("activity", {"stage": self.current_stage}))

            case EventKind.TURN_COMPLETED:
                self.processing = False
                total_time = event.payload.get("total_time_ms", 0)
                updates.append(UIUpdate("activity", {
                    "stage": "completed",
                    "processing": False,
                    "total_time_ms": total_time,
                }))

            # Sensors
            case EventKind.SENSORS_FAST_UPDATED:
                new_sensors = event.payload.get("sensors", {})
                self.sensors.update(new_sensors)
                updates.append(UIUpdate("sensors", {"sensors": self.sensors}))

            # Stance
            case EventKind.STANCE_UPDATED:
                delta = event.payload.get("delta", {})
                for key, change in delta.items():
                    old_val = self.stance.get(key, 0.0)
                    self.stance[key] = old_val + change
                    self.stance_changes[key] = change
                updates.append(UIUpdate("stance", {
                    "stance": self.stance,
                    "changes": self.stance_changes,
                }))

            # Agents
            case EventKind.AGENT_STARTED:
                agent_id = event.payload.get("agent_id", "?")
                self.active_agents.append(agent_id)
                updates.append(UIUpdate("agents", {"started": agent_id}))

            case EventKind.AGENT_COMPLETED:
                agent_id = event.payload.get("agent_id", "?")
                observation = event.payload.get("observation", "")
                salience = event.payload.get("salience", 0.0)
                urgency = event.payload.get("urgency", 0)
                processing_time = event.payload.get("processing_time_ms", 0)

                if agent_id in self.active_agents:
                    self.active_agents.remove(agent_id)

                # Only log non-quiet observations
                if observation and observation.lower() != "quiet":
                    log_entry = {
                        "agent_id": agent_id,
                        "observation": observation,
                        "salience": salience,
                        "urgency": urgency,
                        "time_ms": processing_time,
                    }
                    self.agent_logs.append(log_entry)
                    updates.append(UIUpdate("agents", {"completed": log_entry}))

            case EventKind.AGENT_FAILED:
                agent_id = event.payload.get("agent_id", "?")
                error = event.payload.get("error", "Unknown error")
                if agent_id in self.active_agents:
                    self.active_agents.remove(agent_id)
                updates.append(UIUpdate("agents", {"failed": agent_id, "error": error}))

            # Workspace
            case EventKind.WORKSPACE_PATCHED:
                patch = event.payload.get("patch", {})
                self.workspace.update(patch)
                updates.append(UIUpdate("workspace", {"patch": patch}))

            # Deliberation
            case EventKind.DELIB_ROUND_STARTED:
                round_num = event.payload.get("round", 0)
                updates.append(UIUpdate("activity", {"stage": f"deliberation_r{round_num}"}))

            case EventKind.CONSENSUS_UPDATED:
                self.consensus = event.payload.get("score", 0.0)
                updates.append(UIUpdate("workspace", {"consensus": self.consensus}))

            # Council
            case EventKind.COUNCIL_DECISION_MADE:
                decision = {
                    "speak": event.payload.get("speak", False),
                    "urgency": event.payload.get("urgency", "low"),
                    "intent": event.payload.get("intent"),
                }
                updates.append(UIUpdate("workspace", {"decision": decision}))

            # Voice
            case EventKind.VOICE_RENDERED:
                text = event.payload.get("text", "")
                if text:
                    self.messages.append({"role": "assistant", "content": text})
                    updates.append(UIUpdate("chat", {"role": "assistant", "content": text}))

            # Critics
            case EventKind.CRITICS_UPDATED:
                self.critics = event.payload.get("results", [])
                passed = event.payload.get("passed", True)
                updates.append(UIUpdate("critics", {
                    "results": self.critics,
                    "passed": passed,
                }))

            # Memory
            case EventKind.MEMORY_COMMITTED:
                self.memory_summary = event.payload.get("summary", {})
                updates.append(UIUpdate("memory", {"summary": self.memory_summary}))

            # Safety
            case EventKind.SAFETY_INTERRUPT:
                reason = event.payload.get("reason", "Unknown")
                updates.append(UIUpdate("activity", {"safety_interrupt": reason}))

            # Daemon
            case EventKind.PROACTIVE_NUDGE:
                nudge = event.payload
                updates.append(UIUpdate("chat", {
                    "role": "system",
                    "content": f"[Nudge: {nudge.get('reason', '?')}]",
                }))

        return updates

    def reset_for_turn(self) -> None:
        """Reset transient state for new turn."""
        self.agent_logs.clear()
        self.active_agents.clear()
        self.claims.clear()
        self.critics.clear()
        self.stance_changes.clear()
        self.consensus = 0.0
        self.current_stage = "idle"

    def get_agent_summary(self) -> str:
        """Get summary of agent activity for display."""
        if not self.agent_logs:
            return "No agent activity"

        lines = []
        for log in self.agent_logs[-10:]:
            urgency_marker = "!" * log.get("urgency", 0)
            lines.append(f"{log['agent_id']}: {log['observation'][:60]} {urgency_marker}")

        return "\n".join(lines)
```

---

## File: `src/rilai/ui/app.py`

```python
"""Main Rilai TUI application."""

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, Container
from textual.widgets import Header, Footer, Input, Static, RichLog, DataTable

from rilai.ui.projection import TurnStateProjection, UIUpdate
from rilai.ui.panels.chat import ChatPanel
from rilai.ui.panels.sensors import SensorsPanel
from rilai.ui.panels.stance import StancePanel
from rilai.ui.panels.agents import AgentsPanel
from rilai.ui.panels.activity import ActivityPanel
from rilai.ui.panels.critics import CriticsPanel


class RilaiApp(App):
    """Rilai v3 TUI - Pure projection from event stream."""

    CSS = """
    Screen {
        layout: grid;
        grid-size: 2 1;
        grid-columns: 2fr 1fr;
    }

    #main-panel {
        height: 100%;
    }

    #side-panel {
        height: 100%;
        border-left: solid $primary;
    }

    #chat-container {
        height: 1fr;
    }

    #input-container {
        height: auto;
        padding: 1;
    }

    ChatPanel {
        height: 100%;
        border: solid $primary;
    }

    Input {
        dock: bottom;
    }

    .panel-title {
        background: $primary;
        color: $text;
        padding: 0 1;
    }

    SensorsPanel, StancePanel, AgentsPanel {
        height: auto;
        max-height: 10;
        border: solid $secondary;
        margin-bottom: 1;
    }

    ActivityPanel {
        height: 3;
        border: solid $accent;
    }

    CriticsPanel {
        height: auto;
        max-height: 8;
        border: solid $warning;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit"),
        Binding("ctrl+l", "clear", "Clear"),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, runtime: "TurnRunner" = None):
        super().__init__()
        self.runtime = runtime
        self.projection = TurnStateProjection()
        self._processing = False

    def compose(self) -> ComposeResult:
        """Compose the UI layout."""
        yield Header()

        with Horizontal():
            # Main chat panel
            with Vertical(id="main-panel"):
                with Container(id="chat-container"):
                    yield ChatPanel(id="chat")
                with Container(id="input-container"):
                    yield Input(id="input", placeholder="Type a message...")

            # Side panel with status
            with Vertical(id="side-panel"):
                yield ActivityPanel(id="activity")
                yield SensorsPanel(id="sensors")
                yield StancePanel(id="stance")
                yield AgentsPanel(id="agents")
                yield CriticsPanel(id="critics")

        yield Footer()

    async def on_mount(self) -> None:
        """Handle app mount."""
        self.query_one("#input", Input).focus()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle user input submission."""
        if self._processing:
            return

        user_text = event.value.strip()
        if not user_text:
            return

        event.input.clear()

        # Handle slash commands
        if user_text.startswith("/"):
            await self._handle_command(user_text)
            return

        # Process through runtime
        await self._run_turn(user_text)

    async def _run_turn(self, user_text: str) -> None:
        """Run a turn through the runtime."""
        if not self.runtime:
            self._add_system_message("No runtime configured")
            return

        self._processing = True
        self.projection.reset_for_turn()

        try:
            async for event in self.runtime.run_turn(user_text):
                updates = self.projection.apply_event(event)
                for update in updates:
                    await self._apply_update(update)
        except Exception as e:
            self._add_system_message(f"Error: {e}")
        finally:
            self._processing = False

    async def _apply_update(self, update: UIUpdate) -> None:
        """Apply a UI update to widgets."""
        match update.kind:
            case "chat":
                chat = self.query_one("#chat", ChatPanel)
                chat.add_message(
                    role=update.payload.get("role", "system"),
                    content=update.payload.get("content", ""),
                )

            case "sensors":
                sensors_panel = self.query_one("#sensors", SensorsPanel)
                sensors_panel.update_sensors(update.payload.get("sensors", {}))

            case "stance":
                stance_panel = self.query_one("#stance", StancePanel)
                stance_panel.update_stance(
                    stance=update.payload.get("stance", {}),
                    changes=update.payload.get("changes", {}),
                )

            case "agents":
                agents_panel = self.query_one("#agents", AgentsPanel)
                if "started" in update.payload:
                    agents_panel.agent_started(update.payload["started"])
                elif "completed" in update.payload:
                    agents_panel.agent_completed(update.payload["completed"])
                elif "failed" in update.payload:
                    agents_panel.agent_failed(
                        update.payload["failed"],
                        update.payload.get("error", ""),
                    )

            case "activity":
                activity = self.query_one("#activity", ActivityPanel)
                activity.update_state(update.payload)

            case "critics":
                critics = self.query_one("#critics", CriticsPanel)
                critics.update_results(
                    results=update.payload.get("results", []),
                    passed=update.payload.get("passed", True),
                )

            case "workspace":
                # Workspace updates can trigger multiple panels
                pass

            case "memory":
                # Could show in a dedicated panel
                pass

    async def _handle_command(self, command: str) -> None:
        """Handle slash commands."""
        parts = command[1:].split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        match cmd:
            case "help":
                self._add_system_message(
                    "Commands: /help, /clear, /status, /quit"
                )
            case "clear":
                self.action_clear()
            case "status":
                self._show_status()
            case "quit":
                self.exit()
            case _:
                self._add_system_message(f"Unknown command: {cmd}")

    def _add_system_message(self, message: str) -> None:
        """Add a system message to chat."""
        chat = self.query_one("#chat", ChatPanel)
        chat.add_message(role="system", content=message)

    def _show_status(self) -> None:
        """Show current status."""
        status_lines = [
            f"Turn: {self.projection.turn_id}",
            f"Stage: {self.projection.current_stage}",
            f"Processing: {self._processing}",
            f"Messages: {len(self.projection.messages)}",
            f"Agents active: {len(self.projection.active_agents)}",
        ]
        self._add_system_message("\n".join(status_lines))

    def action_clear(self) -> None:
        """Clear the chat panel."""
        chat = self.query_one("#chat", ChatPanel)
        chat.clear()
        self.projection.messages.clear()

    def action_cancel(self) -> None:
        """Cancel current processing."""
        if self._processing:
            self._add_system_message("Cancellation not yet implemented")
```

---

## File: `src/rilai/ui/panels/chat.py`

```python
"""Chat panel widget."""

from textual.widgets import RichLog
from rich.text import Text


class ChatPanel(RichLog):
    """Chat panel showing conversation history."""

    def __init__(self, **kwargs):
        super().__init__(highlight=True, markup=True, **kwargs)

    def add_message(self, role: str, content: str) -> None:
        """Add a message to the chat."""
        if role == "user":
            prefix = Text("You: ", style="bold cyan")
        elif role == "assistant":
            prefix = Text("Rilai: ", style="bold green")
        else:
            prefix = Text("System: ", style="dim")

        self.write(prefix)
        self.write(content)
        self.write("")  # Blank line

    def clear(self) -> None:
        """Clear all messages."""
        self.clear()
```

---

## File: `src/rilai/ui/panels/sensors.py`

```python
"""Sensors panel widget."""

from textual.widgets import Static
from rich.table import Table


class SensorsPanel(Static):
    """Panel showing fast sensor readings."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._sensors = {}

    def update_sensors(self, sensors: dict) -> None:
        """Update sensor display."""
        self._sensors.update(sensors)
        self._render()

    def _render(self) -> None:
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
```

---

## File: `src/rilai/ui/panels/stance.py`

```python
"""Stance panel widget."""

from textual.widgets import Static
from rich.table import Table
from rich.text import Text


class StancePanel(Static):
    """Panel showing stance vector."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._stance = {}
        self._changes = {}

    def update_stance(self, stance: dict, changes: dict = None) -> None:
        """Update stance display."""
        self._stance = stance
        self._changes = changes or {}
        self._render()

    def _render(self) -> None:
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
```

---

## File: `src/rilai/ui/panels/agents.py`

```python
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
```

---

## File: `src/rilai/ui/panels/activity.py`

```python
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
```

---

## File: `src/rilai/ui/panels/critics.py`

```python
"""Critics panel widget."""

from textual.widgets import Static
from rich.table import Table
from rich.text import Text


class CriticsPanel(Static):
    """Panel showing critic validation results."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._results = []
        self._passed = True

    def update_results(self, results: list, passed: bool) -> None:
        """Update critic results."""
        self._results = results
        self._passed = passed
        self._render()

    def _render(self) -> None:
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
```

---

## File: `src/rilai/ui/panels/__init__.py`

```python
"""TUI panel widgets."""

from rilai.ui.panels.chat import ChatPanel
from rilai.ui.panels.sensors import SensorsPanel
from rilai.ui.panels.stance import StancePanel
from rilai.ui.panels.agents import AgentsPanel
from rilai.ui.panels.activity import ActivityPanel
from rilai.ui.panels.critics import CriticsPanel

__all__ = [
    "ChatPanel",
    "SensorsPanel",
    "StancePanel",
    "AgentsPanel",
    "ActivityPanel",
    "CriticsPanel",
]
```

---

## CLI Integration

Update `src/rilai/cli.py`:

```python
"""Rilai CLI entry point."""

import asyncio
from pathlib import Path

import click


@click.group()
def cli():
    """Rilai - AI Companion"""
    pass


@cli.command()
def run():
    """Run Rilai TUI."""
    from rilai.ui.app import RilaiApp
    from rilai.runtime.turn_runner import TurnRunner
    from rilai.store.event_log import EventLogWriter
    from rilai.runtime.workspace import Workspace

    # Initialize components
    data_dir = Path.home() / ".rilai"
    data_dir.mkdir(exist_ok=True)

    event_log = EventLogWriter(data_dir / "events.db")
    workspace = Workspace()

    runner = TurnRunner(
        event_log=event_log,
        workspace=workspace,
    )

    # Run app
    app = RilaiApp(runtime=runner)
    app.run()


@cli.command()
def shell():
    """Run Rilai in shell mode (no TUI)."""
    from rilai.runtime.turn_runner import TurnRunner
    from rilai.store.event_log import EventLogWriter
    from rilai.runtime.workspace import Workspace

    # Initialize
    data_dir = Path.home() / ".rilai"
    data_dir.mkdir(exist_ok=True)

    event_log = EventLogWriter(data_dir / "events.db")
    workspace = Workspace()

    runner = TurnRunner(
        event_log=event_log,
        workspace=workspace,
    )

    async def run_shell():
        print("Rilai Shell (type 'quit' to exit)")
        while True:
            try:
                user_input = input("\nYou: ").strip()
            except (EOFError, KeyboardInterrupt):
                break

            if user_input.lower() in ("quit", "exit"):
                break

            if not user_input:
                continue

            response = ""
            async for event in runner.run_turn(user_input):
                if event.kind.value == "voice_rendered":
                    response = event.payload.get("text", "")

            if response:
                print(f"\nRilai: {response}")

    asyncio.run(run_shell())


if __name__ == "__main__":
    cli()
```

---

## v2 Files to DELETE

```
src/rilai/tui/app.py (rewritten from scratch)
src/rilai/tui/panels/ (if exists)
```

---

## Tests

```python
"""Tests for TUI module."""

import pytest
from rilai.ui.projection import TurnStateProjection, UIUpdate
from rilai.contracts.events import EngineEvent, EventKind


class TestProjection:
    def test_turn_started_adds_user_message(self):
        projection = TurnStateProjection()

        event = EngineEvent(
            session_id="test",
            turn_id=1,
            seq=0,
            ts_monotonic=0.0,
            kind=EventKind.TURN_STARTED,
            payload={"user_input": "Hello", "turn_id": 1},
        )

        updates = projection.apply_event(event)

        assert any(u.kind == "chat" for u in updates)
        assert projection.messages[-1]["role"] == "user"
        assert projection.messages[-1]["content"] == "Hello"

    def test_agent_completed_logs_non_quiet(self):
        projection = TurnStateProjection()

        event = EngineEvent(
            session_id="test",
            turn_id=1,
            seq=1,
            ts_monotonic=0.1,
            kind=EventKind.AGENT_COMPLETED,
            payload={
                "agent_id": "emotion.stress",
                "observation": "User seems stressed",
                "urgency": 2,
                "salience": 0.8,
            },
        )

        updates = projection.apply_event(event)

        assert any(u.kind == "agents" for u in updates)
        assert len(projection.agent_logs) == 1
        assert projection.agent_logs[0]["agent_id"] == "emotion.stress"

    def test_agent_completed_ignores_quiet(self):
        projection = TurnStateProjection()

        event = EngineEvent(
            session_id="test",
            turn_id=1,
            seq=1,
            ts_monotonic=0.1,
            kind=EventKind.AGENT_COMPLETED,
            payload={
                "agent_id": "emotion.stress",
                "observation": "Quiet",
                "urgency": 0,
            },
        )

        updates = projection.apply_event(event)

        # No agent update for quiet
        assert not any(u.kind == "agents" and "completed" in u.payload for u in updates)
        assert len(projection.agent_logs) == 0

    def test_voice_rendered_adds_assistant_message(self):
        projection = TurnStateProjection()

        event = EngineEvent(
            session_id="test",
            turn_id=1,
            seq=10,
            ts_monotonic=1.0,
            kind=EventKind.VOICE_RENDERED,
            payload={"text": "I hear you're stressed."},
        )

        updates = projection.apply_event(event)

        assert any(u.kind == "chat" for u in updates)
        assert projection.messages[-1]["role"] == "assistant"

    def test_reset_for_turn_clears_transient(self):
        projection = TurnStateProjection()
        projection.agent_logs.append({"agent_id": "test"})
        projection.critics.append({"critic_id": "test"})
        projection.consensus = 0.9

        projection.reset_for_turn()

        assert len(projection.agent_logs) == 0
        assert len(projection.critics) == 0
        assert projection.consensus == 0.0
```

---

## Next Document

Proceed to `10-daemon.md` after TUI is implemented.
