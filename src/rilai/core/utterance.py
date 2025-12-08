"""
UtteranceEvent - The canonical input event for ambient listening.

All input adapters (audio, synthetic) produce UtteranceEvents.
This is the single interface the downstream brain consumes.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
import uuid


@dataclass
class UtteranceEvent:
    """A single utterance from ambient listening.

    This is THE canonical event type that all input adapters produce.
    Everything downstream (episode segmentation, evidence extraction,
    memory, daydream) consumes only UtteranceEvents.

    Fields:
        event_id: Stable, unique identifier
        ts_start: Start timestamp (can be simulated for synthetic)
        ts_end: End timestamp
        speaker_id: Who is speaking ("you", "wife", "coworker_1", etc.)
        channel: Context/location ("office", "home", "meeting", etc.)
        text: The transcript segment
        confidence: STT confidence 0-1 (synthetic uses 0.95-1.0)
        tags: Optional tags (["chitchat", "work", "coding"])
        source: Where this came from ("audio" or "synthetic")
        scenario_file: For synthetic, the source file
        line_number: For synthetic, the line in the source file
    """

    event_id: str
    ts_start: datetime
    ts_end: datetime
    speaker_id: str
    channel: str
    text: str
    confidence: float = 0.95
    tags: list[str] = field(default_factory=list)

    # Provenance metadata
    source: Literal["audio", "synthetic"] = "audio"
    scenario_file: str | None = None
    line_number: int | None = None

    @classmethod
    def create(
        cls,
        text: str,
        speaker_id: str,
        channel: str,
        ts_start: datetime | None = None,
        ts_end: datetime | None = None,
        confidence: float = 0.95,
        tags: list[str] | None = None,
        source: Literal["audio", "synthetic"] = "audio",
        scenario_file: str | None = None,
        line_number: int | None = None,
    ) -> "UtteranceEvent":
        """Factory method to create an UtteranceEvent.

        Args:
            text: The transcript text
            speaker_id: Speaker identifier
            channel: Context/location
            ts_start: Start time (defaults to now)
            ts_end: End time (defaults to ts_start + estimated duration)
            confidence: STT confidence
            tags: Optional tags
            source: Input source type
            scenario_file: Source file for synthetic
            line_number: Line number for synthetic

        Returns:
            New UtteranceEvent instance
        """
        now = datetime.now()
        start = ts_start or now

        # Estimate end time based on text length if not provided
        # Roughly 150 words per minute = 2.5 words per second
        if ts_end is None:
            word_count = len(text.split())
            duration_seconds = max(1.0, word_count / 2.5)
            from datetime import timedelta
            end = start + timedelta(seconds=duration_seconds)
        else:
            end = ts_end

        return cls(
            event_id=str(uuid.uuid4()),
            ts_start=start,
            ts_end=end,
            speaker_id=speaker_id,
            channel=channel,
            text=text,
            confidence=confidence,
            tags=tags or [],
            source=source,
            scenario_file=scenario_file,
            line_number=line_number,
        )

    @property
    def duration_ms(self) -> int:
        """Duration in milliseconds."""
        delta = self.ts_end - self.ts_start
        return int(delta.total_seconds() * 1000)

    @property
    def word_count(self) -> int:
        """Number of words in the utterance."""
        return len(self.text.split())

    @property
    def is_self(self) -> bool:
        """Whether this is the user speaking (not others)."""
        return self.speaker_id.lower() in ("you", "user", "me", "self")

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "event_id": self.event_id,
            "ts_start": self.ts_start.isoformat(),
            "ts_end": self.ts_end.isoformat(),
            "speaker_id": self.speaker_id,
            "channel": self.channel,
            "text": self.text,
            "confidence": self.confidence,
            "tags": self.tags,
            "source": self.source,
            "scenario_file": self.scenario_file,
            "line_number": self.line_number,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "UtteranceEvent":
        """Create from dictionary."""
        return cls(
            event_id=data["event_id"],
            ts_start=datetime.fromisoformat(data["ts_start"]),
            ts_end=datetime.fromisoformat(data["ts_end"]),
            speaker_id=data["speaker_id"],
            channel=data["channel"],
            text=data["text"],
            confidence=data.get("confidence", 0.95),
            tags=data.get("tags", []),
            source=data.get("source", "audio"),
            scenario_file=data.get("scenario_file"),
            line_number=data.get("line_number"),
        )

    def __repr__(self) -> str:
        return (
            f"UtteranceEvent(speaker={self.speaker_id!r}, "
            f"channel={self.channel!r}, "
            f"text={self.text[:50]!r}{'...' if len(self.text) > 50 else ''})"
        )
