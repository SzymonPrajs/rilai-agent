"""
Speech-to-Text using ElevenLabs API

WebSocket streaming for real-time transcription with speaker diarization.
"""

import asyncio
import base64
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import AsyncIterator

from rilai.audio.capture import AudioChunk

logger = logging.getLogger(__name__)


@dataclass
class TranscriptSegment:
    """A segment of transcribed text."""

    segment_id: str
    text: str
    is_final: bool
    confidence: float
    start_ms: int
    end_ms: int
    speaker: str | None = None
    language: str = "en"
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


class ElevenLabsSTTClient:
    """Streaming speech-to-text using ElevenLabs API.

    Uses WebSocket for real-time streaming transcription.
    Supports speaker diarization when available.
    """

    # ElevenLabs STT WebSocket endpoint
    WEBSOCKET_URL = "wss://api.elevenlabs.io/v1/speech-to-text/stream"

    def __init__(
        self,
        api_key: str,
        model: str = "scribe_v1",
        language: str = "en",
        diarize: bool = True,
    ):
        """Initialize ElevenLabs STT client.

        Args:
            api_key: ElevenLabs API key
            model: STT model to use (default: scribe_v1)
            language: Language code (default: en)
            diarize: Enable speaker diarization
        """
        self.api_key = api_key
        self.model = model
        self.language = language
        self.diarize = diarize

        self._ws = None
        self._running = False
        self._receive_task: asyncio.Task | None = None
        self._transcript_queue: asyncio.Queue[TranscriptSegment] = asyncio.Queue()

    @property
    def is_connected(self) -> bool:
        return self._ws is not None and self._running

    async def connect(self) -> None:
        """Establish WebSocket connection."""
        try:
            import websockets
        except ImportError:
            raise ImportError(
                "websockets is required for ElevenLabs STT. "
                "Install with: pip install websockets"
            )

        if not self.api_key:
            raise ValueError("ElevenLabs API key is required")

        headers = {
            "xi-api-key": self.api_key,
        }

        logger.info("Connecting to ElevenLabs STT...")

        self._ws = await websockets.connect(
            self.WEBSOCKET_URL,
            extra_headers=headers,
            ping_interval=20,
            ping_timeout=10,
        )

        # Send configuration
        config = {
            "type": "config",
            "model": self.model,
            "language": self.language,
            "diarize": self.diarize,
        }
        await self._ws.send(json.dumps(config))

        self._running = True

        # Start background receive task
        self._receive_task = asyncio.create_task(self._receive_loop())

        logger.info(
            f"Connected to ElevenLabs STT (model={self.model}, diarize={self.diarize})"
        )

    async def _receive_loop(self) -> None:
        """Background task to receive transcript segments."""
        while self._running and self._ws:
            try:
                message = await asyncio.wait_for(
                    self._ws.recv(),
                    timeout=30.0,
                )
                data = json.loads(message)

                if data.get("type") == "transcript":
                    segment = TranscriptSegment(
                        segment_id=data.get("id", str(uuid.uuid4())),
                        text=data.get("text", ""),
                        is_final=data.get("is_final", False),
                        confidence=data.get("confidence", 1.0),
                        start_ms=data.get("start_ms", 0),
                        end_ms=data.get("end_ms", 0),
                        speaker=data.get("speaker"),
                        language=data.get("language", self.language),
                    )
                    await self._transcript_queue.put(segment)

                elif data.get("type") == "error":
                    logger.error(f"STT error: {data.get('message')}")

                elif data.get("type") == "info":
                    logger.debug(f"STT info: {data.get('message')}")

            except asyncio.TimeoutError:
                # No message received, continue
                continue
            except Exception as e:
                if self._running:
                    logger.error(f"Error receiving transcript: {e}")
                break

    async def send_audio(self, chunk: AudioChunk) -> None:
        """Send audio chunk to ElevenLabs.

        Args:
            chunk: AudioChunk to send for transcription
        """
        if not self._ws or not self._running:
            logger.warning("Cannot send audio: not connected")
            return

        try:
            message = {
                "type": "audio",
                "data": base64.b64encode(chunk.data).decode(),
            }
            await self._ws.send(json.dumps(message))
        except Exception as e:
            logger.error(f"Error sending audio: {e}")

    async def receive_transcripts(self) -> AsyncIterator[TranscriptSegment]:
        """Receive transcript segments.

        Yields:
            TranscriptSegment objects as they become available.
        """
        while self._running:
            try:
                segment = await asyncio.wait_for(
                    self._transcript_queue.get(),
                    timeout=1.0,
                )
                yield segment
            except asyncio.TimeoutError:
                continue

    async def get_next_transcript(
        self, timeout: float = 5.0
    ) -> TranscriptSegment | None:
        """Get next transcript segment with timeout.

        Args:
            timeout: Maximum time to wait in seconds

        Returns:
            TranscriptSegment or None if timeout
        """
        try:
            return await asyncio.wait_for(
                self._transcript_queue.get(),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            return None

    async def send_end_of_stream(self) -> None:
        """Signal end of audio stream."""
        if self._ws and self._running:
            try:
                await self._ws.send(json.dumps({"type": "end_of_stream"}))
            except Exception as e:
                logger.error(f"Error sending end of stream: {e}")

    async def disconnect(self) -> None:
        """Close WebSocket connection."""
        self._running = False

        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
            self._receive_task = None

        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

        logger.info("Disconnected from ElevenLabs STT")


class MockSTTClient:
    """Mock STT client for testing without API access."""

    def __init__(self):
        self._running = False
        self._transcript_queue: asyncio.Queue[TranscriptSegment] = asyncio.Queue()

    @property
    def is_connected(self) -> bool:
        return self._running

    async def connect(self) -> None:
        self._running = True
        logger.info("Mock STT client connected")

    async def send_audio(self, chunk: AudioChunk) -> None:
        """Mock: ignore audio chunks."""
        pass

    async def add_transcript(self, text: str, speaker: str = "user") -> None:
        """Add a transcript segment for testing."""
        segment = TranscriptSegment(
            segment_id=str(uuid.uuid4()),
            text=text,
            is_final=True,
            confidence=1.0,
            start_ms=0,
            end_ms=1000,
            speaker=speaker,
        )
        await self._transcript_queue.put(segment)

    async def receive_transcripts(self) -> AsyncIterator[TranscriptSegment]:
        while self._running:
            try:
                segment = await asyncio.wait_for(
                    self._transcript_queue.get(),
                    timeout=1.0,
                )
                yield segment
            except asyncio.TimeoutError:
                continue

    async def disconnect(self) -> None:
        self._running = False
        logger.info("Mock STT client disconnected")
