"""
Episode Processor

Converts Episodes to memory artifacts (EvidenceShards) and RilaiEvents.
"""

import logging
import re
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from rilai.episodes.schema import Episode

if TYPE_CHECKING:
    from rilai.agencies.messages import RilaiEvent
    from rilai.memory.relational import EvidenceShard

logger = logging.getLogger(__name__)


class EpisodeProcessor:
    """Converts Episodes to memory artifacts.

    Extracts:
    - EvidenceShards: Exact quotes with provenance
    - RilaiEvents: For agent processing
    """

    # Evidence type detection patterns
    EVIDENCE_PATTERNS = {
        "vulnerability": [
            r"\b(scared|afraid|worried|anxious|nervous|terrified|overwhelmed)\b",
            r"\bi('m| am) (scared|afraid|worried|anxious|nervous)\b",
            r"\b(struggling|having trouble|can't cope)\b",
        ],
        "preference": [
            r"\bi (like|prefer|enjoy|love|hate|dislike)\b",
            r"\bi('d| would) (rather|prefer)\b",
            r"\bmy favorite\b",
            r"\bi (always|never) (want|like)\b",
        ],
        "boundary": [
            r"\bi (don't|won't|can't|refuse to)\b",
            r"\b(never|absolutely not|no way)\b",
            r"\bthat's (not okay|unacceptable)\b",
            r"\bi need (space|time|boundaries)\b",
        ],
        "value": [
            r"\b(important to me|matters to me|i believe|i think)\b",
            r"\bmy (values|principles|beliefs)\b",
            r"\bi (stand for|care about|prioritize)\b",
        ],
        "bio": [
            r"\bmy name is\b",
            r"\bi('m| am) (from|a|an)\b",
            r"\bi (work|live|grew up)\b",
            r"\bi have (been|worked|lived)\b",
        ],
        "commitment": [
            r"\bi (should|need to|have to|must|will|going to)\b",
            r"\bi('ll| will) (do|call|email|send|finish)\b",
            r"\b(tomorrow|next week|later|soon) i\b",
            r"\bremind me to\b",
        ],
        "decision": [
            r"\bi('m| am) (thinking about|considering|deciding)\b",
            r"\bshould i\b",
            r"\b(maybe|perhaps) i (should|could|will)\b",
            r"\bi can't decide\b",
        ],
    }

    def __init__(
        self,
        min_quote_words: int = 5,
        max_shards_per_episode: int = 10,
    ):
        """Initialize episode processor.

        Args:
            min_quote_words: Minimum words for a quote to be evidence
            max_shards_per_episode: Maximum evidence shards per episode
        """
        self.min_quote_words = min_quote_words
        self.max_shards_per_episode = max_shards_per_episode

        # Compile patterns for efficiency
        self._compiled_patterns = {
            etype: [re.compile(p, re.IGNORECASE) for p in patterns]
            for etype, patterns in self.EVIDENCE_PATTERNS.items()
        }

    def extract_evidence(self, episode: Episode) -> list["EvidenceShard"]:
        """Extract evidence shards from episode.

        Looks for:
        - Self-disclosures
        - Emotional expressions
        - Preferences/values
        - Commitments
        - Decisions

        Args:
            episode: Episode to process

        Returns:
            List of evidence shards
        """
        from rilai.memory.relational import EvidenceShard

        shards = []

        for i, turn in enumerate(episode.turns):
            # Skip very short utterances
            if turn.word_count < self.min_quote_words:
                continue

            text_lower = turn.text.lower()

            # Check for evidence patterns
            for evidence_type, patterns in self._compiled_patterns.items():
                for pattern in patterns:
                    if pattern.search(text_lower):
                        # Create evidence shard
                        shard = EvidenceShard.create(
                            quote=turn.text,
                            evidence_type=evidence_type,
                            turn_id=i,
                            confidence=0.6,  # Default confidence
                            context=f"Episode {episode.episode_id}, "
                            f"speaker: {turn.speaker}",
                        )

                        # Add episode provenance as metadata
                        # Note: EvidenceShard may not have metadata field,
                        # so we store it in context
                        shard.context = (
                            f"Episode: {episode.episode_id} | "
                            f"Speaker: {turn.speaker} | "
                            f"Turn: {i} | "
                            f"Topics: {', '.join(episode.topic_tags) or 'none'}"
                        )

                        shards.append(shard)
                        break  # One match per turn is enough

        # Limit to top shards (prioritize by evidence type importance)
        type_priority = {
            "commitment": 0,
            "decision": 1,
            "vulnerability": 2,
            "boundary": 3,
            "value": 4,
            "preference": 5,
            "bio": 6,
        }

        shards.sort(key=lambda s: type_priority.get(s.type, 99))

        return shards[: self.max_shards_per_episode]

    def episode_to_event(
        self, episode: Episode, session_id: str = ""
    ) -> "RilaiEvent":
        """Convert episode to a RilaiEvent for agent processing.

        Args:
            episode: Episode to convert
            session_id: Current session ID

        Returns:
            RilaiEvent for agent processing
        """
        from rilai.agencies.messages import RilaiEvent

        return RilaiEvent(
            event_id=f"episode-{episode.episode_id}",
            type="voice",  # Use voice type for audio-derived events
            content=episode.full_text,
            user_id="default",
            session_id=session_id or episode.session_id,
            timestamp=episode.start_ts,
            metadata={
                "episode_id": episode.episode_id,
                "speakers": episode.speakers,
                "duration_ms": episode.duration_ms,
                "intensity": episode.intensity,
                "topic_tags": episode.topic_tags,
                "boundary_type": episode.boundary_type,
                "turn_count": episode.turn_count,
                "word_count": episode.word_count,
                "source": episode.source,
            },
        )

    def extract_commitments(self, episode: Episode) -> list[dict]:
        """Extract commitments/TODOs from episode.

        Args:
            episode: Episode to process

        Returns:
            List of commitment dicts with text, deadline (if any), confidence
        """
        commitments = []
        commitment_patterns = self._compiled_patterns.get("commitment", [])

        for turn in episode.turns:
            text_lower = turn.text.lower()

            for pattern in commitment_patterns:
                match = pattern.search(text_lower)
                if match:
                    # Extract deadline hints
                    deadline = None
                    if "tomorrow" in text_lower:
                        deadline = "tomorrow"
                    elif "next week" in text_lower:
                        deadline = "next_week"
                    elif "today" in text_lower:
                        deadline = "today"

                    commitments.append(
                        {
                            "text": turn.text,
                            "speaker": turn.speaker,
                            "deadline": deadline,
                            "confidence": turn.confidence,
                            "episode_id": episode.episode_id,
                            "timestamp": turn.start_ts.isoformat(),
                        }
                    )
                    break

        return commitments

    def extract_decisions(self, episode: Episode) -> list[dict]:
        """Extract unresolved decisions from episode.

        Args:
            episode: Episode to process

        Returns:
            List of decision dicts with topic, options (if mentioned), confidence
        """
        decisions = []
        decision_patterns = self._compiled_patterns.get("decision", [])

        for turn in episode.turns:
            text_lower = turn.text.lower()

            for pattern in decision_patterns:
                match = pattern.search(text_lower)
                if match:
                    # Try to extract what the decision is about
                    # Simple heuristic: use the rest of the sentence
                    topic = turn.text

                    decisions.append(
                        {
                            "topic": topic,
                            "speaker": turn.speaker,
                            "confidence": turn.confidence,
                            "episode_id": episode.episode_id,
                            "timestamp": turn.start_ts.isoformat(),
                        }
                    )
                    break

        return decisions

    def get_episode_summary(self, episode: Episode) -> str:
        """Generate a brief summary of the episode.

        Args:
            episode: Episode to summarize

        Returns:
            Brief summary string
        """
        parts = []

        # Duration
        duration_min = episode.duration_ms / 60000
        parts.append(f"{duration_min:.1f}min conversation")

        # Speakers
        if len(episode.speakers) == 1:
            parts.append(f"by {episode.speakers[0]}")
        else:
            parts.append(f"between {', '.join(episode.speakers)}")

        # Topics
        if episode.topic_tags:
            parts.append(f"about {', '.join(episode.topic_tags)}")

        # Intensity
        if episode.intensity > 0.7:
            parts.append("(high intensity)")
        elif episode.intensity > 0.4:
            parts.append("(moderate intensity)")

        return " ".join(parts)
