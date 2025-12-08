"""
TUI Color Theme

Industrial/neuroscience dashboard aesthetic with semantic color coding.
"""

# Background colors
BG_MAIN = "#1A1A2E"       # Deep charcoal - main background
BG_PANEL = "#16213E"      # Slate - panel backgrounds
BG_INPUT = "#0F0F1A"      # Darker for input areas
BORDER = "#2E2E4D"        # Dim gray - panel borders

# Semantic colors for different subsystems
COLOR_STANCE = "#F5A623"      # Amber/Orange - affective states
COLOR_SENSORS = "#7ED321"     # Green - input detection layer
COLOR_AGENTS = "#50E3C2"      # Cyan - cognitive processes
COLOR_CRITICS = "#BD10E0"     # Magenta - validation layer
COLOR_WORKSPACE = "#F8E71C"   # Yellow - global broadcast packet
COLOR_MEMORY = "#4A90D9"      # Blue - evidence/hypotheses
COLOR_GENERATORS = "#FF6B6B"  # Coral - response generation

# Chat colors
COLOR_USER = "#FFFFFF"        # White - user messages
COLOR_RILAI = "#9DBCD4"       # Soft blue - system responses
COLOR_SYSTEM = "#6B7280"      # Gray - system messages

# Status colors
COLOR_PASS = "#7ED321"        # Green - pass/success
COLOR_FAIL = "#FF4757"        # Red - fail/error
COLOR_WARN = "#F5A623"        # Amber - warning
COLOR_MUTED = "#6B7280"       # Gray - muted/inactive

# Bar visualization characters
BAR_FILLED = "█"
BAR_EMPTY = "░"
BAR_HALF = "▓"


def make_bar(value: float, width: int = 10, min_val: float = 0.0, max_val: float = 1.0) -> str:
    """Create a text-based bar visualization."""
    normalized = (value - min_val) / (max_val - min_val) if max_val > min_val else 0
    normalized = max(0, min(1, normalized))
    filled = int(normalized * width)
    return BAR_FILLED * filled + BAR_EMPTY * (width - filled)


def colorize_bar(value: float, positive_color: str = COLOR_PASS, negative_color: str = COLOR_FAIL) -> str:
    """Get color for a bar based on value."""
    if value > 0.6:
        return positive_color
    elif value > 0.3:
        return COLOR_WARN
    else:
        return COLOR_MUTED
