"""
Episode Segmenter

Advanced episode segmentation with multiple boundary detection strategies.
"""

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from rilai.episodes.buffer import TranscriptBuffer
from rilai.episodes.schema import Episode

if TYPE_CHECKING:
    from rilai.audio.stt import TranscriptSegment

logger = logging.getLogger(__name__)


class EpisodeSegmenter:
    """Advanced episode segmentation with multiple boundary detection strategies.

    Boundaries are detected by:
    1. Silence gaps (>5s)
    2. Explicit markers ("okay so", "anyway", "moving on")
    3. Time limits (max episode duration)
    4. Topic shifts (future: semantic embedding distance)
    """

    # Explicit boundary markers - phrases that often signal topic change
    BOUNDARY_MARKERS = [
        "okay so",
        "alright so",
        "anyway",
        "moving on",
        "let's talk about",
        "changing topics",
        "by the way",
        "so anyway",
        "anyway so",
        "well anyway",
        "on a different note",
        "speaking of which",
        "that reminds me",
    ]

    # High-intensity keywords for emotional intensity scoring
    INTENSITY_KEYWORDS = {
        "high": [
            "angry",
            "furious",
            "terrified",
            "ecstatic",
            "devastated",
            "amazing",
            "horrible",
            "incredible",
            "awful",
            "fantastic",
            "hate",
            "love",
            "desperate",
            "urgent",
            "emergency",
            "critical",
        ],
        "medium": [
            "frustrated",
            "excited",
            "worried",
            "happy",
            "sad",
            "annoyed",
            "anxious",
            "nervous",
            "thrilled",
            "upset",
            "concerned",
            "delighted",
            "disappointed",
        ],
        "low": [
            "okay",
            "fine",
            "alright",
            "good",
            "bad",
            "interesting",
            "curious",
            "wonder",
        ],
    }

    # Topic keywords for automatic tagging
    TOPIC_KEYWORDS = {
        "work": [
            "work",
            "job",
            "office",
            "meeting",
            "boss",
            "project",
            "client",
            "deadline",
            "colleague",
            "presentation",
        ],
        "health": [
            "health",
            "doctor",
            "sick",
            "medicine",
            "exercise",
            "sleep",
            "tired",
            "pain",
            "hospital",
            "therapy",
        ],
        "relationship": [
            "friend",
            "family",
            "partner",
            "relationship",
            "marriage",
            "dating",
            "kids",
            "parents",
            "sibling",
        ],
        "planning": [
            "plan",
            "goal",
            "tomorrow",
            "schedule",
            "task",
            "need to",
            "should",
            "going to",
            "want to",
        ],
        "emotion": [
            "feel",
            "feeling",
            "happy",
            "sad",
            "angry",
            "stressed",
            "anxious",
            "worried",
            "excited",
        ],
        "finance": [
            "money",
            "budget",
            "expense",
            "cost",
            "pay",
            "salary",
            "savings",
            "investment",
            "debt",
        ],
    }

    def __init__(
        self,
        silence_threshold_ms: int = 5000,
        min_episode_duration_ms: int = 3000,
        max_episode_duration_ms: int = 300000,  # 5 minutes
        min_episode_words: int = 5,
    ):
        """Initialize episode segmenter.

        Args:
            silence_threshold_ms: Silence duration to trigger boundary
            min_episode_duration_ms: Minimum episode duration
            max_episode_duration_ms: Maximum episode duration (force boundary)
            min_episode_words: Minimum words for valid episode
        """
        self.silence_threshold_ms = silence_threshold_ms
        self.min_episode_duration_ms = min_episode_duration_ms
        self.max_episode_duration_ms = max_episode_duration_ms
        self.min_episode_words = min_episode_words

        self._buffer = TranscriptBuffer(
            silence_threshold_ms=silence_threshold_ms,
            min_episode_words=min_episode_words,
        )

        self._episode_start_time: datetime | None = None
        self._episode_count = 0

    async def process_segment(
        self, segment: "TranscriptSegment"
    ) -> Episode | None:
        """Process a transcript segment, return Episode if boundary detected.

        Args:
            segment: Transcript segment to process

        Returns:
            Episode if boundary detected, None otherwise
        """
        # Track episode start time
        if self._episode_start_time is None:
            self._episode_start_time = datetime.now()

        # Check for explicit boundary markers
        text_lower = segment.text.lower()
        for marker in self.BOUNDARY_MARKERS:
            if marker in text_lower:
                # Force boundary before this segment
                episode = self._buffer.force_boundary("explicit")
                if episode:
                    episode = self._post_process_episode(episode)
                    self._episode_start_time = datetime.now()
                    return episode

        # Check for max duration boundary
        if self._episode_start_time:
            duration_ms = (datetime.now() - self._episode_start_time).total_seconds() * 1000
            if duration_ms > self.max_episode_duration_ms:
                episode = self._buffer.force_boundary("time")
                if episode:
                    episode = self._post_process_episode(episode)
                    self._episode_start_time = datetime.now()
                    return episode

        # Add to buffer (handles silence boundaries)
        episode = self._buffer.add_segment(segment)

        if episode:
            episode = self._post_process_episode(episode)
            self._episode_start_time = datetime.now()
            self._episode_count += 1

        return episode

    def _post_process_episode(self, episode: Episode) -> Episode:
        """Post-process episode: compute intensity and extract topics.

        Args:
            episode: Episode to process

        Returns:
            Episode with intensity and topic_tags filled
        """
        # Compute emotional intensity
        episode.intensity = self._compute_intensity(episode)

        # Extract topic tags
        episode.topic_tags = self._extract_topics(episode)

        return episode

    def _compute_intensity(self, episode: Episode) -> float:
        """Compute emotional intensity of episode.

        Args:
            episode: Episode to analyze

        Returns:
            Intensity score (0.0 to 1.0)
        """
        text = episode.plain_text.lower()
        word_count = max(1, episode.word_count)

        score = 0.0

        # Count keyword matches
        for word in self.INTENSITY_KEYWORDS["high"]:
            score += text.count(word) * 1.0
        for word in self.INTENSITY_KEYWORDS["medium"]:
            score += text.count(word) * 0.5
        for word in self.INTENSITY_KEYWORDS["low"]:
            score += text.count(word) * 0.2

        # Normalize by word count (expect ~1 intensity word per 10 words)
        normalized = score / (word_count * 0.1)

        return min(1.0, normalized)

    def _extract_topics(self, episode: Episode) -> list[str]:
        """Extract topic tags from episode.

        Args:
            episode: Episode to analyze

        Returns:
            List of topic tags
        """
        text = episode.plain_text.lower()
        tags = []

        for topic, keywords in self.TOPIC_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                tags.append(topic)

        return tags

    def flush(self) -> Episode | None:
        """Force finalize current episode.

        Returns:
            Episode if there were accumulated segments, None otherwise
        """
        episode = self._buffer.flush()
        if episode:
            episode = self._post_process_episode(episode)
            self._episode_start_time = None
        return episode

    @property
    def current_word_count(self) -> int:
        """Get word count of current (unflushed) episode."""
        return self._buffer.current_word_count

    @property
    def total_episodes(self) -> int:
        """Get total episodes created."""
        return self._episode_count

    @property
    def episode_duration_ms(self) -> int | None:
        """Get current episode duration in ms."""
        if self._episode_start_time:
            return int(
                (datetime.now() - self._episode_start_time).total_seconds() * 1000
            )
        return None

    def reset(self) -> None:
        """Reset segmenter state."""
        self._buffer.clear()
        self._episode_start_time = None
