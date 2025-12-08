"""
SyntheticTextAdapter

Reads JSONL scenario files and emits UtteranceEvents.
Supports both FAST_FORWARD and REALTIME_SIM playback modes.
Includes STT simulation (chunking, merging) to avoid overfitting to clean input.
"""

import asyncio
import json
import logging
import re
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from rilai.adapters.protocol import BaseInputAdapter, PlaybackMode
from rilai.core.utterance import UtteranceEvent

logger = logging.getLogger(__name__)


@dataclass
class ScenarioLine:
    """A single line from a JSONL scenario file."""

    timestamp: datetime
    speaker: str
    channel: str
    text: str
    meta: dict = field(default_factory=dict)
    line_number: int = 0

    @classmethod
    def from_dict(cls, data: dict, line_number: int, base_date: datetime) -> "ScenarioLine":
        """Parse a scenario line from a dict.

        Args:
            data: The parsed JSON dict
            line_number: Line number in the file (1-indexed)
            base_date: Base date to combine with time-only strings

        Returns:
            ScenarioLine instance
        """
        # Parse timestamp - can be "HH:MM:SS" or full ISO format
        t = data.get("t") or data.get("timestamp") or data.get("time")
        if isinstance(t, str):
            if "T" in t or "-" in t:
                # Full ISO format
                timestamp = datetime.fromisoformat(t)
            else:
                # Time only - combine with base date
                parts = t.split(":")
                hour = int(parts[0])
                minute = int(parts[1]) if len(parts) > 1 else 0
                second = int(parts[2]) if len(parts) > 2 else 0
                timestamp = base_date.replace(
                    hour=hour, minute=minute, second=second, microsecond=0
                )
        else:
            timestamp = base_date

        return cls(
            timestamp=timestamp,
            speaker=data.get("speaker", "unknown"),
            channel=data.get("channel", "default"),
            text=data.get("text", ""),
            meta=data.get("meta", {}),
            line_number=line_number,
        )


@dataclass
class ChunkingConfig:
    """Configuration for STT simulation (chunking/merging)."""

    # Maximum characters per chunk (split longer utterances)
    chunk_max_chars: int = 120

    # Merge consecutive utterances from same speaker within this window
    merge_window_sec: float = 3.0

    # Enabled flags
    enable_chunking: bool = True
    enable_merging: bool = True


