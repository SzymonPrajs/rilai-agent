"""
InputAdapter Protocol

Defines the interface that all input adapters must implement.
Both real audio and synthetic test adapters produce UtteranceEvents.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from datetime import datetime
from enum import Enum
from typing import Protocol, runtime_checkable

from rilai.core.utterance import UtteranceEvent


class PlaybackMode(Enum):
    """Playback modes for input adapters."""

    FAST_FORWARD = "fast"
    """Process entire scenario instantly (no sleep). For regression tests."""

    REALTIME_SIM = "realtime"
    """Use actual delays between timestamps. For live observation."""


@runtime_checkable
class InputAdapter(Protocol):
    """Protocol for input adapters.

    All input adapters (audio, synthetic) must implement this interface.
    They all produce UtteranceEvents as output.
    """

    @property
    def name(self) -> str:
        """Human-readable name of this adapter."""
        ...

    @property
    def is_running(self) -> bool:
        """Whether the adapter is currently running."""
        ...

    @property
    def simulated_clock(self) -> datetime | None:
        """Current simulated time (for synthetic adapters).

        Returns None for real-time adapters like audio.
        For synthetic adapters, returns the current position in the scenario.
        """
        ...

    async def start(self) -> None:
        """Start the adapter.

        For audio: Initialize mic capture, VAD, STT.
        For synthetic: Open the scenario file.
        """
        ...

    async def stop(self) -> None:
        """Stop the adapter.

        Clean up resources and flush any pending data.
        """
        ...

    def stream(self) -> AsyncIterator[UtteranceEvent]:
        """Stream UtteranceEvents from this adapter.

        Yields:
            UtteranceEvent objects as they become available.

        Note:
            For FAST_FORWARD mode, this yields all events as fast as possible.
            For REALTIME_SIM mode, this respects timestamp delays.
        """
        ...


class BaseInputAdapter(ABC):
    """Base class for input adapters with common functionality."""

    def __init__(self) -> None:
        self._running = False
        self._simulated_clock: datetime | None = None

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name of this adapter."""
        ...

    @property
    def is_running(self) -> bool:
        """Whether the adapter is currently running."""
        return self._running

    @property
    def simulated_clock(self) -> datetime | None:
        """Current simulated time."""
        return self._simulated_clock

    @abstractmethod
    async def start(self) -> None:
        """Start the adapter."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Stop the adapter."""
        ...

    @abstractmethod
    def stream(self) -> AsyncIterator[UtteranceEvent]:
        """Stream UtteranceEvents."""
        ...
