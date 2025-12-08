"""
Audio Capture Sources

Provides MicCapture for live microphone input and TranscriptReplay for testing.
"""

import asyncio
import json
import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class AudioCaptureConfig:
    """Configuration for audio capture."""

    sample_rate: int = 16000
    channels: int = 1
    chunk_duration_ms: int = 100  # 100ms chunks
    vad_threshold: float = 0.5  # Silero VAD threshold
    silence_timeout_ms: int = 2000  # End speech after 2s silence
    device_index: int | None = None  # macOS audio device


@dataclass
class AudioChunk:
    """A chunk of audio data from capture."""

    chunk_id: str
    data: bytes  # Raw PCM audio
    sample_rate: int  # e.g., 16000
    channels: int  # 1 (mono) or 2 (stereo)
    timestamp: datetime
    duration_ms: int
    is_speech: bool = False  # Set by VAD later
    energy_db: float = 0.0  # Volume level
    source: Literal["mic", "replay"] = "mic"


@dataclass
class TranscriptEntry:
    """A single entry in a transcript file."""

    timestamp_ms: int
    speaker: str
    text: str


@dataclass
class TranscriptChunk:
    """A transcript chunk from replay mode."""

    chunk_id: str
    text: str
    speaker: str
    timestamp: datetime
    original_timestamp_ms: int
    source: Literal["replay"] = "replay"


class AudioSource(ABC):
    """Abstract base for audio sources."""

    @abstractmethod
    async def start(self) -> None:
        """Start capturing audio."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Stop capturing audio."""
        ...

    @abstractmethod
    async def read_chunk(self) -> AudioChunk | TranscriptChunk | None:
        """Read next audio/transcript chunk."""
        ...

    @property
    @abstractmethod
    def is_running(self) -> bool:
        """Check if source is currently running."""
        ...


class MicCapture(AudioSource):
    """macOS microphone capture using sounddevice."""

    def __init__(self, config: AudioCaptureConfig | None = None):
        self.config = config or AudioCaptureConfig()
        self._stream = None
        self._buffer: asyncio.Queue[AudioChunk] = asyncio.Queue()
        self._running = False
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        """Initialize and start microphone stream."""
        try:
            import sounddevice as sd
        except ImportError:
            raise ImportError(
                "sounddevice is required for microphone capture. "
                "Install with: pip install sounddevice"
            )

        self._loop = asyncio.get_event_loop()
        self._running = True

        # Calculate blocksize from chunk duration
        blocksize = int(
            self.config.sample_rate * self.config.chunk_duration_ms / 1000
        )

        # Use callback-based streaming
        self._stream = sd.InputStream(
            samplerate=self.config.sample_rate,
            channels=self.config.channels,
            dtype="int16",
            blocksize=blocksize,
            callback=self._audio_callback,
            device=self.config.device_index,
        )
        self._stream.start()
        logger.info(
            f"Microphone capture started (sample_rate={self.config.sample_rate}, "
            f"chunk_ms={self.config.chunk_duration_ms})"
        )

    def _audio_callback(self, indata, frames, time_info, status):
        """Callback for sounddevice stream."""
        if status:
            logger.warning(f"Audio callback status: {status}")

        if self._running and self._loop:
            chunk = AudioChunk(
                chunk_id=f"mic-{uuid.uuid4().hex[:8]}",
                data=indata.tobytes(),
                sample_rate=self.config.sample_rate,
                channels=self.config.channels,
                timestamp=datetime.now(),
                duration_ms=self.config.chunk_duration_ms,
                is_speech=False,  # Set by VAD later
                energy_db=self._compute_energy(indata),
                source="mic",
            )
            # Thread-safe put to async queue
            self._loop.call_soon_threadsafe(self._buffer.put_nowait, chunk)

    @staticmethod
    def _compute_energy(audio: np.ndarray) -> float:
        """Compute energy in dB."""
        rms = np.sqrt(np.mean(audio.astype(float) ** 2))
        return 20 * np.log10(max(rms, 1e-10))

    async def read_chunk(self) -> AudioChunk | None:
        """Read next chunk from buffer."""
        if not self._running:
            return None
        try:
            return await asyncio.wait_for(self._buffer.get(), timeout=1.0)
        except asyncio.TimeoutError:
            return None

    async def stop(self) -> None:
        """Stop microphone stream."""
        self._running = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        logger.info("Microphone capture stopped")