class SyntheticTextAdapter(BaseInputAdapter):
    """Input adapter that reads JSONL scenario files.

    Scenario JSONL format:
    ```jsonl
    {"t": "09:12:08", "speaker": "you", "channel": "office", "text": "Morning!"}
    {"t": "09:12:15", "speaker": "coworker_1", "channel": "office", "text": "Hey!"}
    ```

    Supports:
    - FAST_FORWARD mode: Process entire scenario instantly
    - REALTIME_SIM mode: Respect timestamp delays
    - STT simulation: Chunk long utterances, merge consecutive same-speaker
    - Gap detection: Recognizes silence for daydream triggers
    """

    def __init__(
        self,
        scenario_path: str | Path,
        mode: PlaybackMode = PlaybackMode.FAST_FORWARD,
        chunking: ChunkingConfig | None = None,
        base_date: datetime | None = None,
        speed_multiplier: float = 1.0,
    ):
        """Initialize the synthetic adapter.

        Args:
            scenario_path: Path to JSONL scenario file
            mode: Playback mode (FAST_FORWARD or REALTIME_SIM)
            chunking: STT simulation config (defaults to enabled)
            base_date: Base date for time-only timestamps (defaults to today)
            speed_multiplier: Speed multiplier for REALTIME_SIM (2.0 = 2x speed)
        """
        super().__init__()
        self.scenario_path = Path(scenario_path)
        self.mode = mode
        self.chunking = chunking or ChunkingConfig()
        self.base_date = base_date or datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        self.speed_multiplier = speed_multiplier

        # State
        self._lines: list[ScenarioLine] = []
        self._current_index = 0

        # Statistics
        self._stats = {
            "lines_read": 0,
            "utterances_emitted": 0,
            "chunks_created": 0,
            "merges_performed": 0,
            "gaps_detected": 0,
        }

    @property
    def name(self) -> str:
        return f"SyntheticTextAdapter({self.scenario_path.name})"

    @property
    def stats(self) -> dict:
        return self._stats.copy()

    async def start(self) -> None:
        """Load the scenario file."""
        if self._running:
            logger.warning("Adapter already running")
            return

        if not self.scenario_path.exists():
            raise FileNotFoundError(f"Scenario file not found: {self.scenario_path}")

        # Load all lines
        self._lines = []
        with open(self.scenario_path, "r") as f:
            for i, line in enumerate(f, 1):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                try:
                    data = json.loads(line)
                    scenario_line = ScenarioLine.from_dict(data, i, self.base_date)
                    self._lines.append(scenario_line)
                except json.JSONDecodeError as e:
                    logger.warning(f"Skipping invalid JSON at line {i}: {e}")

        self._stats["lines_read"] = len(self._lines)
        self._current_index = 0
        self._running = True

        # Set initial simulated clock
        if self._lines:
            self._simulated_clock = self._lines[0].timestamp

        logger.info(
            f"Loaded scenario {self.scenario_path.name}: "
            f"{len(self._lines)} lines, mode={self.mode.value}"
        )

    async def stop(self) -> None:
        """Stop the adapter."""
        self._running = False
        logger.info(f"Adapter stopped. Stats: {self._stats}")

    async def stream(self) -> AsyncIterator[UtteranceEvent]:
        """Stream UtteranceEvents from the scenario.

        Yields:
            UtteranceEvent objects, with optional delays in REALTIME_SIM mode.
        """
        if not self._running:
            raise RuntimeError("Adapter not started. Call start() first.")

        # Apply merging if enabled
        if self.chunking.enable_merging:
            lines = self._merge_consecutive(self._lines)
        else:
            lines = self._lines

        last_timestamp: datetime | None = None

        for line in lines:
            if not self._running:
                break

            # Update simulated clock
            self._simulated_clock = line.timestamp

            # Handle delays in REALTIME_SIM mode
            if self.mode == PlaybackMode.REALTIME_SIM and last_timestamp:
                delay = (line.timestamp - last_timestamp).total_seconds()
                delay /= self.speed_multiplier
                if delay > 0:
                    # Detect significant gaps (for daydream triggers)
                    if delay > 30:  # 30+ seconds is a gap
                        self._stats["gaps_detected"] += 1
                        logger.debug(f"Gap detected: {delay:.1f}s")
                    await asyncio.sleep(delay)

            last_timestamp = line.timestamp

            # Apply chunking if enabled
            if self.chunking.enable_chunking and len(line.text) > self.chunking.chunk_max_chars:
                chunks = self._chunk_text(line.text)
                self._stats["chunks_created"] += len(chunks) - 1

                for i, chunk in enumerate(chunks):
                    # Distribute time across chunks
                    chunk_offset = timedelta(
                        seconds=(i * len(chunk)) / max(1, len(line.text)) * 2
                    )
                    utterance = self._line_to_utterance(
                        line,
                        text_override=chunk,
                        ts_offset=chunk_offset,
                    )
                    self._stats["utterances_emitted"] += 1
                    yield utterance
            else:
                utterance = self._line_to_utterance(line)
                self._stats["utterances_emitted"] += 1
                yield utterance

    def _line_to_utterance(
        self,
        line: ScenarioLine,
        text_override: str | None = None,
        ts_offset: timedelta | None = None,
    ) -> UtteranceEvent:
        """Convert a ScenarioLine to an UtteranceEvent."""
        text = text_override or line.text
        ts_start = line.timestamp
        if ts_offset:
            ts_start = ts_start + ts_offset

        # Estimate end time based on text length
        word_count = len(text.split())
        duration = timedelta(seconds=max(1.0, word_count / 2.5))

        # Extract tags from meta
        tags = []
        if "mode" in line.meta:
            tags.append(line.meta["mode"])
        if "tags" in line.meta:
            tags.extend(line.meta["tags"])

        return UtteranceEvent(
            event_id=str(uuid.uuid4()),
            ts_start=ts_start,
            ts_end=ts_start + duration,
            speaker_id=line.speaker,
            channel=line.channel,
            text=text,
            confidence=0.98,  # High confidence for synthetic
            tags=tags,
            source="synthetic",
            scenario_file=str(self.scenario_path),
            line_number=line.line_number,
        )

    def _merge_consecutive(self, lines: list[ScenarioLine]) -> list[ScenarioLine]:
        """Merge consecutive lines from the same speaker within merge window."""
        if not lines:
            return []

        merged = []
        current = lines[0]

        for next_line in lines[1:]:
            # Check if should merge
            same_speaker = next_line.speaker == current.speaker
            same_channel = next_line.channel == current.channel
            time_diff = (next_line.timestamp - current.timestamp).total_seconds()
            within_window = time_diff <= self.chunking.merge_window_sec

            if same_speaker and same_channel and within_window:
                # Merge into current
                current = ScenarioLine(
                    timestamp=current.timestamp,
                    speaker=current.speaker,
                    channel=current.channel,
                    text=current.text + " " + next_line.text,
                    meta={**current.meta, **next_line.meta},
                    line_number=current.line_number,
                )
                self._stats["merges_performed"] += 1
            else:
                merged.append(current)
                current = next_line

        merged.append(current)
        return merged

    def _chunk_text(self, text: str) -> list[str]:
        """Split text into chunks respecting word boundaries.

        Tries to split at sentence boundaries first, then word boundaries.
        """
        max_chars = self.chunking.chunk_max_chars

        if len(text) <= max_chars:
            return [text]

        chunks = []

        # Try to split at sentence boundaries first
        sentences = re.split(r"(?<=[.!?])\s+", text)

        current_chunk = ""
        for sentence in sentences:
            if len(current_chunk) + len(sentence) + 1 <= max_chars:
                current_chunk = (current_chunk + " " + sentence).strip()
            else:
                if current_chunk:
                    chunks.append(current_chunk)

                # If single sentence is too long, split by words
                if len(sentence) > max_chars:
                    words = sentence.split()
                    current_chunk = ""
                    for word in words:
                        if len(current_chunk) + len(word) + 1 <= max_chars:
                            current_chunk = (current_chunk + " " + word).strip()
                        else:
                            if current_chunk:
                                chunks.append(current_chunk)
                            current_chunk = word
                else:
                    current_chunk = sentence

        if current_chunk:
            chunks.append(current_chunk)

        return chunks

    def get_gap_times(self, min_gap_seconds: float = 30.0) -> list[datetime]:
        """Get timestamps of significant gaps in the scenario.

        Useful for knowing when daydream mode should trigger.

        Args:
            min_gap_seconds: Minimum gap duration to consider

        Returns:
            List of timestamps where gaps occur
        """
        gaps = []
        for i in range(1, len(self._lines)):
            prev = self._lines[i - 1]
            curr = self._lines[i]
            gap = (curr.timestamp - prev.timestamp).total_seconds()
            if gap >= min_gap_seconds:
                gaps.append(curr.timestamp)
        return gaps

    def get_timeline_summary(self) -> str:
        """Get a human-readable summary of the scenario timeline."""
        if not self._lines:
            return "Empty scenario"

        first = self._lines[0].timestamp
        last = self._lines[-1].timestamp
        duration = last - first

        speakers = set(line.speaker for line in self._lines)
        channels = set(line.channel for line in self._lines)

        return (
            f"Timeline: {first.strftime('%H:%M')} - {last.strftime('%H:%M')} "
            f"({duration.total_seconds() / 60:.0f} min)\n"
            f"Lines: {len(self._lines)}\n"
            f"Speakers: {', '.join(sorted(speakers))}\n"
            f"Channels: {', '.join(sorted(channels))}"
        )
