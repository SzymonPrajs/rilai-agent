"""Textual TUI for Rilai v2.

Provides a split-screen interface:
- Left: Chat panel with user/assistant messages
- Right: Live telemetry inspector (sensors, stance, agents, workspace, critics, memory)
"""

from rilai.tui.app import RilaiTUI, RealEngine, MockEngine

__all__ = ["RilaiTUI", "RealEngine", "MockEngine"]
