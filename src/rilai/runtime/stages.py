"""Stage implementations for TurnRunner."""

import re
from typing import AsyncIterator, TYPE_CHECKING

from rilai.contracts.events import EngineEvent, EventKind

if TYPE_CHECKING:
    from rilai.runtime.turn_runner import TurnRunner
    from rilai.runtime.workspace import Workspace
    from rilai.runtime.scheduler import Scheduler


# ─────────────────────────────────────────────────────────────────────────────
# Stage 1: Fast Sensors
# ─────────────────────────────────────────────────────────────────────────────

# Keyword patterns for fast sensor extraction
EMOTION_WORDS = {"feel", "feeling", "happy", "sad", "angry", "anxious", "stressed", "tired", "overwhelmed"}
PROBLEM_WORDS = {"problem", "issue", "bug", "error", "wrong", "broken", "help", "stuck"}
SOCIAL_WORDS = {"friend", "family", "relationship", "they", "meeting", "people"}
PLANNING_WORDS = {"plan", "goal", "task", "deadline", "schedule", "tomorrow", "next"}
ACTION_WORDS = {"do", "make", "create", "build", "start", "finish", "run"}
SAFETY_WORDS = {"kill", "suicide", "harm", "hurt", "die", "death", "end it"}


def run_fast_sensors(text: str) -> dict[str, float]:
    """Extract sensor probabilities from text without LLM.

    Returns:
        Dict of sensor_name -> probability [0.0, 1.0]
    """
    text_lower = text.lower()
    words = set(re.findall(r'\b\w+\b', text_lower))
    word_count = len(text.split())
    is_short = word_count < 10
    is_question = "?" in text

    sensors = {
        "vulnerability": 0.0,
        "advice_requested": 0.0,
        "relational_bid": 0.0,
        "ai_feelings_probe": 0.0,
        "humor_masking": 0.0,
        "rupture": 0.0,
        "ambiguity": 0.0,
        "safety_risk": 0.0,
        "prompt_injection": 0.0,
    }

    # Vulnerability: emotion words + short messages
    emotion_hits = len(words & EMOTION_WORDS)
    if emotion_hits > 0:
        sensors["vulnerability"] = min(0.3 + emotion_hits * 0.2, 0.9)

    # Advice requested: problem words + questions
    problem_hits = len(words & PROBLEM_WORDS)
    if problem_hits > 0 and is_question:
        sensors["advice_requested"] = min(0.4 + problem_hits * 0.15, 0.9)

    # Relational bid: social words + short
    social_hits = len(words & SOCIAL_WORDS)
    if social_hits > 0 and is_short:
        sensors["relational_bid"] = min(0.3 + social_hits * 0.2, 0.8)

    # AI feelings probe: questions about AI/feelings
    ai_words = {"you", "feel", "think", "are you", "do you"}
    if is_question and len(words & ai_words) >= 2:
        sensors["ai_feelings_probe"] = 0.6

    # Ambiguity: very short, no clear markers
    if is_short and emotion_hits == 0 and problem_hits == 0:
        sensors["ambiguity"] = 0.5

    # Safety risk: explicit safety words
    safety_hits = len(words & SAFETY_WORDS)
    if safety_hits > 0:
        sensors["safety_risk"] = min(0.5 + safety_hits * 0.2, 1.0)

    # Prompt injection: suspicious patterns
    injection_patterns = ["ignore", "pretend", "forget", "system prompt", "jailbreak"]
    for pattern in injection_patterns:
        if pattern in text_lower:
            sensors["prompt_injection"] = 0.8
            break

    return sensors


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2: Memory Retrieval (stub - implemented in 08-memory)
# ─────────────────────────────────────────────────────────────────────────────

