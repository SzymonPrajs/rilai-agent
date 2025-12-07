"""Default configuration values for Rilai v2."""

from typing import Literal

# API Keys (must be overridden in config.py)
OPENROUTER_API_KEY = ""

# Models (all treated as thinking models)
MODELS = {
    "small": "meta-llama/llama-3.1-8b-instruct",
    "medium": "meta-llama/llama-3.3-70b-instruct",
    "large": "deepseek/deepseek-chat",
}

REASONING_EFFORT: dict[str, Literal["minimal", "low", "medium", "high"]] = {
    "agent_assess": "minimal",
    "deliberation": "medium",
    "council_synthesis": "high",
}

# Agencies
ENABLED_AGENCIES: str | list[str] = "all"

# Brain Daemon
DAEMON_TICK_INTERVAL: float = 60.0
DAEMON_URGENCY_THRESHOLD: Literal["low", "medium", "high", "critical"] = "high"

# Deliberation
DELIBERATION_MAX_ROUNDS: int = 3
DELIBERATION_CONSENSUS_THRESHOLD: float = 0.8

# Performance
AGENCY_TIMEOUT_MS: int = 30000
AGENT_TIMEOUT_MS: int = 15000

# Paths
DATA_DIR: str = "data"

# All configurable keys (for validation)
CONFIG_KEYS = {
    "OPENROUTER_API_KEY",
    "MODELS",
    "REASONING_EFFORT",
    "ENABLED_AGENCIES",
    "DAEMON_TICK_INTERVAL",
    "DAEMON_URGENCY_THRESHOLD",
    "DELIBERATION_MAX_ROUNDS",
    "DELIBERATION_CONSENSUS_THRESHOLD",
    "AGENCY_TIMEOUT_MS",
    "AGENT_TIMEOUT_MS",
    "DATA_DIR",
}
