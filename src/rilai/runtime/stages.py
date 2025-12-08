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
# Stage 3-4: Agent Waves
# ─────────────────────────────────────────────────────────────────────────────

async def run_agent_waves(
    runner: "TurnRunner",
    workspace: "Workspace",
    scheduler: "Scheduler",
) -> AsyncIterator[EngineEvent]:
    """Run agents in waves using MicroAgentRunner."""
    import logging
    import time
    import uuid

    from rilai.agents.runner import MicroAgentRunner
    from rilai.providers.openrouter import openrouter
    from rilai.core.stance import StanceVector as CoreStanceVector
    from rilai.contracts.agent import Claim, ClaimType

    logger = logging.getLogger(__name__)

    agent_runner = MicroAgentRunner(openrouter)

    # Get scheduled agents from scheduler
    waves = scheduler.get_agent_waves(
        sensors=workspace.sensors if hasattr(workspace, 'sensors') else {},
        modulators=workspace.modulators,
    )

    all_outputs = []

    for wave_num, agent_ids in enumerate(waves):
        yield runner._emit(
            EventKind.WAVE_STARTED,
            {"wave": wave_num, "agent_count": len(agent_ids)},
        )

        # Convert workspace stance to core StanceVector (dataclass)
        ws = workspace.stance
        core_stance = CoreStanceVector(
            valence=ws.valence,
            arousal=ws.arousal,
            control=ws.control,
            certainty=ws.certainty,
            safety=ws.safety,
            closeness=ws.closeness,
            curiosity=ws.curiosity,
            strain=ws.strain,
        )

        # Get sensor dict
        sensors = workspace.sensors if hasattr(workspace, 'sensors') else {}

        # Run agents for this wave
        # Note: If scheduler has no registry, agent_ids are placeholders that won't match
        # In that case, pass agent_ids=None to run all triggered agents from catalog
        start_time = time.time()
        try:
            # Check if these are real agent IDs from catalog
            catalog_ids = set(agent_runner.get_agent_ids())
            valid_ids = [aid for aid in agent_ids if aid in catalog_ids]

            outputs = await agent_runner.run(
                user_text=workspace.user_message,
                sensors=sensors,
                stance=core_stance,
                agent_ids=valid_ids if valid_ids else None,  # None = run all triggered
            )
        except Exception as e:
            # Log error but continue - don't fail the whole turn
            logger.warning(f"Agent wave {wave_num} failed: {e}")
            outputs = []

        wave_time_ms = int((time.time() - start_time) * 1000)

        # Emit individual agent completion events
        for output in outputs:
            yield runner._emit(EventKind.AGENT_STARTED, {"agent_id": output.agent})
            yield runner._emit(
                EventKind.AGENT_COMPLETED,
                {
                    "agent_id": output.agent,
                    "observation": output.glimpse or "",
                    "salience": output.salience,
                    "urgency": min(3, int(output.salience * 4)),
                    "confidence": min(3, int(output.salience * 4)),
                    "claims": [],
                    "processing_time_ms": wave_time_ms // max(1, len(outputs)),
                },
            )

        all_outputs.extend(outputs)

        # Apply stance deltas to workspace
        if outputs:
            merged_deltas = agent_runner.merge_deltas(outputs)
            if merged_deltas:
                for dim, delta in merged_deltas.items():
                    if hasattr(workspace.stance, dim):
                        current = getattr(workspace.stance, dim)
                        setattr(workspace.stance, dim, max(-1, min(1, current + delta)))

        yield runner._emit(
            EventKind.WAVE_COMPLETED,
            {"wave": wave_num, "results": len(outputs)},
        )

    # Store agent outputs for council to use
    workspace._agent_outputs = all_outputs

    # Convert to claims for council
    claims = []
    for output in all_outputs:
        if output.salience > 0.1 and output.glimpse:
            claims.append(Claim(
                id=str(uuid.uuid4()),
                text=output.glimpse[:200],  # Claim text max 200 chars
                type=ClaimType.OBSERVATION,
                source_agent=output.agent,
                urgency=min(3, int(output.salience * 4)),
                confidence=min(3, int(output.salience * 4)),
            ))
    workspace._active_claims = claims


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
# Stage 6: Council
# ─────────────────────────────────────────────────────────────────────────────

async def run_council(
    runner: "TurnRunner",
    workspace: "Workspace",
) -> AsyncIterator[EngineEvent]:
    """Run council decision and voice rendering."""
    from rilai.runtime.council import Council
    from rilai.runtime.voice import Voice

    # Populate active_claims from agent outputs
    if hasattr(workspace, '_active_claims'):
        workspace.active_claims = workspace._active_claims
    else:
        workspace.active_claims = []

    council = Council(emit_fn=runner._emit)
    voice = Voice(emit_fn=runner._emit)

    # Make decision
    decision = await council.decide(workspace)

    # Set workspace state from decision
    if decision.speech_act:
        workspace.current_goal = decision.speech_act.intent
        workspace.constraints = decision.speech_act.do_not or []

    if decision.speak:
        # Render response via Voice (makes LLM call)
        result = await voice.render(decision, workspace)
        workspace.current_response = result.text
        # Voice.render already emits VOICE_RENDERED event
    else:
        workspace.current_response = ""
        yield runner._emit(
            EventKind.VOICE_RENDERED,
            {"text": ""},
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
# Stage 7: Critics
# ─────────────────────────────────────────────────────────────────────────────

async def run_critics(
    runner: "TurnRunner",
    workspace: "Workspace",
) -> AsyncIterator[EngineEvent]:
    """Run post-generation critics."""
    from rilai.runtime.critics import Critics
    from rilai.contracts.council import CouncilDecision, SpeechAct

    if not workspace.current_response:
        yield runner._emit(
            EventKind.CRITICS_UPDATED,
            {"results": [], "passed": True},
        )
        return

    critics = Critics(emit_fn=runner._emit)

    # Reconstruct minimal decision for critics
    decision = CouncilDecision(
        speak=True,
        urgency="medium",
        speech_act=SpeechAct(
            intent=workspace.current_goal or "witness",
            key_points=[],
            tone="friendly",
        ),
        needs_clarification=None,
        thinking="",
    )

    # Critics.validate() emits the CRITICS_UPDATED event
    passed, results = await critics.validate(
        workspace.current_response,
        workspace,
        decision,
    )
    # Event already emitted by critics.validate(), yield nothing extra
    return
    yield  # Make this an async generator


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
