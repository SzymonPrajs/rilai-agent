"""
Rilai v2 Configuration

Copy this file to config.py and fill in your values.
config.py is gitignored to keep secrets safe.
"""

# =============================================================================
# API Keys
# =============================================================================

OPENROUTER_API_KEY = "sk-or-v1-..."  # Get from https://openrouter.ai/keys
ELEVENLABS_API_KEY = ""  # Get from https://elevenlabs.io/app/settings/api-keys

# =============================================================================
# Models
# =============================================================================

# All models (treated as thinking models)
MODELS = {
    "tiny": "meta-llama/llama-3.2-1b-instruct",       # Ambient mode (lowest cost)
    "small": "meta-llama/llama-3.1-8b-instruct",      # Fast agent assessments
    "medium": "meta-llama/llama-3.3-70b-instruct",    # Council synthesis
    "large": "deepseek/deepseek-chat",                # Deep reasoning tasks
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

# =============================================================================
# Performance
# =============================================================================

AGENCY_TIMEOUT_MS = 30000             # Timeout for entire agency
AGENT_TIMEOUT_MS = 15000              # Timeout for single agent

# =============================================================================
# Paths
# =============================================================================

DATA_DIR = "data"                     # Runtime data directory

# =============================================================================
# Audio Capture (Ambient Mode)
# =============================================================================

AUDIO_SAMPLE_RATE = 16000             # Sample rate for audio capture (Hz)
AUDIO_VAD_THRESHOLD = 0.5             # Voice activity detection threshold (0.0-1.0)
AUDIO_SILENCE_TIMEOUT_MS = 5000       # Silence duration to end episode (ms)
AUDIO_CHUNK_DURATION_MS = 100         # Duration per audio chunk (ms)

# =============================================================================
# ElevenLabs STT
# =============================================================================

ELEVENLABS_STT_MODEL = "scribe_v1"    # ElevenLabs transcription model
ELEVENLABS_STT_LANGUAGE = "en"        # Language code for transcription

# =============================================================================
# Episode Segmentation
# =============================================================================

EPISODE_MIN_DURATION_MS = 3000        # Minimum episode duration (ms)
EPISODE_MAX_DURATION_MS = 300000      # Maximum episode duration (5 min)
EPISODE_SILENCE_GAP_MS = 5000         # Silence gap to trigger boundary (ms)

# =============================================================================
# Transcript Replay (Testing)
# =============================================================================

AUDIO_REPLAY_ENABLED = False          # Enable transcript replay mode
AUDIO_REPLAY_PATH = ""                # Path to JSONL transcript file
AUDIO_REPLAY_SPEED = 10.0             # Replay speed multiplier

# =============================================================================
# Proactive Intervention
# =============================================================================

PROACTIVE_HOURLY_BUDGET = 3.0         # Max interrupts per hour
PROACTIVE_DAILY_BUDGET = 12.0         # Max interrupts per day
PROACTIVE_QUIET_HOURS_START = 22      # Quiet hours start (24h format)
PROACTIVE_QUIET_HOURS_END = 8         # Quiet hours end (24h format)
PROACTIVE_NOTIFICATIONS_ENABLED = True  # Enable macOS notifications for L4

# =============================================================================
# Ambient Mode
# =============================================================================

AMBIENT_ENABLED = False               # Enable ambient cognitive processing
AMBIENT_DAYDREAM_TIMEOUT_S = 60       # Seconds before entering daydream mode
AMBIENT_STAKES_THRESHOLD = 0.7        # Stakes threshold to escalate to interactive
