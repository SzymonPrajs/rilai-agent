"""
EpisodeBuilder

Converts a stream of UtteranceEvents into Episodes.
Handles speaker continuity, silence gap detection, and episode boundaries.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable

from rilai.core.events import Event, EventType, event_bus
from rilai.core.utterance import UtteranceEvent
from rilai.episodes.schema import Episode, SpeechTurn

logger = logging.getLogger(__name__)


@dataclass
class EpisodeBuilderConfig:
    """Configuration for episode building."""

    # Minimum duration to consider an episode complete
    min_duration_ms: int = 3000

    # Maximum duration before forcing episode boundary
    max_duration_ms: int = 300000  # 5 minutes

    # Silence gap to trigger episode boundary
    silence_gap_ms: int = 30000  # 30 seconds

    # Minimum turns to consider an episode valid
    min_turns: int = 1


@dataclass
class EpisodeBuilderState:
    """Current state of the episode builder."""

    # Current episode being built
    current_episode_id: str | None = None
    current_turns: list[SpeechTurn] = field(default_factory=list)
    episode_start: datetime | None = None
    last_utterance_time: datetime | None = None

    # Statistics
    total_episodes: int = 0
    total_utterances: int = 0


class EpisodeBuilder:
    """Builds Episodes from a stream of UtteranceEvents.

    Detects episode boundaries based on:
    - Silence gaps (configurable threshold)
    - Maximum duration exceeded
    - Channel changes

    Emits EPISODE_BUILT events when episodes are complete.
    """

    def __init__(
        self,
        config: EpisodeBuilderConfig | None = None,
        on_episode: Callable[[Episode], None] | None = None,
        session_id: str = "",
    ):
        """Initialize the episode builder.

        Args:
            config: Builder configuration
            on_episode: Callback when episode is complete
            session_id: Current session ID
        """
        self.config = config or EpisodeBuilderConfig()
        self._on_episode = on_episode
        self.session_id = session_id

        self._state = EpisodeBuilderState()
        self._current_channel: str | None = None

    @property
    def state(self) -> EpisodeBuilderState:
        return self._state

    @property
    def is_building(self) -> bool:
        """Whether we're currently building an episode."""
        return self._state.current_episode_id is not None

    @property
    def current_duration_ms(self) -> int:
        """Duration of current episode in milliseconds."""
        if not self._state.episode_start or not self._state.last_utterance_time:
            return 0
        delta = self._state.last_utterance_time - self._state.episode_start
        return int(delta.total_seconds() * 1000)

    async def process(self, utterance: UtteranceEvent) -> Episode | None:
        """Process an utterance and potentially complete an episode.

        Args:
            utterance: The utterance to process

        Returns:
            Completed Episode if boundary was triggered, None otherwise
        """
        self._state.total_utterances += 1
        completed_episode: Episode | None = None

        # Check if we need to close current episode
        if self.is_building:
            should_close = self._should_close_episode(utterance)
            if should_close:
                completed_episode = await self._close_episode(should_close)

        # Start new episode if needed
        if not self.is_building:
            self._start_episode(utterance)

        # Add utterance to current episode
        self._add_utterance(utterance)

        # Check if max duration exceeded
        if self.current_duration_ms >= self.config.max_duration_ms:
            completed_episode = await self._close_episode("max_duration")

        return completed_episode

    async def flush(self) -> Episode | None:
        """Force flush the current episode.

        Returns:
            The flushed episode if there was one
        """
        if self.is_building and self._state.current_turns:
            return await self._close_episode("flush")
        return None

    def _should_close_episode(self, utterance: UtteranceEvent) -> str | None:
        """Check if current episode should be closed.

        Returns:
            Boundary reason string if should close, None otherwise
        """
        if not self._state.last_utterance_time:
            return None

        # Check silence gap
        gap = utterance.ts_start - self._state.last_utterance_time
        gap_ms = int(gap.total_seconds() * 1000)
        if gap_ms >= self.config.silence_gap_ms:
            return "silence_gap"

        # Check channel change
        if self._current_channel and utterance.channel != self._current_channel:
            return "channel_change"

        return None

    def _start_episode(self, utterance: UtteranceEvent) -> None:
        """Start a new episode."""
        self._state.current_episode_id = str(uuid.uuid4())
        self._state.current_turns = []
        self._state.episode_start = utterance.ts_start
        self._current_channel = utterance.channel

        logger.debug(f"Started episode {self._state.current_episode_id}")

    def _add_utterance(self, utterance: UtteranceEvent) -> None:
        """Add an utterance to the current episode."""
        turn = SpeechTurn.create(
            speaker=utterance.speaker_id,
            text=utterance.text,
            start_ts=utterance.ts_start,
            end_ts=utterance.ts_end,
            confidence=utterance.confidence,
        )
        self._state.current_turns.append(turn)
        self._state.last_utterance_time = utterance.ts_end

    async def _close_episode(self, boundary_type: str) -> Episode:
        """Close the current episode and emit it.

        Args:
            boundary_type: What triggered the boundary

        Returns:
            The completed Episode
        """
        episode = self._build_episode(boundary_type)

        # Update state
        self._state.total_episodes += 1
        self._state.current_episode_id = None
        self._state.current_turns = []
        self._state.episode_start = None
        self._state.last_utterance_time = None
        self._current_channel = None

        logger.info(
            f"Episode {episode.episode_id} completed: "
            f"{episode.turn_count} turns, {episode.word_count} words, "
            f"boundary={boundary_type}"
        )

        # Emit event
        await event_bus.emit(
            Event(
                EventType.EPISODE_BUILT,
                {
                    "episode_id": episode.episode_id,
                    "turn_count": episode.turn_count,
                    "word_count": episode.word_count,
                    "duration_ms": episode.duration_ms,
                    "boundary_type": boundary_type,
                    "speakers": episode.speakers,
                },
            )
        )

        # Call callback
        if self._on_episode:
            self._on_episode(episode)

        return episode

    def _build_episode(self, boundary_type: str) -> Episode:
        """Build an Episode from current state."""
        turns = self._state.current_turns

        # Collect speakers
        speakers = list(set(turn.speaker for turn in turns))

        # Calculate duration
        if turns:
            start_ts = turns[0].start_ts
            end_ts = turns[-1].end_ts
        else:
            start_ts = end_ts = datetime.now()

        # Calculate intensity (simple heuristic based on turn frequency)
        duration_seconds = max(1, (end_ts - start_ts).total_seconds())
        turn_rate = len(turns) / (duration_seconds / 60)  # turns per minute
        intensity = min(1.0, turn_rate / 10)  # Normalize to 0-1

        # Collect full text
        full_text = " ".join(turn.text for turn in turns)

        return Episode(
            episode_id=self._state.current_episode_id or str(uuid.uuid4()),
            session_id=self.session_id,
            start_ts=start_ts,
            end_ts=end_ts,
            turns=turns,
            speakers=speakers,
            intensity=intensity,
            topic_tags=[],  # Will be filled by episode processor
            boundary_type=boundary_type,
            source="synthetic",  # Will be updated based on actual source
        )

    def get_stats(self) -> dict:
        """Get builder statistics."""
        return {
            "total_episodes": self._state.total_episodes,
            "total_utterances": self._state.total_utterances,
            "is_building": self.is_building,
            "current_duration_ms": self.current_duration_ms if self.is_building else 0,
            "current_turns": len(self._state.current_turns),
        }
