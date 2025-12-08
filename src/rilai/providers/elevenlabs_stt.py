"""ElevenLabs Scribe Realtime v2 Speech-to-Text Client.

Provides real-time streaming speech-to-text using ElevenLabs' Scribe API.
See: https://elevenlabs.io/docs/developers/guides/cookbooks/speech-to-text/streaming

Features:
- WebSocket-based streaming transcription
- Voice Activity Detection (VAD) for automatic segmentation
- Word-level timestamps
- Partial and committed transcript events
"""

import asyncio
import base64
import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import AsyncIterator, Callable

import websockets
from websockets.exceptions import ConnectionClosed

from rilai.config import get_config

logger = logging.getLogger(__name__)


class ScribeEventType(str, Enum):
    """Event types from Scribe Realtime API."""

    SESSION_STARTED = "session_started"
    PARTIAL_TRANSCRIPT = "partial_transcript"
    COMMITTED_TRANSCRIPT = "committed_transcript"
    COMMITTED_TRANSCRIPT_TIMESTAMPS = "committed_transcript_with_timestamps"
    AUTH_ERROR = "auth_error"
    INPUT_ERROR = "input_error"
    TRANSCRIBER_ERROR = "transcriber_error"
    SERVER_ERROR = "server_error"


@dataclass
class WordTimestamp:
    """Word with timing information."""

    word: str
    start_ms: int
    end_ms: int
    confidence: float = 1.0


@dataclass
class TranscriptEvent:
    """A transcript event from Scribe."""

    event_type: ScribeEventType
    text: str = ""
    is_final: bool = False
    words: list[WordTimestamp] = field(default_factory=list)
    language: str | None = None
    error_message: str | None = None

    @classmethod
    def from_message(cls, data: dict) -> "TranscriptEvent":
        """Create from WebSocket message."""
        msg_type = data.get("message_type", data.get("type", ""))

        # Map message types to event types
        event_type = ScribeEventType.PARTIAL_TRANSCRIPT
        is_final = False

        if msg_type == "session_started":
            event_type = ScribeEventType.SESSION_STARTED
        elif msg_type == "partial_transcript":
            event_type = ScribeEventType.PARTIAL_TRANSCRIPT
        elif msg_type == "committed_transcript":
            event_type = ScribeEventType.COMMITTED_TRANSCRIPT
            is_final = True
        elif msg_type == "committed_transcript_with_timestamps":
            event_type = ScribeEventType.COMMITTED_TRANSCRIPT_TIMESTAMPS
            is_final = True
        elif msg_type in ("auth_error", "input_error", "transcriber_error", "server_error"):
            event_type = ScribeEventType(msg_type)

        # Extract text
        text = data.get("text", "")

        # Extract word timestamps if available
        words = []
        if "words" in data:
            for w in data["words"]:
                words.append(WordTimestamp(
                    word=w.get("word", w.get("text", "")),
                    start_ms=int(w.get("start", w.get("start_ms", 0)) * 1000) if isinstance(w.get("start", 0), float) else w.get("start_ms", 0),
                    end_ms=int(w.get("end", w.get("end_ms", 0)) * 1000) if isinstance(w.get("end", 0), float) else w.get("end_ms", 0),
                    confidence=w.get("confidence", 1.0),
                ))

        return cls(
            event_type=event_type,
            text=text,
            is_final=is_final,
            words=words,
            language=data.get("language_code"),
            error_message=data.get("error", data.get("message")),
        )


