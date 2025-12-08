"""
AudioAdapter

Wraps the existing audio capture pipeline (mic + VAD + STT) to emit UtteranceEvents.
This is the production adapter for real-time audio input.
"""

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import TYPE_CHECKING

from rilai.adapters.protocol import BaseInputAdapter
from rilai.core.utterance import UtteranceEvent

if TYPE_CHECKING:
    from rilai.config import Config

logger = logging.getLogger(__name__)


class AudioAdapter(BaseInputAdapter):
    """Input adapter for real-time audio capture.

    Wraps the existing audio capture service (mic, VAD, STT) and
    converts TranscriptSegments to UtteranceEvents.

    Usage:
        adapter = AudioAdapter(config)
        await adapter.start()
        async for utterance in adapter.stream():
            process(utterance)
        await adapter.stop()
    """

    def __init__(
        self,
        config: "Config",
        speaker_id: str = "you",
        channel: str = "default",
    ):
        """Initialize the audio adapter.

        Args:
            config: Application configuration
            speaker_id: Default speaker ID (usually "you" for mic input)
            channel: Default channel/context
        """
        super().__init__()
        self.config = config
        self.speaker_id = speaker_id
        self.channel = channel

        # Audio service will be initialized on start
        self._audio_service = None
        self._utterance_queue: asyncio.Queue[UtteranceEvent] = asyncio.Queue()

        # Statistics
        self._stats = {
            "segments_received": 0,
            "utterances_emitted": 0,
        }

    @property
    def name(self) -> str:
        return "AudioAdapter(mic)"

    @property
    def stats(self) -> dict:
        return self._stats.copy()

    async def start(self) -> None:
        """Start the audio capture service."""
        if self._running:
            logger.warning("AudioAdapter already running")
            return

        try:
            from rilai.audio.service import AudioCaptureService

            self._audio_service = AudioCaptureService(
                config=self.config,
                on_transcript=self._handle_transcript,
            )
            await self._audio_service.start()
            self._running = True
            logger.info("AudioAdapter started")

        except ImportError as e:
            logger.error(f"Failed to import audio service: {e}")
            raise RuntimeError(
                "Audio service not available. "
                "Make sure audio dependencies are installed."
            ) from e

    async def stop(self) -> None:
        """Stop the audio capture service."""
        self._running = False

        if self._audio_service:
            await self._audio_service.stop()
            self._audio_service = None

        logger.info(f"AudioAdapter stopped. Stats: {self._stats}")

    async def stream(self) -> AsyncIterator[UtteranceEvent]:
        """Stream UtteranceEvents from the audio capture.

        Yields:
            UtteranceEvent objects as speech is recognized
        """
        if not self._running:
            raise RuntimeError("AudioAdapter not started. Call start() first.")

        while self._running:
            try:
                # Wait for utterances from the audio service
                utterance = await asyncio.wait_for(
                    self._utterance_queue.get(),
                    timeout=1.0,
                )
                yield utterance

            except asyncio.TimeoutError:
                # No utterance received, continue waiting
                continue

            except asyncio.CancelledError:
                break

    def _handle_transcript(self, segment) -> None:
        """Handle a transcript segment from the audio service.

        Converts TranscriptSegment to UtteranceEvent and queues it.

        Args:
            segment: TranscriptSegment from the audio service
        """
        self._stats["segments_received"] += 1

        # Only process final segments (not intermediate)
        if not segment.is_final:
            return

        # Convert to UtteranceEvent
        utterance = UtteranceEvent(
            event_id=str(uuid.uuid4()),
            ts_start=datetime.now(),  # Use current time for real-time
            ts_end=datetime.now(),
            speaker_id=segment.speaker or self.speaker_id,
            channel=self.channel,
            text=segment.text,
            confidence=segment.confidence,
            tags=[],
            source="audio",
        )

        self._stats["utterances_emitted"] += 1

        # Queue the utterance (non-blocking)
        try:
            self._utterance_queue.put_nowait(utterance)
        except asyncio.QueueFull:
            logger.warning("Utterance queue full, dropping oldest")
            # Drop oldest and add new
            try:
                self._utterance_queue.get_nowait()
                self._utterance_queue.put_nowait(utterance)
            except asyncio.QueueEmpty:
                pass

    def set_channel(self, channel: str) -> None:
        """Update the current channel/context.

        Args:
            channel: New channel name
        """
        self.channel = channel
        logger.debug(f"Channel updated to: {channel}")

    def set_speaker(self, speaker_id: str) -> None:
        """Update the default speaker ID.

        Args:
            speaker_id: New speaker ID
        """
        self.speaker_id = speaker_id
        logger.debug(f"Speaker updated to: {speaker_id}")
