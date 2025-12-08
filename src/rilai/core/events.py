"""Internal event bus for Rilai v2.

Replaces WebSocket-based communication with internal async events.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any, Callable, Coroutine


class EventType(Enum):
    """Types of events in the system."""

    # User input events
    USER_MESSAGE = auto()
    USER_COMMAND = auto()

    # Processing events
    PROCESSING_STARTED = auto()
    PROCESSING_COMPLETED = auto()

    # Agency events
    AGENCY_STARTED = auto()
    AGENCY_COMPLETED = auto()
    AGENT_STARTED = auto()
    AGENT_COMPLETED = auto()

    # Deliberation events
    DELIBERATION_ROUND_STARTED = auto()
    DELIBERATION_ROUND_COMPLETED = auto()
    CONSENSUS_REACHED = auto()

    # Council events
    COUNCIL_STARTED = auto()
    COUNCIL_DECISION = auto()
    COUNCIL_COMPLETED = auto()

    # Voice events
    VOICE_STARTED = auto()
    VOICE_COMPLETED = auto()

    # Brain daemon events
    DAEMON_STARTED = auto()
    DAEMON_STOPPED = auto()
    DAEMON_TICK = auto()
    DAEMON_WATCHER_ALERT = auto()
    PROACTIVE_MESSAGE = auto()

    # Audio capture events (ambient mode)
    AUDIO_CAPTURE_STARTED = auto()
    AUDIO_CAPTURE_STOPPED = auto()
    SPEECH_DETECTED = auto()
    SPEECH_ENDED = auto()
    TRANSCRIPT_SEGMENT = auto()

    # Episode events
    EPISODE_STARTED = auto()
    EPISODE_COMPLETED = auto()
    EPISODE_BOUNDARY = auto()

    # Ambient mode events
    MODE_TRANSITION = auto()
    STAKES_UPDATED = auto()
    COMMITMENT_EXTRACTED = auto()
    DECISION_DETECTED = auto()

    # Hypothesis events (daydream mode)
    HYPOTHESIS_GENERATED = auto()
    HYPOTHESIS_VALIDATED = auto()
    HYPOTHESIS_INVALIDATED = auto()

    # Proactive nudge events
    NUDGE_PREPARED = auto()
    NUDGE_DELIVERED = auto()
    NUDGE_SUPPRESSED = auto()
    NUDGE_DISMISSED = auto()

    # System events
    SESSION_STARTED = auto()
    SESSION_ENDED = auto()
    ERROR = auto()


@dataclass
class Event:
    """An event in the system."""

    type: EventType
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)

    def __repr__(self) -> str:
        return f"Event({self.type.name}, {self.data})"


# Type alias for event handlers
EventHandler = Callable[[Event], Coroutine[Any, Any, None]]


class EventBus:
    """Async event bus for internal communication.

    Components can subscribe to events and emit events.
    This replaces WebSocket-based frontend communication.
    """

    def __init__(self) -> None:
        self._handlers: dict[EventType, list[EventHandler]] = {}
        self._all_handlers: list[EventHandler] = []  # Handlers for all events
        self._event_queue: asyncio.Queue[Event] = asyncio.Queue()
        self._running = False
        self._task: asyncio.Task | None = None

    def subscribe(
        self,
        event_type: EventType | None,
        handler: EventHandler,
    ) -> None:
        """Subscribe to an event type.

        Args:
            event_type: The event type to subscribe to, or None for all events
            handler: Async function to call when event fires
        """
        if event_type is None:
            self._all_handlers.append(handler)
        else:
            if event_type not in self._handlers:
                self._handlers[event_type] = []
            self._handlers[event_type].append(handler)

    def unsubscribe(
        self,
        event_type: EventType | None,
        handler: EventHandler,
    ) -> None:
        """Unsubscribe from an event type."""
        if event_type is None:
            if handler in self._all_handlers:
                self._all_handlers.remove(handler)
        else:
            if event_type in self._handlers and handler in self._handlers[event_type]:
                self._handlers[event_type].remove(handler)

    async def emit(self, event: Event) -> None:
        """Emit an event to all subscribers.

        Events are processed asynchronously in order.
        """
        await self._event_queue.put(event)

    async def emit_now(self, event: Event) -> None:
        """Emit an event and wait for all handlers to complete.

        Use for events that need immediate processing.
        """
        await self._dispatch(event)

    async def _dispatch(self, event: Event) -> None:
        """Dispatch event to all matching handlers."""
        handlers = list(self._all_handlers)

        if event.type in self._handlers:
            handlers.extend(self._handlers[event.type])

        if handlers:
            await asyncio.gather(
                *(handler(event) for handler in handlers),
                return_exceptions=True,
            )

    async def _process_queue(self) -> None:
        """Process events from the queue."""
        while self._running:
            try:
                event = await asyncio.wait_for(
                    self._event_queue.get(),
                    timeout=1.0,
                )
                await self._dispatch(event)
                self._event_queue.task_done()
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    async def start(self) -> None:
        """Start processing events."""
        self._running = True
        self._task = asyncio.create_task(self._process_queue())

    async def stop(self) -> None:
        """Stop processing events."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def clear(self) -> None:
        """Clear all handlers."""
        self._handlers.clear()
        self._all_handlers.clear()


# Global event bus instance
event_bus = EventBus()