class ScribeRealtimeClient:
    """Client for ElevenLabs Scribe Realtime v2 API.

    Usage:
        client = ScribeRealtimeClient()
        await client.connect()

        # Stream audio chunks
        async for event in client.stream_audio(audio_generator()):
            if event.is_final:
                print(f"Final: {event.text}")
            else:
                print(f"Partial: {event.text}")

        await client.close()
    """

    BASE_URL = "wss://api.elevenlabs.io/v1/speech-to-text/realtime"

    def __init__(
        self,
        api_key: str | None = None,
        model_id: str | None = None,
        language: str | None = None,
        audio_format: str | None = None,
        sample_rate: int | None = None,
        commit_strategy: str | None = None,
        vad_threshold: float | None = None,
        vad_silence_secs: float | None = None,
        include_timestamps: bool | None = None,
    ):
        """Initialize the Scribe client.

        Args:
            api_key: ElevenLabs API key (defaults to config)
            model_id: Model ID (defaults to config, must be scribe_v2_realtime)
            language: Language code (defaults to config, empty = auto-detect)
            audio_format: Audio encoding format (defaults to config)
            sample_rate: Audio sample rate in Hz (defaults to config)
            commit_strategy: "manual" or "vad" (defaults to config)
            vad_threshold: VAD sensitivity 0.1-0.9 (defaults to config)
            vad_silence_secs: Silence duration before VAD commit (defaults to config)
            include_timestamps: Include word-level timestamps (defaults to config)
        """
        config = get_config()

        self._api_key = api_key or config.ELEVENLABS_API_KEY
        self._model_id = model_id or getattr(config, "ELEVENLABS_STT_MODEL", "scribe_v2_realtime")
        self._language = language if language is not None else getattr(config, "ELEVENLABS_STT_LANGUAGE", "")
        self._audio_format = audio_format or getattr(config, "ELEVENLABS_STT_AUDIO_FORMAT", "pcm_16000")
        self._sample_rate = sample_rate or getattr(config, "ELEVENLABS_STT_SAMPLE_RATE", 16000)
        self._commit_strategy = commit_strategy or getattr(config, "ELEVENLABS_STT_COMMIT_STRATEGY", "vad")
        self._vad_threshold = vad_threshold if vad_threshold is not None else getattr(config, "ELEVENLABS_STT_VAD_THRESHOLD", 0.4)
        self._vad_silence_secs = vad_silence_secs if vad_silence_secs is not None else getattr(config, "ELEVENLABS_STT_VAD_SILENCE_SECS", 1.5)
        self._include_timestamps = include_timestamps if include_timestamps is not None else getattr(config, "ELEVENLABS_STT_INCLUDE_TIMESTAMPS", True)

        self._reconnect_attempts = getattr(config, "ELEVENLABS_STT_RECONNECT_ATTEMPTS", 3)
        self._reconnect_delay_ms = getattr(config, "ELEVENLABS_STT_RECONNECT_DELAY_MS", 1000)

        self._ws: websockets.WebSocketClientProtocol | None = None
        self._connected = False
        self._receive_task: asyncio.Task | None = None
        self._event_queue: asyncio.Queue[TranscriptEvent] = asyncio.Queue()

    def _build_url(self) -> str:
        """Build the WebSocket URL with query parameters."""
        params = [f"model_id={self._model_id}"]

        if self._language:
            params.append(f"language_code={self._language}")

        params.append(f"audio_format={self._audio_format}")
        params.append(f"commit_strategy={self._commit_strategy}")
        params.append(f"include_timestamps={str(self._include_timestamps).lower()}")

        if self._commit_strategy == "vad":
            params.append(f"vad_threshold={self._vad_threshold}")
            params.append(f"vad_silence_threshold_secs={self._vad_silence_secs}")

        return f"{self.BASE_URL}?{'&'.join(params)}"

    async def connect(self) -> None:
        """Establish WebSocket connection to Scribe API."""
        if self._connected:
            return

        if not self._api_key:
            raise ValueError("ElevenLabs API key not configured")

        url = self._build_url()
        headers = {"xi-api-key": self._api_key}

        attempt = 0
        while attempt < self._reconnect_attempts:
            try:
                self._ws = await websockets.connect(
                    url,
                    additional_headers=headers,
                    ping_interval=20,
                    ping_timeout=20,
                )
                self._connected = True

                # Wait for session_started
                msg = await asyncio.wait_for(self._ws.recv(), timeout=10.0)
                data = json.loads(msg)
                event = TranscriptEvent.from_message(data)

                if event.event_type == ScribeEventType.SESSION_STARTED:
                    logger.info("Scribe realtime session started")
                    return
                elif event.event_type in (ScribeEventType.AUTH_ERROR, ScribeEventType.SERVER_ERROR):
                    raise ConnectionError(f"Scribe connection failed: {event.error_message}")

            except (ConnectionClosed, asyncio.TimeoutError, OSError) as e:
                attempt += 1
                if attempt >= self._reconnect_attempts:
                    raise ConnectionError(f"Failed to connect to Scribe after {attempt} attempts: {e}")

                delay = (self._reconnect_delay_ms / 1000) * (2 ** (attempt - 1))  # Exponential backoff
                logger.warning(f"Scribe connection attempt {attempt} failed, retrying in {delay:.1f}s...")
                await asyncio.sleep(delay)

    async def close(self) -> None:
        """Close the WebSocket connection."""
        self._connected = False

        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
            self._receive_task = None

        if self._ws:
            await self._ws.close()
            self._ws = None

    async def send_audio_chunk(self, audio_bytes: bytes, commit: bool = False) -> None:
        """Send an audio chunk to Scribe.

        Args:
            audio_bytes: Raw audio bytes (PCM format)
            commit: If True, signals end of speech segment
        """
        if not self._connected or not self._ws:
            raise RuntimeError("Not connected to Scribe")

        message = {
            "message_type": "input_audio_chunk",
            "audio_base_64": base64.b64encode(audio_bytes).decode("utf-8") if audio_bytes else "",
            "sample_rate": self._sample_rate,
            "commit": commit,
        }

        await self._ws.send(json.dumps(message))

    async def commit(self) -> None:
        """Manually commit the current audio segment."""
        await self.send_audio_chunk(b"", commit=True)

    async def receive_events(self) -> AsyncIterator[TranscriptEvent]:
        """Receive transcript events from Scribe.

        Yields:
            TranscriptEvent objects for partial and committed transcripts
        """
        if not self._connected or not self._ws:
            raise RuntimeError("Not connected to Scribe")

        try:
            async for msg in self._ws:
                data = json.loads(msg)
                event = TranscriptEvent.from_message(data)

                # Handle errors
                if event.event_type in (
                    ScribeEventType.AUTH_ERROR,
                    ScribeEventType.INPUT_ERROR,
                    ScribeEventType.TRANSCRIBER_ERROR,
                    ScribeEventType.SERVER_ERROR,
                ):
                    logger.error(f"Scribe error: {event.error_message}")
                    yield event
                    continue

                yield event

        except ConnectionClosed as e:
            logger.warning(f"Scribe connection closed: {e}")
            self._connected = False

    async def stream_audio(
        self,
        audio_source: AsyncIterator[bytes],
        on_partial: Callable[[str], None] | None = None,
        on_final: Callable[[str, list[WordTimestamp]], None] | None = None,
    ) -> AsyncIterator[TranscriptEvent]:
        """Stream audio and receive transcription events.

        This is the main high-level API for streaming transcription.

        Args:
            audio_source: Async iterator yielding audio chunks (PCM bytes)
            on_partial: Optional callback for partial transcripts
            on_final: Optional callback for final transcripts (with timestamps)

        Yields:
            TranscriptEvent objects
        """
        if not self._connected:
            await self.connect()

        # Start receiving events in background
        async def send_audio():
            async for chunk in audio_source:
                await self.send_audio_chunk(chunk)

        send_task = asyncio.create_task(send_audio())

        try:
            async for event in self.receive_events():
                if event.event_type == ScribeEventType.PARTIAL_TRANSCRIPT:
                    if on_partial:
                        on_partial(event.text)

                elif event.event_type in (
                    ScribeEventType.COMMITTED_TRANSCRIPT,
                    ScribeEventType.COMMITTED_TRANSCRIPT_TIMESTAMPS,
                ):
                    if on_final:
                        on_final(event.text, event.words)

                yield event

        finally:
            send_task.cancel()
            try:
                await send_task
            except asyncio.CancelledError:
                pass


# Singleton instance
scribe_client: ScribeRealtimeClient | None = None


def get_scribe_client() -> ScribeRealtimeClient:
    """Get or create the singleton Scribe client."""
    global scribe_client
    if scribe_client is None:
        scribe_client = ScribeRealtimeClient()
    return scribe_client


async def transcribe_audio_stream(
    audio_source: AsyncIterator[bytes],
) -> AsyncIterator[TranscriptEvent]:
    """Convenience function for streaming transcription.

    Args:
        audio_source: Async iterator yielding audio chunks

    Yields:
        TranscriptEvent objects
    """
    client = get_scribe_client()
    async for event in client.stream_audio(audio_source):
        yield event
