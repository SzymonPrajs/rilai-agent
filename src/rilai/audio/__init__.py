"""
Audio Capture Module for Ambient Mode

Provides:
- MicCapture: macOS microphone capture using sounddevice
- TranscriptReplay: Replay pre-recorded transcripts for testing
- VADProcessor: Voice Activity Detection using Silero VAD
- ElevenLabsSTTClient: WebSocket streaming STT
- AudioCaptureService: Orchestrates the full audio pipeline
"""

from rilai.audio.capture import (
    AudioChunk,
    AudioCaptureConfig,
    AudioSource,
    MicCapture,
    TranscriptChunk,
    TranscriptEntry,
    TranscriptReplay,
)
from rilai.audio.service import AudioCaptureService
from rilai.audio.stt import ElevenLabsSTTClient, TranscriptSegment
from rilai.audio.vad import VADProcessor

__all__ = [
    # Data types
    "AudioChunk",
    "AudioCaptureConfig",
    "TranscriptChunk",
    "TranscriptEntry",
    "TranscriptSegment",
    # Sources
    "AudioSource",
    "MicCapture",
    "TranscriptReplay",
    # Processing
    "VADProcessor",
    "ElevenLabsSTTClient",
    # Service
    "AudioCaptureService",
]
