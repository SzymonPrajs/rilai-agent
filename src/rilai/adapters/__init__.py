"""
Input Adapters Module

Provides different input sources that all produce UtteranceEvents.

Available adapters:
- SyntheticTextAdapter: Reads JSONL scenario files for testing
- AudioAdapter: Wraps real mic + STT pipeline (future)
"""

from rilai.adapters.protocol import InputAdapter, PlaybackMode
from rilai.adapters.synthetic import SyntheticTextAdapter

__all__ = [
    "InputAdapter",
    "PlaybackMode",
    "SyntheticTextAdapter",
]