async def run_memory_retrieval(
    runner: "TurnRunner",
    workspace: "Workspace",
) -> AsyncIterator[EngineEvent]:
    """Retrieve context from memory system.

    Stub implementation - will be replaced by 08-memory module.
    """
    # Stub: emit empty retrieval
    workspace.retrieved_episodes = []
    workspace.user_facts = []
    workspace.open_threads = []

    yield runner._emit(
        EventKind.MEMORY_RETRIEVED,
        {
            "episodes": [],
            "user_facts": [],
            "open_threads": [],
        },
    )

    yield runner._emit(
        EventKind.WORKSPACE_PATCHED,
        {
            "patch": {
                "retrieved_episodes_count": 0,
                "user_facts_count": 0,
                "open_threads_count": 0,
            }
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# Stage 3-4: Agent Waves (stub - implemented in 05-agents)
# ─────────────────────────────────────────────────────────────────────────────

async def run_agent_waves(
    runner: "TurnRunner",
    workspace: "Workspace",
    scheduler: "Scheduler",
) -> AsyncIterator[EngineEvent]:
    """Run agents in waves, yielding events.

    Stub implementation - will be replaced by 05-agents module.
    """
    # Get scheduled agents
    waves = scheduler.get_agent_waves(
        sensors=workspace.sensors if hasattr(workspace, 'sensors') else {},
        modulators=workspace.modulators,
    )

    for wave_num, agent_ids in enumerate(waves):
        yield runner._emit(
            EventKind.WAVE_STARTED,
            {"wave": wave_num, "agent_count": len(agent_ids)},
        )

        # Stub: emit placeholder agent completions
        for agent_id in agent_ids:
            yield runner._emit(EventKind.AGENT_STARTED, {"agent_id": agent_id})
            yield runner._emit(
                EventKind.AGENT_COMPLETED,
                {
                    "agent_id": agent_id,
                    "observation": "Quiet",
                    "salience": 0.0,
                    "urgency": 0,
                    "confidence": 0,
                    "claims": [],
                    "processing_time_ms": 0,
                },
            )

        yield runner._emit(
            EventKind.WAVE_COMPLETED,
            {"wave": wave_num, "results": len(agent_ids)},
        )


# ─────────────────────────────────────────────────────────────────────────────
# Stage 5: Deliberation (stub - implemented in 06-deliberation)
# ─────────────────────────────────────────────────────────────────────────────

async def run_deliberation(
    runner: "TurnRunner",
    workspace: "Workspace",
) -> AsyncIterator[EngineEvent]:
    """Run claim-based deliberation.

    Stub implementation - will be replaced by 06-deliberation module.
    """
    # Stub: single round with high consensus
    yield runner._emit(
        EventKind.DELIB_ROUND_STARTED,
        {"round": 0},
    )

    workspace.consensus_level = 0.95

    yield runner._emit(
        EventKind.CONSENSUS_UPDATED,
        {"level": 0.95},
    )

    yield runner._emit(
        EventKind.DELIB_ROUND_COMPLETED,
        {"round": 0, "consensus": 0.95},
    )


# ─────────────────────────────────────────────────────────────────────────────
# Stage 6: Council (stub - implemented in 07-council-voice)
# ─────────────────────────────────────────────────────────────────────────────

async def run_council(
    runner: "TurnRunner",
    workspace: "Workspace",
) -> AsyncIterator[EngineEvent]:
    """Run council decision and voice rendering.

    Stub implementation - will be replaced by 07-council-voice module.
    """
    yield runner._emit(
        EventKind.COUNCIL_DECISION_MADE,
        {
            "speak": True,
            "urgency": "medium",
            "intent": "respond",
            "key_points": ["acknowledge user input"],
            "thinking": None,
        },
    )

    workspace.current_goal = "respond"
    workspace.constraints = []

    # Stub response
    workspace.current_response = f"I hear you. You said: {workspace.user_message[:100]}"

    yield runner._emit(
        EventKind.VOICE_RENDERED,
        {"text": workspace.current_response},
    )


async def run_safety_council(
    runner: "TurnRunner",
    workspace: "Workspace",
) -> AsyncIterator[EngineEvent]:
    """Minimal council for safety interrupts."""
    workspace.current_response = (
        "I notice you might be going through something difficult. "
        "I'm here to listen. Would you like to talk about what's on your mind?"
    )

    yield runner._emit(
        EventKind.COUNCIL_DECISION_MADE,
        {
            "speak": True,
            "urgency": "high",
            "intent": "protect",
            "key_points": ["acknowledge", "offer support"],
            "thinking": "Safety interrupt triggered",
        },
    )

    yield runner._emit(
        EventKind.VOICE_RENDERED,
        {"text": workspace.current_response},
    )


# ─────────────────────────────────────────────────────────────────────────────
# Stage 7: Critics (stub - implemented in 07-council-voice)
# ─────────────────────────────────────────────────────────────────────────────

async def run_critics(
    runner: "TurnRunner",
    workspace: "Workspace",
) -> AsyncIterator[EngineEvent]:
    """Run post-generation critics.

    Stub implementation - will be replaced by 07-council-voice module.
    """
    # Stub: all critics pass
    results = [
        {"critic": "length_check", "passed": True, "reason": ""},
        {"critic": "safety_check", "passed": True, "reason": ""},
    ]

    yield runner._emit(
        EventKind.CRITICS_UPDATED,
        {"results": results},
    )


# ─────────────────────────────────────────────────────────────────────────────
# Stage 8: Memory Commit (stub - implemented in 08-memory)
# ─────────────────────────────────────────────────────────────────────────────

async def run_memory_commit(
    runner: "TurnRunner",
    workspace: "Workspace",
) -> AsyncIterator[EngineEvent]:
    """Commit durable memory updates.

    Stub implementation - will be replaced by 08-memory module.
    """
    # Stub: no memory committed
    yield runner._emit(
        EventKind.MEMORY_COMMITTED,
        {"summary": {"episodes_added": 0, "user_facts_added": 0}},
    )
