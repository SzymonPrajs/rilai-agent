"""
Episode Segmentation Module

Segments continuous audio/transcript streams into discrete episodes
and extracts memory artifacts.

Provides:
- Episode, SpeechTurn: Data structures for episodes
- TranscriptBuffer: Accumulates transcript segments
- EpisodeSegmenter: Detects episode boundaries
- EpisodeProcessor: Converts episodes to memory artifacts
"""

from rilai.episodes.buffer import TranscriptBuffer
from rilai.episodes.processor import EpisodeProcessor
from rilai.episodes.schema import Episode, SpeechTurn
from rilai.episodes.segmenter import EpisodeSegmenter

__all__ = [
    # Data structures
    "Episode",
    "SpeechTurn",
    # Components
    "TranscriptBuffer",
    "EpisodeSegmenter",
    "EpisodeProcessor",
]
