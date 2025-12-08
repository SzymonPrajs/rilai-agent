"""
Input Adapters Module

Provides different input sources that all produce UtteranceEvents.

Available adapters:
- SyntheticTextAdapter: Reads JSONL scenario files for testing
- AudioAdapter: Wraps real mic + STT pipeline
"""

from rilai.adapters.protocol import InputAdapter, PlaybackMode, BaseInputAdapter
from rilai.adapters.synthetic import SyntheticTextAdapter, ChunkingConfig
from rilai.adapters.audio import AudioAdapter

__all__ = [
    "InputAdapter",
    "BaseInputAdapter",
    "PlaybackMode",
    "SyntheticTextAdapter",
    "ChunkingConfig",
    "AudioAdapter",
]
