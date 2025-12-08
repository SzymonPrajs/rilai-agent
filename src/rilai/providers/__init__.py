"""Model providers for Rilai v2."""

from .openrouter import Message, ModelResponse, OpenRouterClient, openrouter, get_provider
from .elevenlabs_stt import (
    ScribeRealtimeClient,
    ScribeEventType,
    TranscriptEvent,
    WordTimestamp,
    get_scribe_client,
    transcribe_audio_stream,
)

__all__ = [
    # OpenRouter
    "Message",
    "ModelResponse",
    "OpenRouterClient",
    "openrouter",
    "get_provider",
    # ElevenLabs Scribe STT
    "ScribeRealtimeClient",
    "ScribeEventType",
    "TranscriptEvent",
    "WordTimestamp",
    "get_scribe_client",
    "transcribe_audio_stream",
]
