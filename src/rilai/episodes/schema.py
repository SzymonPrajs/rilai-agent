"""
Episode Data Structures

Defines the core data structures for episode segmentation.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


@dataclass
class SpeechTurn:
    """A single speaker turn within an episode.

    A turn represents a contiguous segment of speech from one speaker.
    Multiple consecutive utterances from the same speaker are merged.
    """

    turn_id: str
    speaker: str  # Speaker ID or "unknown"
    text: str
    start_ts: datetime
    end_ts: datetime
    confidence: float = 1.0

    @property
    def duration_ms(self) -> int:
        """Get turn duration in milliseconds."""
        return int((self.end_ts - self.start_ts).total_seconds() * 1000)

    @property
    def word_count(self) -> int:
        """Get word count."""
        return len(self.text.split())

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "turn_id": self.turn_id,
            "speaker": self.speaker,
            "text": self.text,
            "start_ts": self.start_ts.isoformat(),
            "end_ts": self.end_ts.isoformat(),
            "confidence": self.confidence,
            "duration_ms": self.duration_ms,
            "word_count": self.word_count,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SpeechTurn":
        """Create from dictionary."""
        return cls(
            turn_id=data["turn_id"],
            speaker=data["speaker"],
            text=data["text"],
            start_ts=datetime.fromisoformat(data["start_ts"]),
            end_ts=datetime.fromisoformat(data["end_ts"]),
            confidence=data.get("confidence", 1.0),
        )

    @classmethod
    def create(
        cls,
        speaker: str,
        text: str,
        start_ts: datetime | None = None,
        end_ts: datetime | None = None,
        confidence: float = 1.0,
    ) -> "SpeechTurn":
        """Create a new turn with auto-generated ID."""
        now = datetime.now()
        return cls(
            turn_id=f"turn_{uuid.uuid4().hex[:8]}",
            speaker=speaker or "unknown",
            text=text,
            start_ts=start_ts or now,
            end_ts=end_ts or now,
            confidence=confidence,
        )


@dataclass
class Episode:
    """A segmented conversation episode.

    Episodes are discrete units of conversation bounded by:
    - Extended silence (>5s)
    - Topic shifts
    - Explicit boundary markers ("okay so", "anyway")
    - Time limits (max 5 minutes)
    """

    episode_id: str
    start_ts: datetime
    end_ts: datetime
    speakers: list[str]  # All speakers in episode
    turns: list[SpeechTurn]  # Ordered speech turns
    topic_tags: list[str] = field(default_factory=list)
    intensity: float = 0.0  # 0-1, based on emotional keywords/energy
    boundary_type: Literal["silence", "topic", "explicit", "time"] = "silence"

    # Metadata
    session_id: str = ""
    source: Literal["mic", "replay"] = "mic"

    @property
    def duration_ms(self) -> int:
        """Get episode duration in milliseconds."""
        return int((self.end_ts - self.start_ts).total_seconds() * 1000)

    @property
    def full_text(self) -> str:
        """Get full episode text with speaker labels."""
        return "\n".join(f"[{t.speaker}]: {t.text}" for t in self.turns)

    @property
    def plain_text(self) -> str:
        """Get full episode text without speaker labels."""
        return " ".join(t.text for t in self.turns)

    @property
    def word_count(self) -> int:
        """Get total word count."""
        return sum(t.word_count for t in self.turns)

    @property
    def turn_count(self) -> int:
        """Get number of turns."""
        return len(self.turns)

    @property
    def unique_speakers(self) -> int:
        """Get number of unique speakers."""
        return len(set(self.speakers))

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "episode_id": self.episode_id,
            "start_ts": self.start_ts.isoformat(),
            "end_ts": self.end_ts.isoformat(),
            "speakers": self.speakers,
            "turns": [t.to_dict() for t in self.turns],
            "topic_tags": self.topic_tags,
            "intensity": self.intensity,
            "boundary_type": self.boundary_type,
            "duration_ms": self.duration_ms,
            "word_count": self.word_count,
            "session_id": self.session_id,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Episode":
        """Create from dictionary."""
        return cls(
            episode_id=data["episode_id"],
            start_ts=datetime.fromisoformat(data["start_ts"]),
            end_ts=datetime.fromisoformat(data["end_ts"]),
            speakers=data["speakers"],
            turns=[SpeechTurn.from_dict(t) for t in data["turns"]],
            topic_tags=data.get("topic_tags", []),
            intensity=data.get("intensity", 0.0),
            boundary_type=data.get("boundary_type", "silence"),
            session_id=data.get("session_id", ""),
            source=data.get("source", "mic"),
        )

    @classmethod
    def create(
        cls,
        turns: list[SpeechTurn],
        boundary_type: Literal["silence", "topic", "explicit", "time"] = "silence",
        session_id: str = "",
        source: Literal["mic", "replay"] = "mic",
    ) -> "Episode":
        """Create a new episode from turns."""
        if not turns:
            raise ValueError("Episode must have at least one turn")

        speakers = list(set(t.speaker for t in turns))
        start_ts = min(t.start_ts for t in turns)
        end_ts = max(t.end_ts for t in turns)

        return cls(
            episode_id=f"ep_{uuid.uuid4().hex[:8]}",
            start_ts=start_ts,
            end_ts=end_ts,
            speakers=speakers,
            turns=turns,
            boundary_type=boundary_type,
            session_id=session_id,
            source=source,
        )

    def get_speaker_text(self, speaker: str) -> str:
        """Get all text from a specific speaker."""
        return " ".join(t.text for t in self.turns if t.speaker == speaker)

    def get_last_n_turns(self, n: int = 5) -> list[SpeechTurn]:
        """Get the last N turns."""
        return self.turns[-n:]

    def merge_with(self, other: "Episode") -> "Episode":
        """Merge with another episode."""
        all_turns = sorted(
            self.turns + other.turns,
            key=lambda t: t.start_ts,
        )
        speakers = list(set(self.speakers + other.speakers))
        topic_tags = list(set(self.topic_tags + other.topic_tags))

        return Episode(
            episode_id=f"ep_{uuid.uuid4().hex[:8]}",
            start_ts=min(self.start_ts, other.start_ts),
            end_ts=max(self.end_ts, other.end_ts),
            speakers=speakers,
            turns=all_turns,
            topic_tags=topic_tags,
            intensity=max(self.intensity, other.intensity),
            boundary_type="time",  # Merged episodes use time boundary
            session_id=self.session_id,
            source=self.source,
        )