class TranscriptReplay(AudioSource):
    """Replay pre-recorded transcripts for testing.

    Bypasses actual audio capture and directly feeds transcript
    at accelerated speed.

    Transcript format (JSONL):
        {"timestamp_ms": 0, "speaker": "user", "text": "Hello, how are you?"}
        {"timestamp_ms": 1500, "speaker": "assistant", "text": "I'm doing well."}

    Or JSON:
        {"entries": [{"timestamp_ms": 0, "speaker": "user", "text": "..."}]}
    """

    def __init__(
        self,
        transcript_path: Path | str,
        speed_multiplier: float = 10.0,  # 10x faster than real-time
    ):
        self.transcript_path = Path(transcript_path)
        self.speed_multiplier = speed_multiplier
        self._entries: list[TranscriptEntry] = []
        self._current_index = 0
        self._running = False
        self._start_time: datetime | None = None

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        """Load transcript and start replay."""
        self._entries = self._load_transcript()
        self._current_index = 0
        self._running = True
        self._start_time = datetime.now()
        logger.info(
            f"Transcript replay started: {len(self._entries)} entries, "
            f"{self.speed_multiplier}x speed"
        )

    def _load_transcript(self) -> list[TranscriptEntry]:
        """Load transcript from JSON/JSONL file."""
        entries = []

        if not self.transcript_path.exists():
            raise FileNotFoundError(f"Transcript not found: {self.transcript_path}")

        with open(self.transcript_path) as f:
            if self.transcript_path.suffix == ".jsonl":
                for line in f:
                    line = line.strip()
                    if line:
                        data = json.loads(line)
                        entries.append(
                            TranscriptEntry(
                                timestamp_ms=data.get("timestamp_ms", 0),
                                speaker=data.get("speaker", "unknown"),
                                text=data.get("text", ""),
                            )
                        )
            else:
                data = json.load(f)
                # Support both {"entries": [...]} and direct array
                entry_list = data.get("entries", data) if isinstance(data, dict) else data
                for entry in entry_list:
                    entries.append(
                        TranscriptEntry(
                            timestamp_ms=entry.get("timestamp_ms", 0),
                            speaker=entry.get("speaker", "unknown"),
                            text=entry.get("text", ""),
                        )
                    )

        return sorted(entries, key=lambda e: e.timestamp_ms)

    async def read_chunk(self) -> TranscriptChunk | None:
        """Get next transcript entry based on replay timing."""
        if not self._running or self._current_index >= len(self._entries):
            return None

        entry = self._entries[self._current_index]

        # Calculate when this entry should be delivered
        elapsed_ms = (datetime.now() - self._start_time).total_seconds() * 1000
        target_ms = entry.timestamp_ms / self.speed_multiplier

        if elapsed_ms < target_ms:
            await asyncio.sleep((target_ms - elapsed_ms) / 1000)

        self._current_index += 1

        return TranscriptChunk(
            chunk_id=f"replay-{self._current_index}",
            text=entry.text,
            speaker=entry.speaker,
            timestamp=datetime.now(),
            original_timestamp_ms=entry.timestamp_ms,
            source="replay",
        )

    async def stop(self) -> None:
        """Stop replay."""
        self._running = False
        logger.info("Transcript replay stopped")

    def reset(self) -> None:
        """Reset replay to beginning."""
        self._current_index = 0
        self._start_time = datetime.now()

    @property
    def progress(self) -> float:
        """Get replay progress (0.0 to 1.0)."""
        if not self._entries:
            return 0.0
        return self._current_index / len(self._entries)

    @property
    def remaining_entries(self) -> int:
        """Get number of remaining entries."""
        return max(0, len(self._entries) - self._current_index)
