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
    "tiny":  "openai/gpt-oss-20b",           # Very fast agent sensors
    "small": "openai/gpt-oss-120b",          # Fast agent assessments
    "medium": "x-ai/grok-4.1-fast",          # Council synthesis
    "large":  "google/gemini-3-pro-preview", # Deep reasoning tasks
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
# ElevenLabs STT (Scribe Realtime v2)
# =============================================================================

# Model configuration
ELEVENLABS_STT_MODEL = "scribe_v2_realtime"  # Realtime streaming model
ELEVENLABS_STT_LANGUAGE = "en"               # ISO-639-1/3 language code (empty = auto-detect)

# Audio format settings
ELEVENLABS_STT_AUDIO_FORMAT = "pcm_16000"    # pcm_8000, pcm_16000, pcm_22050, pcm_24000, pcm_44100, pcm_48000, ulaw_8000
ELEVENLABS_STT_SAMPLE_RATE = 16000           # Must match audio format

# VAD (Voice Activity Detection) settings
ELEVENLABS_STT_COMMIT_STRATEGY = "vad"       # "manual" or "vad" (auto-commit on silence)
ELEVENLABS_STT_VAD_THRESHOLD = 0.4           # VAD sensitivity 0.1-0.9 (lower = more sensitive)
ELEVENLABS_STT_VAD_SILENCE_SECS = 1.5        # Seconds of silence before VAD commit

# Output settings
ELEVENLABS_STT_INCLUDE_TIMESTAMPS = True     # Include word-level timestamps in output

# WebSocket settings
ELEVENLABS_STT_CHUNK_INTERVAL_MS = 100       # Interval between audio chunk sends (100-1000ms recommended)
ELEVENLABS_STT_RECONNECT_ATTEMPTS = 3        # Max reconnection attempts on failure
ELEVENLABS_STT_RECONNECT_DELAY_MS = 1000     # Initial delay between reconnection attempts (exponential backoff)

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
