"""
Audio Capture Service

Orchestrates the full audio pipeline:
- Audio capture (mic or replay)
- VAD processing
- STT streaming
- Episode segmentation
- Memory artifact creation
"""

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from rilai.audio.capture import (
    AudioCaptureConfig,
    AudioChunk,
    AudioSource,
    MicCapture,
    TranscriptChunk,
    TranscriptReplay,
)
from rilai.audio.stt import ElevenLabsSTTClient, MockSTTClient, TranscriptSegment
from rilai.audio.vad import SimpleEnergyVAD, VADProcessor
from rilai.core.events import Event, EventType, event_bus

if TYPE_CHECKING:
    from rilai.config import Config

logger = logging.getLogger(__name__)


class AudioCaptureService:
    """Orchestrates the full audio capture pipeline.

    Coordinates:
    - Audio capture (mic or replay)
    - VAD processing
    - STT streaming
    - Emits transcript segments for episode processing
    """

    def __init__(
        self,
        config: "Config",
        on_transcript: Callable[[TranscriptSegment], None] | None = None,
    ):
        """Initialize audio capture service.

        Args:
            config: Application configuration
            on_transcript: Callback for transcript segments
        """
        self.config = config
        self._on_transcript = on_transcript
        self._running = False

        # Components (initialized on start)
        self._audio_source: AudioSource | None = None
        self._vad: VADProcessor | SimpleEnergyVAD | None = None
        self._stt: ElevenLabsSTTClient | MockSTTClient | None = None

        # Tasks
        self._capture_task: asyncio.Task | None = None
        self._stt_receive_task: asyncio.Task | None = None

        # Statistics
        self._stats = {
            "chunks_processed": 0,
            "speech_chunks": 0,
            "transcripts_received": 0,
            "errors": 0,
        }

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def stats(self) -> dict:
        return self._stats.copy()

    async def start(self) -> None:
        """Start the audio capture pipeline."""
        if self._running:
            logger.warning("Audio capture service already running")
            return

        self._running = True

        # Initialize audio source
        replay_enabled = getattr(self.config, "AUDIO_REPLAY_ENABLED", False)
        replay_path = getattr(self.config, "AUDIO_REPLAY_PATH", "")
        replay_speed = getattr(self.config, "AUDIO_REPLAY_SPEED", 10.0)

        if replay_enabled and replay_path:
            self._audio_source = TranscriptReplay(
                transcript_path=Path(replay_path),
                speed_multiplier=replay_speed,
            )
            logger.info(f"Using transcript replay: {replay_path}")
        else:
            sample_rate = getattr(self.config, "AUDIO_SAMPLE_RATE", 16000)
            chunk_ms = getattr(self.config, "AUDIO_CHUNK_MS", 100)
            vad_threshold = getattr(self.config, "AUDIO_VAD_THRESHOLD", 0.5)

            self._audio_source = MicCapture(
                AudioCaptureConfig(
                    sample_rate=sample_rate,
                    chunk_duration_ms=chunk_ms,
                    vad_threshold=vad_threshold,
                )
            )
            logger.info("Using microphone capture")

        await self._audio_source.start()

        # Initialize VAD (only for mic mode)
        if not replay_enabled:
            try:
                vad_threshold = getattr(self.config, "AUDIO_VAD_THRESHOLD", 0.5)
                self._vad = VADProcessor(threshold=vad_threshold)
                self._vad.load_model()
            except ImportError:
                logger.warning("Silero VAD not available, using energy-based VAD")
                self._vad = SimpleEnergyVAD()

        # Initialize STT (only for mic mode)
        if not replay_enabled:
            api_key = getattr(self.config, "ELEVENLABS_API_KEY", "")
            model = getattr(self.config, "ELEVENLABS_STT_MODEL", "scribe_v1")

            if api_key:
                self._stt = ElevenLabsSTTClient(api_key=api_key, model=model)
                await self._stt.connect()
            else:
                logger.warning("No ElevenLabs API key, using mock STT")
                self._stt = MockSTTClient()
                await self._stt.connect()

        # Start processing tasks
        self._capture_task = asyncio.create_task(self._capture_loop())

        if self._stt:
            self._stt_receive_task = asyncio.create_task(self._stt_receive_loop())

        await event_bus.emit(
            Event(
                EventType.AUDIO_CAPTURE_STARTED
                if hasattr(EventType, "AUDIO_CAPTURE_STARTED")
                else EventType.PROCESSING_STARTED,
                {"mode": "replay" if replay_enabled else "mic"},
            )
        )
        logger.info("Audio capture service started")

    async def stop(self) -> None:
        """Stop the audio capture pipeline."""
        self._running = False

        # Cancel tasks
        if self._capture_task:
            self._capture_task.cancel()
            try:
                await self._capture_task
            except asyncio.CancelledError:
                pass
            self._capture_task = None

        if self._stt_receive_task:
            self._stt_receive_task.cancel()
            try:
                await self._stt_receive_task
            except asyncio.CancelledError:
                pass
            self._stt_receive_task = None

        # Stop components
        if self._stt:
            await self._stt.disconnect()
            self._stt = None

        if self._audio_source:
            await self._audio_source.stop()
            self._audio_source = None

        await event_bus.emit(
            Event(
                EventType.AUDIO_CAPTURE_STOPPED
                if hasattr(EventType, "AUDIO_CAPTURE_STOPPED")
                else EventType.PROCESSING_COMPLETED,
                {"stats": self._stats},
            )
        )
        logger.info(f"Audio capture service stopped. Stats: {self._stats}")

    async def _capture_loop(self) -> None:
        """Main capture loop."""
        while self._running:
            try:
                chunk = await self._audio_source.read_chunk()

                if chunk is None:
                    # Source exhausted (e.g., replay finished)
                    if isinstance(self._audio_source, TranscriptReplay):
                        logger.info("Transcript replay completed")
                        self._running = False
                    continue

                self._stats["chunks_processed"] += 1

                if isinstance(chunk, TranscriptChunk):
                    # Replay mode - direct transcript
                    await self._process_replay_chunk(chunk)
                elif isinstance(chunk, AudioChunk):
                    # Mic mode - VAD + STT
                    await self._process_audio_chunk(chunk)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._stats["errors"] += 1
                logger.error(f"Error in capture loop: {e}")
                await asyncio.sleep(0.1)

    async def _process_audio_chunk(self, chunk: AudioChunk) -> None:
        """Process microphone audio chunk through VAD and STT."""
        # VAD check
        if self._vad:
            chunk.is_speech = self._vad.process_chunk(chunk)

        if chunk.is_speech:
            self._stats["speech_chunks"] += 1

            # Emit speech detected event
            await event_bus.emit(
                Event(
                    EventType.SPEECH_DETECTED
                    if hasattr(EventType, "SPEECH_DETECTED")
                    else EventType.PROCESSING_STARTED,
                    {
                        "energy_db": chunk.energy_db,
                        "timestamp": chunk.timestamp.isoformat(),
                    },
                )
            )

            # Send to STT
            if self._stt:
                await self._stt.send_audio(chunk)

    async def _process_replay_chunk(self, chunk: TranscriptChunk) -> None:
        """Process replay transcript chunk."""
        # Convert replay chunk to TranscriptSegment
        segment = TranscriptSegment(
            segment_id=chunk.chunk_id,
            text=chunk.text,
            is_final=True,
            confidence=1.0,
            start_ms=chunk.original_timestamp_ms,
            end_ms=chunk.original_timestamp_ms + 1000,
            speaker=chunk.speaker,
        )

        await self._handle_transcript(segment)

    async def _stt_receive_loop(self) -> None:
        """Receive transcripts from STT service."""
        if not self._stt:
            return

        async for segment in self._stt.receive_transcripts():
            if not self._running:
                break

            if segment.is_final:
                await self._handle_transcript(segment)

    async def _handle_transcript(self, segment: TranscriptSegment) -> None:
        """Handle received transcript segment."""
        self._stats["transcripts_received"] += 1

        logger.debug(
            f"Transcript: [{segment.speaker or 'unknown'}] {segment.text[:50]}..."
        )

        # Emit transcript event
        await event_bus.emit(
            Event(
                EventType.TRANSCRIPT_FINAL
                if hasattr(EventType, "TRANSCRIPT_FINAL")
                else EventType.PROCESSING_COMPLETED,
                {
                    "text": segment.text,
                    "speaker": segment.speaker,
                    "confidence": segment.confidence,
                    "timestamp": segment.timestamp.isoformat(),
                },
            )
        )

        # Call callback if provided
        if self._on_transcript:
            try:
                self._on_transcript(segment)
            except Exception as e:
                logger.error(f"Error in transcript callback: {e}")

    def set_transcript_callback(
        self, callback: Callable[[TranscriptSegment], None]
    ) -> None:
        """Set callback for transcript segments."""
        self._on_transcript = callback
