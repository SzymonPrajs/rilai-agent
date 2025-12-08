"""
Ambient Processor

Processes ambient input streams (audio transcripts, episodes) through
the mode-appropriate pipeline.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Callable

from rilai.ambient.mode_manager import ModeManager, OperatingMode
from rilai.audio.service import AudioCaptureService
from rilai.audio.stt import TranscriptSegment
from rilai.core.events import Event, EventType, event_bus
from rilai.episodes.processor import EpisodeProcessor
from rilai.episodes.schema import Episode
from rilai.episodes.segmenter import EpisodeSegmenter

if TYPE_CHECKING:
    from rilai.config import Config
    from rilai.memory.relational import EvidenceShard, RelationalMemoryStore

logger = logging.getLogger(__name__)


@dataclass
class AmbientProcessResult:
    """Result from ambient processing."""

    episode: Episode | None = None
    evidence_count: int = 0
    stakes_estimate: float = 0.0
    commitments_found: int = 0
    decisions_found: int = 0
    should_escalate: bool = False
    escalation_reason: str = ""


class AmbientProcessor:
    """Processes ambient input streams.

    Coordinates:
    - Audio capture service
    - Episode segmentation
    - Evidence extraction
    - Stakes estimation
    - Mode transitions
    """

    def __init__(
        self,
        config: "Config",
        mode_manager: ModeManager,
        memory_store: "RelationalMemoryStore | None" = None,
        on_episode: Callable[[Episode], None] | None = None,
        on_evidence: Callable[["EvidenceShard"], None] | None = None,
    ):
        """Initialize ambient processor.

        Args:
            config: Application configuration
            mode_manager: Mode manager instance
            memory_store: Optional relational memory store
            on_episode: Callback for completed episodes
            on_evidence: Callback for extracted evidence
        """
        self.config = config
        self.mode_manager = mode_manager
        self.memory_store = memory_store

        self._on_episode = on_episode
        self._on_evidence = on_evidence

        # Components
        self._audio_service: AudioCaptureService | None = None
        self._segmenter = EpisodeSegmenter()
        self._episode_processor = EpisodeProcessor()

        # State
        self._running = False
        self._process_task: asyncio.Task | None = None

        # Statistics
        self._stats = {
            "episodes_processed": 0,
            "evidence_extracted": 0,
            "commitments_found": 0,
            "decisions_found": 0,
            "high_stakes_events": 0,
        }

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def stats(self) -> dict:
        return self._stats.copy()

    async def start(self) -> None:
        """Start ambient processing."""
        if self._running:
            logger.warning("Ambient processor already running")
            return

        self._running = True

        # Initialize audio service
        self._audio_service = AudioCaptureService(
            config=self.config,
            on_transcript=self._handle_transcript_sync,
        )
        await self._audio_service.start()

        # Transition to ambient ingest mode
        await self.mode_manager.transition_to(
            OperatingMode.AMBIENT_INGEST, "ambient_start"
        )

        logger.info("Ambient processor started")

    async def stop(self) -> None:
        """Stop ambient processing."""
        self._running = False

        # Flush any pending episode
        episode = self._segmenter.flush()
        if episode:
            await self._process_episode(episode)

        # Stop audio service
        if self._audio_service:
            await self._audio_service.stop()
            self._audio_service = None

        # Transition to idle
        await self.mode_manager.transition_to(
            OperatingMode.IDLE_DAYDREAM, "ambient_stop"
        )

        logger.info(f"Ambient processor stopped. Stats: {self._stats}")

    def _handle_transcript_sync(self, segment: TranscriptSegment) -> None:
        """Synchronous wrapper for async transcript handling."""
        asyncio.create_task(self._handle_transcript(segment))

    async def _handle_transcript(self, segment: TranscriptSegment) -> None:
        """Handle incoming transcript segment.

        Args:
            segment: Transcript segment from audio service
        """
        if not self._running:
            return

        # Process through segmenter
        episode = await self._segmenter.process_segment(segment)

        if episode:
            await self._process_episode(episode)

    async def _process_episode(self, episode: Episode) -> AmbientProcessResult:
        """Process a completed episode.

        Args:
            episode: Completed episode to process

        Returns:
            Processing result
        """
        result = AmbientProcessResult(episode=episode)

        self._stats["episodes_processed"] += 1

        logger.info(
            f"Processing episode {episode.episode_id}: "
            f"{episode.turn_count} turns, {episode.word_count} words, "
            f"topics={episode.topic_tags}"
        )

        # Extract evidence
        evidence_shards = self._episode_processor.extract_evidence(episode)
        result.evidence_count = len(evidence_shards)
        self._stats["evidence_extracted"] += len(evidence_shards)

        # Store evidence
        if self.memory_store:
            session_id = getattr(self.config, "session_id", "")
            for shard in evidence_shards:
                self.memory_store.add_evidence(shard, session_id)
                if self._on_evidence:
                    self._on_evidence(shard)

        # Extract commitments
        commitments = self._episode_processor.extract_commitments(episode)
        result.commitments_found = len(commitments)
        self._stats["commitments_found"] += len(commitments)

        # Extract decisions
        decisions = self._episode_processor.extract_decisions(episode)
        result.decisions_found = len(decisions)
        self._stats["decisions_found"] += len(decisions)

        # Estimate stakes
        result.stakes_estimate = self._estimate_stakes(
            episode, evidence_shards, commitments, decisions
        )

        # Update mode manager
        self.mode_manager.update_stakes(result.stakes_estimate)

        # Check for escalation
        if result.stakes_estimate > ModeManager.STAKES_THRESHOLD:
            result.should_escalate = True
            result.escalation_reason = "high_stakes"
            self._stats["high_stakes_events"] += 1

            await self.mode_manager.auto_transition(
                stakes=result.stakes_estimate
            )

        # Emit episode completed event
        await event_bus.emit(
            Event(
                EventType.EPISODE_COMPLETED
                if hasattr(EventType, "EPISODE_COMPLETED")
                else EventType.PROCESSING_COMPLETED,
                {
                    "episode_id": episode.episode_id,
                    "duration_ms": episode.duration_ms,
                    "word_count": episode.word_count,
                    "evidence_count": result.evidence_count,
                    "stakes": result.stakes_estimate,
                    "topics": episode.topic_tags,
                },
            )
        )

        # Call episode callback
        if self._on_episode:
            self._on_episode(episode)

        return result

    def _estimate_stakes(
        self,
        episode: Episode,
        evidence: list["EvidenceShard"],
        commitments: list[dict],
        decisions: list[dict],
    ) -> float:
        """Estimate stakes level for an episode.

        Args:
            episode: The episode
            evidence: Extracted evidence shards
            commitments: Extracted commitments
            decisions: Extracted decisions

        Returns:
            Stakes estimate (0.0 to 1.0)
        """
        stakes = 0.0

        # Base stakes from intensity
        stakes += episode.intensity * 0.3

        # Stakes from evidence types
        high_stakes_types = {"vulnerability", "boundary", "commitment", "decision"}
        for shard in evidence:
            if shard.type in high_stakes_types:
                stakes += 0.15

        # Stakes from commitments (especially with deadlines)
        for commitment in commitments:
            stakes += 0.1
            if commitment.get("deadline") == "today":
                stakes += 0.2
            elif commitment.get("deadline") == "tomorrow":
                stakes += 0.1

        # Stakes from unresolved decisions
        stakes += len(decisions) * 0.1

        # Stakes from topics
        high_stakes_topics = {"health", "finance", "relationship"}
        for topic in episode.topic_tags:
            if topic in high_stakes_topics:
                stakes += 0.1

        return min(1.0, stakes)

    async def process_manual_input(self, text: str, speaker: str = "user") -> AmbientProcessResult:
        """Process manual text input (for testing or non-audio input).

        Args:
            text: Text to process
            speaker: Speaker identifier

        Returns:
            Processing result
        """
        # Create a fake transcript segment
        segment = TranscriptSegment(
            segment_id=f"manual-{datetime.now().timestamp()}",
            text=text,
            is_final=True,
            confidence=1.0,
            start_ms=0,
            end_ms=1000,
            speaker=speaker,
        )

        # Process through segmenter
        episode = await self._segmenter.process_segment(segment)

        if episode:
            return await self._process_episode(episode)

        return AmbientProcessResult()

    def flush_episode(self) -> Episode | None:
        """Force flush the current episode.

        Returns:
            Episode if there was content, None otherwise
        """
        return self._segmenter.flush()

    def get_current_episode_stats(self) -> dict:
        """Get statistics about the current (unflushed) episode.

        Returns:
            Dictionary of current episode stats
        """
        return {
            "word_count": self._segmenter.current_word_count,
            "duration_ms": self._segmenter.episode_duration_ms,
            "total_episodes": self._segmenter.total_episodes,
        }
