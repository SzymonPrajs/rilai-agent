"""
Ambient Mode Module

Manages operating modes and ambient processing for the cognitive co-processor.

Provides:
- ModeManager: State machine for operating mode transitions
- OperatingMode: Enum of available modes
- AmbientProcessor: Processes ambient input streams
"""

from rilai.ambient.mode_manager import ModeManager, OperatingMode
from rilai.ambient.processor import AmbientProcessor

__all__ = [
    "ModeManager",
    "OperatingMode",
    "AmbientProcessor",
]
