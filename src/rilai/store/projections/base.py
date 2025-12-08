"""Base class for projections."""

from abc import ABC, abstractmethod
from typing import Any

from rilai.contracts.events import EngineEvent


class Projection(ABC):
    """Base class for event projections.

    A projection maintains derived state from an event stream.
    It can be rebuilt from scratch by replaying events.
    """

    @abstractmethod
    def apply(self, event: EngineEvent) -> Any:
        """Apply an event to update projection state.

        Args:
            event: The event to apply

        Returns:
            Optional return value (e.g., UI updates)
        """
        pass

    @abstractmethod
    def reset(self) -> None:
        """Reset projection to initial state."""
        pass

    def rebuild_from(self, events: list[EngineEvent]) -> None:
        """Rebuild projection from a list of events.

        This is used to restore state from the event log.
        """
        self.reset()
        for event in events:
            self.apply(event)
