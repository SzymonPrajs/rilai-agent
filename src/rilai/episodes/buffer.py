"""
Transcript Buffer

Accumulates transcript segments for episode processing.
Detects episode boundaries based on silence gaps.
"""

import logging
import uuid
from collections import deque
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from rilai.episodes.schema import Episode, SpeechTurn

if TYPE_CHECKING:
    from rilai.audio.stt import TranscriptSegment

logger = logging.getLogger(__name__)


class TranscriptBuffer:
    """Accumulates transcript segments for episode processing.

    Maintains a sliding window of recent transcripts and
    detects episode boundaries based on silence gaps.
    """

    def __init__(
        self,
        window_size: int = 100,  # Max segments in window
        silence_threshold_ms: int = 5000,  # 5s silence = boundary
        min_episode_words: int = 5,  # Minimum words for episode
    ):
        """Initialize transcript buffer.

        Args:
            window_size: Maximum segments to keep in window
            silence_threshold_ms: Silence duration (ms) to trigger boundary
            min_episode_words: Minimum word count for valid episode
        """
        self.window_size = window_size
        self.silence_threshold_ms = silence_threshold_ms
        self.min_episode_words = min_episode_words

        self._segments: deque["TranscriptSegment"] = deque(maxlen=window_size)
        self._current_episode_segments: list["TranscriptSegment"] = []
        self._last_segment_time: datetime | None = None
        self._episode_count = 0

    def add_segment(self, segment: "TranscriptSegment") -> Episode | None:
        """Add a segment and check for episode boundary.

        Args:
            segment: Transcript segment to add

        Returns:
            Episode if a boundary was detected, None otherwise.
        """
        now = datetime.now()

        # Check for silence boundary
        if self._last_segment_time:
            silence_ms = (now - self._last_segment_time).total_seconds() * 1000

            if silence_ms > self.silence_threshold_ms and self._current_episode_segments:
                # Boundary detected - finalize current episode
                episode = self._finalize_episode("silence")

                # Start new episode with this segment
                self._current_episode_segments = [segment]
                self._last_segment_time = now
                self._segments.append(segment)

                return episode

        # Add to current episode
        self._current_episode_segments.append(segment)
        self._segments.append(segment)
        self._last_segment_time = now

        return None

    def force_boundary(
        self, boundary_type: str = "explicit"
    ) -> Episode | None:
        """Force an episode boundary.

        Args:
            boundary_type: Type of boundary (explicit, topic, time)

        Returns:
            Episode if there were accumulated segments, None otherwise.
        """
        if self._current_episode_segments:
            episode = self._finalize_episode(boundary_type)
            self._current_episode_segments = []
            return episode
        return None

    def flush(self) -> Episode | None:
        """Force finalize current episode.

        Returns:
            Episode if there were accumulated segments, None otherwise.
        """
        return self.force_boundary("time")

    def _finalize_episode(self, boundary_type: str) -> Episode | None:
        """Create an Episode from accumulated segments.

        Args:
            boundary_type: Type of boundary that triggered finalization

        Returns:
            Episode or None if not enough content
        """
        segments = self._current_episode_segments

        if not segments:
            return None

        # Convert segments to turns (merge consecutive same-speaker)
        turns = self._segments_to_turns(segments)

        if not turns:
            return None

        # Check minimum word count
        word_count = sum(t.word_count for t in turns)
        if word_count < self.min_episode_words:
            logger.debug(
                f"Episode too short ({word_count} words), skipping"
            )
            return None

        self._episode_count += 1

        episode = Episode.create(
            turns=turns,
            boundary_type=boundary_type,
        )

        logger.debug(
            f"Episode finalized: {episode.episode_id} "
            f"({len(turns)} turns, {word_count} words, {boundary_type})"
        )

        return episode

    def _segments_to_turns(
        self, segments: list["TranscriptSegment"]
    ) -> list[SpeechTurn]:
        """Convert segments to speaker turns.

        Merges consecutive segments from the same speaker.

        Args:
            segments: List of transcript segments

        Returns:
            List of speech turns
        """
        if not segments:
            return []

        turns = []
        current_speaker = None
        current_texts = []
        current_start = None
        current_end = None
        current_confidences = []

        for seg in segments:
            speaker = seg.speaker or "unknown"

            if speaker != current_speaker and current_texts:
                # Speaker change - finalize current turn
                turn = SpeechTurn.create(
                    speaker=current_speaker,
                    text=" ".join(current_texts),
                    start_ts=current_start,
                    end_ts=current_end,
                    confidence=sum(current_confidences) / len(current_confidences),
                )
                turns.append(turn)

                # Reset for new speaker
                current_texts = []
                current_confidences = []
                current_start = None

            # Update current turn
            current_speaker = speaker
            current_texts.append(seg.text)
            current_confidences.append(seg.confidence)

            if current_start is None:
                current_start = seg.timestamp
            current_end = seg.timestamp

        # Finalize last turn
        if current_texts:
            turn = SpeechTurn.create(
                speaker=current_speaker,
                text=" ".join(current_texts),
                start_ts=current_start,
                end_ts=current_end,
                confidence=sum(current_confidences) / len(current_confidences)
                if current_confidences
                else 1.0,
            )
            turns.append(turn)

        return turns

    @property
    def current_word_count(self) -> int:
        """Get word count of current (unflushed) episode."""
        return sum(len(s.text.split()) for s in self._current_episode_segments)

    @property
    def current_segment_count(self) -> int:
        """Get segment count of current episode."""
        return len(self._current_episode_segments)

    @property
    def total_episodes(self) -> int:
        """Get total episodes created."""
        return self._episode_count

    @property
    def time_since_last_segment(self) -> timedelta | None:
        """Get time since last segment."""
        if self._last_segment_time:
            return datetime.now() - self._last_segment_time
        return None

    def clear(self) -> None:
        """Clear all accumulated data."""
        self._segments.clear()
        self._current_episode_segments = []
        self._last_segment_time = None
