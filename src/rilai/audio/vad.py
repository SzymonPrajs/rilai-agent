"""
Voice Activity Detection using Silero VAD

Silero VAD is lightweight and runs locally without GPU.
Uses ONNX runtime for fast CPU inference.
"""

import logging
from pathlib import Path

import numpy as np

from rilai.audio.capture import AudioChunk

logger = logging.getLogger(__name__)


class VADProcessor:
    """Voice Activity Detection using Silero VAD.

    Silero VAD is lightweight (~1MB) and runs efficiently on CPU.
    It provides accurate speech detection with minimal latency.
    """

    def __init__(self, threshold: float = 0.5):
        """Initialize VAD processor.

        Args:
            threshold: Speech probability threshold (0.0-1.0).
                      Higher values are more conservative (fewer false positives).
        """
        self.threshold = threshold
        self._model = None
        self._get_speech_timestamps = None
        self._sampling_rate = 16000
        self._model_loaded = False

    def load_model(self) -> None:
        """Load Silero VAD model."""
        if self._model_loaded:
            return

        try:
            import torch
        except ImportError:
            raise ImportError(
                "torch is required for Silero VAD. "
                "Install with: pip install torch"
            )

        logger.info("Loading Silero VAD model...")

        # Load model from torch hub
        self._model, utils = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            force_reload=False,
            onnx=True,  # Use ONNX for faster CPU inference
        )

        # Extract utility functions
        (
            self._get_speech_timestamps,
            _,  # save_audio
            _,  # read_audio
            _,  # VADIterator
            _,  # collect_chunks
        ) = utils

        self._model_loaded = True
        logger.info("Silero VAD model loaded successfully")

    def process_chunk(self, chunk: AudioChunk) -> bool:
        """Determine if chunk contains speech.

        Args:
            chunk: AudioChunk to process

        Returns:
            True if speech detected, False otherwise.
        """
        import torch

        if not self._model_loaded:
            self.load_model()

        # Convert bytes to tensor
        audio = np.frombuffer(chunk.data, dtype=np.int16).astype(np.float32)
        audio = audio / 32768.0  # Normalize to [-1, 1]
        audio_tensor = torch.from_numpy(audio)

        # Get speech probability
        speech_prob = self._model(audio_tensor, self._sampling_rate).item()

        return speech_prob > self.threshold

    def get_speech_probability(self, chunk: AudioChunk) -> float:
        """Get speech probability for a chunk.

        Args:
            chunk: AudioChunk to process

        Returns:
            Speech probability (0.0 to 1.0)
        """
        import torch

        if not self._model_loaded:
            self.load_model()

        audio = np.frombuffer(chunk.data, dtype=np.int16).astype(np.float32)
        audio = audio / 32768.0
        audio_tensor = torch.from_numpy(audio)

        return self._model(audio_tensor, self._sampling_rate).item()

    def get_speech_segments(
        self, audio_data: bytes, sample_rate: int = 16000
    ) -> list[tuple[int, int]]:
        """Get speech segments from longer audio.

        Args:
            audio_data: Raw PCM audio bytes (int16)
            sample_rate: Sample rate of audio

        Returns:
            List of (start_ms, end_ms) tuples for speech segments.
        """
        import torch

        if not self._model_loaded:
            self.load_model()

        audio = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32)
        audio = audio / 32768.0
        audio_tensor = torch.from_numpy(audio)

        timestamps = self._get_speech_timestamps(
            audio_tensor,
            self._model,
            sampling_rate=sample_rate,
            threshold=self.threshold,
        )

        return [
            (
                int(ts["start"] / sample_rate * 1000),
                int(ts["end"] / sample_rate * 1000),
            )
            for ts in timestamps
        ]

    def reset(self) -> None:
        """Reset VAD state (for streaming applications)."""
        if self._model is not None:
            self._model.reset_states()


class SimpleEnergyVAD:
    """Simple energy-based VAD as fallback when Silero is unavailable.

    Uses RMS energy threshold for basic speech detection.
    Less accurate than Silero but requires no dependencies.
    """

    def __init__(
        self,
        energy_threshold_db: float = -30.0,
        min_speech_duration_ms: int = 100,
    ):
        """Initialize simple energy-based VAD.

        Args:
            energy_threshold_db: Energy threshold in dB
            min_speech_duration_ms: Minimum duration to consider as speech
        """
        self.energy_threshold_db = energy_threshold_db
        self.min_speech_duration_ms = min_speech_duration_ms
        self._speech_frames = 0
        self._sample_rate = 16000

    def process_chunk(self, chunk: AudioChunk) -> bool:
        """Determine if chunk contains speech based on energy.

        Args:
            chunk: AudioChunk to process

        Returns:
            True if speech detected, False otherwise.
        """
        # Use pre-computed energy if available
        if chunk.energy_db > self.energy_threshold_db:
            self._speech_frames += 1
            frames_needed = int(
                self.min_speech_duration_ms * chunk.sample_rate / 1000 / len(chunk.data)
            )
            return self._speech_frames >= max(1, frames_needed)
        else:
            self._speech_frames = 0
            return False

    def reset(self) -> None:
        """Reset VAD state."""
        self._speech_frames = 0
