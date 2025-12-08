"""Rilai TUI - Textual-based interface with live telemetry.

Split-screen layout:
- Left: Chat panel (user/assistant messages, input bar)
- Right: Inspector panel (sensors, stance, agents, workspace, memory)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Literal

from rich.align import Align
from rich.panel import Panel
from rich.text import Text

from textual import on
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Pretty,
    RichLog,
    Static,
    TabbedContent,
    TabPane,
    OptionList,
)
from textual.widgets.option_list import Option
from textual.screen import ModalScreen


# -----------------------------
# Engine event contract (UI-port)
# -----------------------------
EventKind = Literal["sensors", "stance", "agent_log", "workspace", "assistant", "memory", "activity", "critics"]


@dataclass(frozen=True)
class EngineEvent:
    """Event emitted by the engine for TUI updates."""
    kind: EventKind
    payload: dict[str, Any]


class Engine:
    """Protocol for engine implementations."""

    async def start(self) -> None:
        """Start the engine."""
        pass

    async def stop(self) -> None:
        """Stop the engine."""
        pass

    async def stream_turn(self, user_text: str) -> AsyncIterator[EngineEvent]:
        """Process user input and stream events for TUI updates."""
        raise NotImplementedError


class MockEngine(Engine):
    """Demo engine that streams telemetry like a real pipeline would."""

    async def stream_turn(self, user_text: str) -> AsyncIterator[EngineEvent]:
        # 1) sensors arrive first
        await asyncio.sleep(0.10)
        yield EngineEvent("sensors", {
            "vulnerability": (0.72 if "scared" in user_text.lower() else 0.12, "...scared..."),
            "advice_requested": (0.05, ""),
            "relational_bid": (0.41 if "you" in user_text.lower() else 0.18, ""),
            "ambiguity": (0.22, ""),
            "safety_risk": (0.01, ""),
        })

        # 2) stance update
        await asyncio.sleep(0.10)
        yield EngineEvent("stance", {
            "valence": 0.10,
            "arousal": 0.44,
            "certainty": 0.58,
            "safety": 0.70,
            "closeness": 0.46,
            "curiosity": 0.66,
            "strain": 0.22,
            "goal": "WITNESS",
            "tier": "medium",
        })

        # 3) micro-agent glimpses (streamy)
        await asyncio.sleep(0.12)
        yield EngineEvent("agent_log", {"line": "fear_reader: could be judgment-fear more than food"})
        await asyncio.sleep(0.08)
        yield EngineEvent("agent_log", {"line": "vulnerability_holder: witness first; no tips unless asked"})
        await asyncio.sleep(0.06)
        yield EngineEvent("agent_log", {"line": "meta_transparency: if asked 'do you feel', be brief + return to them"})

        # 4) workspace packet
        await asyncio.sleep(0.12)
        yield EngineEvent("workspace", {
            "goal": "WITNESS",
            "primary_question": "Is it sensory fear, or fear of being judged?",
            "constraints": ["no_premature_advice", "be_specific", "one_good_question"],
            "sensor_summary": {"vulnerability": 0.72, "advice_requested": 0.05, "relational_bid": 0.41},
        })

        # 5) assistant response
        await asyncio.sleep(0.25)
        yield EngineEvent("assistant", {
            "text": (
                "That lands as surprisingly tender - pizza is such a normal thing to be afraid of.\n"
                "Before I try to be helpful: is the fear more body-level (texture / getting sick), "
                "or more like 'I'll seem weird if I react to this'?"
            )
        })

        # 6) memory write (optional)
        await asyncio.sleep(0.05)
        yield EngineEvent("memory", {"line": "memory_write: preference_seed? (low confidence)"})


class RealEngine(Engine):
    """Adapter that wraps the real Rilai engine for TUI integration.

    Subscribes to the event bus for real-time streaming during processing,
    then yields final state from EngineResult.
    """

    def __init__(self):
        from rilai.core.engine import Engine as CoreEngine
        from rilai.core.events import event_bus, EventType

        self._engine = CoreEngine()
        self._event_bus = event_bus
        self._EventType = EventType
        self._event_queue: asyncio.Queue[EngineEvent] = asyncio.Queue()
        self._subscribed = False

    async def start(self) -> None:
        """Start the engine and subscribe to events."""
        await self._engine.start()
        self._subscribe_to_events()

    async def stop(self) -> None:
        """Stop the engine and unsubscribe from events."""
        self._unsubscribe_from_events()
        await self._engine.stop()

    def _subscribe_to_events(self) -> None:
        """Subscribe to core events for real-time TUI updates."""
        if self._subscribed:
            return
        self._subscribed = True

        ET = self._EventType
        self._event_bus.subscribe(ET.AGENT_COMPLETED, self._on_agent_completed)
        self._event_bus.subscribe(ET.AGENCY_STARTED, self._on_agency_started)
        self._event_bus.subscribe(ET.COUNCIL_STARTED, self._on_council_started)
        self._event_bus.subscribe(ET.COUNCIL_DECISION, self._on_council_decision)
        self._event_bus.subscribe(ET.ERROR, self._on_error)

    def _unsubscribe_from_events(self) -> None:
        """Unsubscribe from core events."""
        if not self._subscribed:
            return
        self._subscribed = False

        ET = self._EventType
        self._event_bus.unsubscribe(ET.AGENT_COMPLETED, self._on_agent_completed)
        self._event_bus.unsubscribe(ET.AGENCY_STARTED, self._on_agency_started)
        self._event_bus.unsubscribe(ET.COUNCIL_STARTED, self._on_council_started)
        self._event_bus.unsubscribe(ET.COUNCIL_DECISION, self._on_council_decision)
        self._event_bus.unsubscribe(ET.ERROR, self._on_error)

    async def _on_agent_completed(self, event) -> None:
        """Handle agent completion - stream glimpses to TUI."""
        agent_id = event.data.get("agent_id", "?")
        voice = event.data.get("voice", "")
        if voice:
            line = f"{agent_id}: {voice[:80]}{'...' if len(voice) > 80 else ''}"
            await self._event_queue.put(EngineEvent("agent_log", {"line": line}))

    async def _on_agency_started(self, event) -> None:
        """Handle agency start - update activity indicator."""
        await self._event_queue.put(EngineEvent("activity", {"state": "SENSING"}))

    async def _on_council_started(self, event) -> None:
        """Handle council start - update activity indicator."""
        await self._event_queue.put(EngineEvent("activity", {"state": "THINKING"}))

    async def _on_council_decision(self, event) -> None:
        """Handle council decision - partial workspace update."""
        intent = event.data.get("intent", "")
        if intent:
            await self._event_queue.put(EngineEvent("workspace", {"goal": intent}))

    async def _on_error(self, event) -> None:
        """Handle errors."""
        await self._event_queue.put(EngineEvent("activity", {"state": "ALERT"}))

    async def stream_turn(self, user_text: str) -> AsyncIterator[EngineEvent]:
        """Process user input and stream events for TUI updates."""
        # Clear any stale events
        while not self._event_queue.empty():
            try:
                self._event_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        # Signal start
        yield EngineEvent("activity", {"state": "SENSING"})

        # Start processing in background (events will be queued by subscribers)
        task = asyncio.create_task(self._engine.process_message(user_text))

        # Yield events as they arrive while processing
        while not task.done():
            try:
                event = await asyncio.wait_for(self._event_queue.get(), timeout=0.1)
                yield event
            except asyncio.TimeoutError:
                continue

        # Get result
        result = await task

        # Yield final state from turn_state
        ts = result.turn_state

        # Sensors: convert {sensor: p} to {sensor: (p, "")} for TUI format
        sensors_converted = {k: (v, "") for k, v in ts.sensors.items()}
        yield EngineEvent("sensors", sensors_converted)

        # Stance: inject goal and tier
        stance_data = ts.stance.copy()
        stance_data["goal"] = ts.workspace.get("goal", "-")
        stance_data["tier"] = ts.workspace.get("tier", "medium")
        yield EngineEvent("stance", stance_data)

        # Workspace
        yield EngineEvent("workspace", ts.workspace)

        # Agents: log any remaining glimpses
        for agent in ts.agents:
            glimpse = agent.get("glimpse", "")
            if glimpse:
                yield EngineEvent("agent_log", {"line": f"{agent.get('agent', '?')}: {glimpse}"})

        # Critics
        yield EngineEvent("critics", {"results": ts.critics})

        # Memory
        yield EngineEvent("memory", {"summary": ts.memory})

        # Assistant response
        if result.response:
            yield EngineEvent("assistant", {"text": result.response})

        # Done
        yield EngineEvent("activity", {"state": "IDLE"})


# -----------------------------
# Scenario Selection Modal
# -----------------------------
class ScenarioSelectScreen(ModalScreen[str | None]):
    """Modal screen for selecting a scenario to play."""

    CSS = """
    ScenarioSelectScreen {
        align: center middle;
    }

    #scenario-dialog {
        width: 60;
        height: auto;
        max-height: 80%;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }

    #scenario-title {
        text-align: center;
        text-style: bold;
        padding-bottom: 1;
    }

    #scenario-list {
        height: auto;
        max-height: 20;
        margin-bottom: 1;
    }

    #scenario-buttons {
        height: 3;
        align: center middle;
    }
    """

    def __init__(self, scenarios: list[Path]) -> None:
        super().__init__()
        self.scenarios = scenarios

    def compose(self) -> ComposeResult:
        with Vertical(id="scenario-dialog"):
            yield Static("Select Scenario", id="scenario-title")
            option_list = OptionList(id="scenario-list")
            for scenario in self.scenarios:
                option_list.add_option(Option(scenario.stem, id=str(scenario)))
            yield option_list
            with Horizontal(id="scenario-buttons"):
                yield Button("Play", id="play-btn", variant="primary")
                yield Button("Cancel", id="cancel-btn")

    @on(Button.Pressed, "#play-btn")
    def on_play(self) -> None:
        option_list = self.query_one("#scenario-list", OptionList)
        if option_list.highlighted is not None:
            option = option_list.get_option_at_index(option_list.highlighted)
            self.dismiss(option.id)
        else:
            self.dismiss(None)

    @on(Button.Pressed, "#cancel-btn")
    def on_cancel(self) -> None:
        self.dismiss(None)

    @on(OptionList.OptionSelected)
    def on_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)


# -----------------------------
# Main TUI Application
# -----------------------------
class RilaiTUI(App):
    """Rilai TUI with chat and live telemetry inspector."""

    CSS = """
    Screen {
        background: $background;
        color: $foreground;
    }

    #body {
        height: 1fr;
        padding: 1;
    }

    #chat-pane {
        width: 1fr;
        height: 1fr;
        border: round $panel;
        background: $surface;
        margin-right: 1;
    }

    #inspect-pane {
        width: 1fr;
        height: 1fr;
        border: round $panel;
        background: $surface;
    }

    .pane-title {
        height: 3;
        padding: 0 1;
        content-align: left middle;
        background: $panel;
        color: $foreground;
        text-style: bold;
        border-bottom: heavy $surface;
    }

    #chat-log {
        height: 1fr;
        border: round $surface;
        background: $panel;
        margin: 1;
    }

    #input-row {
        height: 3;
        margin: 0 1 1 1;
    }

    #chat-input {
        width: 1fr;
        background: $panel;
        border: tall $accent;
    }

    #send-btn {
        margin-left: 1;
        min-width: 8;
    }

    #mic-btn {
        margin-left: 1;
        min-width: 10;
    }

    Button.-primary {
        background: $accent 20%;
        border: tall $accent;
        text-style: bold;
    }

    #activity-bar {
        height: 3;
        padding: 0 1;
        content-align: left middle;
        background: $panel;
        border-top: heavy $surface;
    }

    #status-strip {
        height: 3;
        padding: 0 1;
        content-align: left middle;
        background: $panel;
        border-bottom: heavy $surface;
    }

    #inspector-tabs {
        height: 1fr;
        padding: 1;
    }

    DataTable {
        height: 1fr;
        border: round $surface;
    }

    #agent-log, #memory-log {
        height: 1fr;
        border: round $surface;
        background: $panel;
    }

    #workspace-pretty {
        height: 1fr;
        border: round $surface;
        background: $panel;
        padding: 1;
    }
    """

    BINDINGS = [
        ("ctrl+m", "toggle_mic", "Mic"),
        ("ctrl+l", "clear_chat", "Clear"),
        ("ctrl+q", "quit", "Quit"),
    ]

    def __init__(self, engine: Engine | None = None) -> None:
        super().__init__()
        self.engine: Engine = engine or MockEngine()
        self.mic_enabled = False
        self._last_goal = "-"
        self._last_tier = "-"
        self._activity = "IDLE"

        # For /play command
        self._episode_builder = None
        self._episode_processor = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Horizontal(id="body"):
            # Left: Chat
            with Vertical(id="chat-pane"):
                yield Static("Chat", classes="pane-title")
                yield RichLog(id="chat-log", wrap=True, highlight=True)
                with Horizontal(id="input-row"):
                    yield Input(placeholder="Type here or /play to load scenario...", id="chat-input")
                    yield Button("Send", id="send-btn", variant="primary")
                    yield Button("Mic: OFF", id="mic-btn")
                yield Static("", id="activity-bar")

            # Right: Inspector
            with Vertical(id="inspect-pane"):
                yield Static("System", classes="pane-title")
                yield Static("", id="status-strip")
                with TabbedContent(id="inspector-tabs"):
                    with TabPane("Sensors", id="sensors-tab"):
                        yield DataTable(id="sensors-table")
                    with TabPane("Stance", id="stance-tab"):
                        yield DataTable(id="stance-table")
                    with TabPane("Agents", id="agents-tab"):
                        yield RichLog(id="agent-log", wrap=True)
                    with TabPane("Workspace", id="workspace-tab"):
                        yield Pretty({}, id="workspace-pretty")
                    with TabPane("Critics", id="critics-tab"):
                        yield DataTable(id="critics-table")
                    with TabPane("Memory", id="memory-tab"):
                        yield RichLog(id="memory-log", wrap=True)

        yield Footer()

    async def on_mount(self) -> None:
        self._setup_tables()
        self._refresh_status_strip()
        self._refresh_activity_bar()

        # Start engine
        await self.engine.start()

        chat = self.query_one("#chat-log", RichLog)
        chat.write(Panel(
            Text("Rilai TUI online. Type a message or /play to load a scenario.", style="bold"),
            title="boot",
            border_style="dim"
        ))

    async def on_unmount(self) -> None:
        await self.engine.stop()

    def _setup_tables(self) -> None:
        sensors = self.query_one("#sensors-table", DataTable)
        sensors.add_columns("sensor", "p", "evidence")
        sensors.cursor_type = "row"

        stance = self.query_one("#stance-table", DataTable)
        stance.add_columns("metric", "value")
        stance.cursor_type = "row"

        # Seed stance rows (stable keys so we can update cells)
        for metric in ["valence", "arousal", "certainty", "safety", "closeness", "curiosity", "strain", "goal", "tier"]:
            stance.add_row(metric, "-", key=metric)

        # Critics table
        critics = self.query_one("#critics-table", DataTable)
        critics.add_columns("critic", "pass", "reason")
        critics.cursor_type = "row"

    def _refresh_status_strip(self) -> None:
        mode = "LISTEN" if self.mic_enabled else "TYPE"
        goal = self._last_goal
        tier = self._last_tier

        text = (
            f"[bold]{mode}[/]  "
            f"[dim]goal:[/] [bold]{goal}[/]   "
            f"[dim]tier:[/] [bold]{tier}[/]"
        )
        self.query_one("#status-strip", Static).update(text)

    def _refresh_activity_bar(self) -> None:
        activity = self._activity
        style = {
            "IDLE": "dim",
            "SENSING": "green",
            "THINKING": "yellow",
            "DAYDREAMING": "cyan",
            "ALERT": "red bold",
        }.get(activity, "")

        text = f"Activity: [{style}]{activity}[/]"
        self.query_one("#activity-bar", Static).update(text)

    def _set_activity(self, activity: str) -> None:
        self._activity = activity
        self._refresh_activity_bar()

    def _chat_bubble(self, who: str, text: str, right: bool = False) -> Panel:
        title = "you" if who == "user" else who
        style = "blue" if who == "user" else "green" if who == "assistant" else "dim"
        panel = Panel(Text(text), title=title, border_style=style, padding=(0, 1))
        return Align.right(panel) if right else panel

    def _chat_utterance(self, speaker: str, text: str, timestamp: str = "") -> Panel:
        """Format an utterance from /play replay."""
        title = f"{speaker}" + (f" [{timestamp}]" if timestamp else "")
        style = "blue" if speaker == "you" else "dim"
        return Panel(Text(text), title=title, border_style=style, padding=(0, 1))

    def _chat_system(self, text: str) -> None:
        """Add a system message to chat."""
        chat = self.query_one("#chat-log", RichLog)
        chat.write(Panel(Text(text, style="italic"), border_style="dim"))

    async def _run_turn(self, user_text: str) -> None:
        """Process user input through the engine."""
        self._set_activity("SENSING")

        async for event in self.engine.stream_turn(user_text):
            self._apply_event(event)

        self._set_activity("IDLE")

    def _apply_event(self, event: EngineEvent) -> None:
        """Apply an engine event to update the TUI."""
        if event.kind == "sensors":
            table = self.query_one("#sensors-table", DataTable)
            for sensor, (p, ev) in event.payload.items():
                try:
                    table.update_cell(sensor, "p", f"{p:.2f}")
                    table.update_cell(sensor, "evidence", ev or "")
                except Exception:
                    table.add_row(sensor, f"{p:.2f}", ev or "", key=sensor)

        elif event.kind == "stance":
            table = self.query_one("#stance-table", DataTable)
            for k, v in event.payload.items():
                if k == "goal":
                    self._last_goal = str(v)
                    self._refresh_status_strip()
                if k == "tier":
                    self._last_tier = str(v)
                    self._refresh_status_strip()
                try:
                    table.update_cell(k, "value", f"{v}" if isinstance(v, str) else f"{v:.2f}")
                except Exception:
                    pass  # Row doesn't exist yet

        elif event.kind == "agent_log":
            self.query_one("#agent-log", RichLog).write(event.payload["line"])

        elif event.kind == "workspace":
            self.query_one("#workspace-pretty", Pretty).update(event.payload)

        elif event.kind == "memory":
            memory_log = self.query_one("#memory-log", RichLog)
            if "line" in event.payload:
                memory_log.write(event.payload["line"])
            elif "summary" in event.payload:
                # Display memory summary from real engine
                summary = event.payload["summary"]
                if isinstance(summary, dict):
                    if summary.get("summary"):
                        memory_log.write(f"[dim]Summary:[/] {summary.get('summary', '-')}")
                    for ev in summary.get("evidence", [])[:5]:
                        memory_log.write(f"  [cyan]evidence:[/] {ev}")
                    for hyp in summary.get("hypotheses", [])[:3]:
                        memory_log.write(f"  [yellow]hypothesis:[/] {hyp}")
                elif isinstance(summary, str) and summary:
                    memory_log.write(summary)

        elif event.kind == "critics":
            table = self.query_one("#critics-table", DataTable)
            table.clear()
            for critic in event.payload.get("results", []):
                passed = "[green]✓[/]" if critic.get("passed") else "[red]✗[/]"
                table.add_row(
                    critic.get("critic_name", critic.get("name", "?")),
                    passed,
                    (critic.get("reason", "")[:50] + "...") if len(critic.get("reason", "")) > 50 else critic.get("reason", ""),
                )

        elif event.kind == "assistant":
            chat = self.query_one("#chat-log", RichLog)
            chat.write(self._chat_bubble("assistant", event.payload["text"], right=False))

        elif event.kind == "activity":
            self._set_activity(event.payload.get("state", "IDLE"))

    def _send_user_text(self, text: str) -> None:
        """Handle user input (message or command)."""
        text = text.strip()
        if not text:
            return

        # Handle slash commands
        if text.startswith("/"):
            self._handle_command(text)
            return

        # Regular message
        chat = self.query_one("#chat-log", RichLog)
        chat.write(self._chat_bubble("user", text, right=True))

        # Kick off streaming turn processing
        self.run_worker(self._run_turn(text), name="turn", group="turn", exclusive=True)

    def _handle_command(self, text: str) -> None:
        """Handle slash commands."""
        parts = text[1:].split(maxsplit=1)
        cmd = parts[0].lower() if parts else ""
        args = parts[1] if len(parts) > 1 else ""

        if cmd == "play":
            self.run_worker(self._cmd_play(args), name="play", exclusive=True)
        elif cmd == "clear":
            self.action_clear_chat()
        elif cmd == "help":
            self._show_help()
        else:
            self._chat_system(f"Unknown command: /{cmd}")

    def _show_help(self) -> None:
        """Show available commands."""
        help_text = """Available commands:
  /play        - Select and replay a scenario
  /play <name> - Replay a specific scenario
  /clear       - Clear chat and inspector
  /help        - Show this help"""
        self._chat_system(help_text)

    async def _cmd_play(self, args: str) -> None:
        """Handle /play command."""
        scenarios_dir = Path("scenarios")

        if not scenarios_dir.exists():
            self._chat_system(f"No scenarios directory found at: {scenarios_dir}")
            return

        scenarios = list(scenarios_dir.glob("*.jsonl"))
        if not scenarios:
            self._chat_system("No scenario files found in scenarios/")
            return

        if args:
            # Direct play
            matching = [s for s in scenarios if args in s.stem]
            if not matching:
                self._chat_system(f"No scenario matching: {args}")
                return
            scenario_path = matching[0]
        else:
            # Show selection modal
            result = await self.push_screen_wait(ScenarioSelectScreen(scenarios))
            if result is None:
                return
            scenario_path = Path(result)

        await self._replay_scenario(scenario_path)

    async def _replay_scenario(self, path: Path) -> None:
        """Replay a scenario with live visualization."""
        from rilai.adapters.protocol import PlaybackMode
        from rilai.adapters.synthetic import SyntheticTextAdapter, ChunkingConfig
        from rilai.brain.episode_builder import EpisodeBuilder, EpisodeBuilderConfig
        from rilai.episodes.processor import EpisodeProcessor

        self._chat_system(f"Loading scenario: {path.name}")

        # Clear previous state
        self.action_clear_chat()

        # Initialize components
        adapter = SyntheticTextAdapter(
            scenario_path=path,
            mode=PlaybackMode.FAST_FORWARD,
            chunking=ChunkingConfig(enable_chunking=False, enable_merging=False),
        )

        episode_builder = EpisodeBuilder(config=EpisodeBuilderConfig())
        episode_processor = EpisodeProcessor()

        self._set_activity("SENSING")

        try:
            await adapter.start()

            async for utterance in adapter.stream():
                # 1. Show utterance in chat
                chat = self.query_one("#chat-log", RichLog)
                timestamp = utterance.ts_start.strftime("%H:%M:%S")
                chat.write(self._chat_utterance(
                    utterance.speaker_id,
                    utterance.text,
                    timestamp
                ))
                await asyncio.sleep(0.25)  # Pause to see utterance

                # 2. Process through episode builder
                episode = await episode_builder.process(utterance)

                # 3. If episode completed, extract and display evidence
                if episode:
                    self._set_activity("THINKING")

                    # Extract evidence
                    evidence = episode_processor.extract_evidence(episode)
                    commitments = episode_processor.extract_commitments(episode)
                    decisions = episode_processor.extract_decisions(episode)

                    # Update sensors panel with evidence types
                    sensors_table = self.query_one("#sensors-table", DataTable)
                    evidence_counts = {}
                    for shard in evidence:
                        evidence_counts[shard.type] = evidence_counts.get(shard.type, 0) + 1

                    for etype, count in evidence_counts.items():
                        try:
                            sensors_table.update_cell(etype, "p", f"{count}")
                        except Exception:
                            sensors_table.add_row(etype, f"{count}", "", key=etype)

                    await asyncio.sleep(0.15)

                    # Update workspace
                    workspace_data = {
                        "episode_id": episode.episode_id,
                        "turn_count": episode.turn_count,
                        "word_count": episode.word_count,
                        "evidence_count": len(evidence),
                        "commitments": len(commitments),
                        "decisions": len(decisions),
                    }
                    self.query_one("#workspace-pretty", Pretty).update(workspace_data)
                    await asyncio.sleep(0.15)

                    # Log evidence to agents panel
                    agent_log = self.query_one("#agent-log", RichLog)
                    for shard in evidence[:5]:  # Limit to avoid spam
                        agent_log.write(f"[{shard.type}] {shard.quote[:60]}...")
                        await asyncio.sleep(0.08)

                    # Log commitments/decisions to memory
                    memory_log = self.query_one("#memory-log", RichLog)
                    for c in commitments[:3]:
                        memory_log.write(f"[commitment] {c.what[:50]}...")
                    for d in decisions[:3]:
                        memory_log.write(f"[decision] {d.what[:50]}...")

                    self._set_activity("SENSING")

                # Small delay between utterances
                await asyncio.sleep(0.15)

            # Flush final episode
            final_episode = await episode_builder.flush()
            if final_episode:
                self._set_activity("THINKING")
                evidence = episode_processor.extract_evidence(final_episode)
                agent_log = self.query_one("#agent-log", RichLog)
                for shard in evidence[:5]:
                    agent_log.write(f"[{shard.type}] {shard.quote[:60]}...")
                    await asyncio.sleep(0.08)

        finally:
            await adapter.stop()
            self._set_activity("IDLE")

        self._chat_system(f"Scenario complete: {path.name}")

    @on(Input.Submitted, "#chat-input")
    def on_chat_input_submitted(self, event: Input.Submitted) -> None:
        self._send_user_text(event.value)
        event.input.value = ""

    @on(Button.Pressed, "#send-btn")
    def on_send_pressed(self) -> None:
        inp = self.query_one("#chat-input", Input)
        self._send_user_text(inp.value)
        inp.value = ""

    @on(Button.Pressed, "#mic-btn")
    def on_mic_pressed(self) -> None:
        self.action_toggle_mic()

    def action_toggle_mic(self) -> None:
        """Toggle microphone (stub for future voice)."""
        self.mic_enabled = not self.mic_enabled
        self.query_one("#mic-btn", Button).label = "Mic: ON" if self.mic_enabled else "Mic: OFF"
        self._refresh_status_strip()

    def action_clear_chat(self) -> None:
        """Clear chat and inspector panels."""
        self.query_one("#chat-log", RichLog).clear()
        self.query_one("#agent-log", RichLog).clear()
        self.query_one("#memory-log", RichLog).clear()
        self.query_one("#workspace-pretty", Pretty).update({})

        # Clear sensors table
        sensors = self.query_one("#sensors-table", DataTable)
        sensors.clear()

        # Reset stance table
        stance = self.query_one("#stance-table", DataTable)
        for metric in ["valence", "arousal", "certainty", "safety", "closeness", "curiosity", "strain", "goal", "tier"]:
            try:
                stance.update_cell(metric, "value", "-")
            except Exception:
                pass  # Row doesn't exist

        # Clear critics table
        critics = self.query_one("#critics-table", DataTable)
        critics.clear()

        self._last_goal = "-"
        self._last_tier = "-"
        self._refresh_status_strip()


# Allow running directly
if __name__ == "__main__":
    RilaiTUI().run()
