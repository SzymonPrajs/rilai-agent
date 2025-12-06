"""
Rilai v2 Configuration

Copy this file to config.py and fill in your values.
config.py is gitignored to keep secrets safe.
"""

# =============================================================================
# API Keys
# =============================================================================

OPENROUTER_API_KEY = "sk-or-v1-..."  # Get from https://openrouter.ai/keys

# =============================================================================
# Models
# =============================================================================

# Standard models (for agents and council)
MODELS = {
    "small": "meta-llama/llama-3.1-8b-instruct",      # Fast agent assessments
    "medium": "meta-llama/llama-3.3-70b-instruct",    # Council synthesis
    "large": "deepseek/deepseek-chat",                # Deep reasoning tasks
}

# Thinking model variants (for deliberation, complex reasoning)
THINKING_MODELS = {
    "small": "deepseek/deepseek-r1-distill-qwen-7b",
    "medium": "anthropic/claude-3.5-sonnet:thinking",
    "large": "deepseek/deepseek-r1",
}

# Reasoning effort per context
REASONING_EFFORT = {
    "agent_assess": "minimal",        # Quick assessments
    "deliberation": "medium",         # Multi-round discussion
    "council_synthesis": "high",      # Final decision
}

# =============================================================================
# Agencies
# =============================================================================

# Which agencies to enable ("all" or list of names)
ENABLED_AGENCIES = "all"
# ENABLED_AGENCIES = ["planning", "emotion", "social", "reasoning"]

# =============================================================================
# Brain Daemon
# =============================================================================

DAEMON_TICK_INTERVAL = 60.0           # Seconds between background ticks
DAEMON_URGENCY_THRESHOLD = "high"     # Minimum urgency to proactively speak

# =============================================================================
# Deliberation
# =============================================================================

DELIBERATION_MAX_ROUNDS = 3           # Maximum deliberation rounds
DELIBERATION_CONSENSUS_THRESHOLD = 0.8  # Consensus level to trigger early exit
DELIBERATION_USE_THINKING = True      # Use thinking models for deliberation

# =============================================================================
# Performance
# =============================================================================

AGENCY_TIMEOUT_MS = 30000             # Timeout for entire agency
AGENT_TIMEOUT_MS = 15000              # Timeout for single agent

# =============================================================================
# Paths
# =============================================================================

DATA_DIR = "data"                     # Runtime data directory
