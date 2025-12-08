# Document 03: Runtime Core (`rilai-runtime`)

**Purpose:** Implement TurnRunner and core stages
**Execution:** One Claude Code session
**Dependencies:** 01-contracts, 02-event-store

---

## Overview

The runtime module implements the turn pipeline - the heart of v3.
TurnRunner orchestrates 9 stages, yielding events as an async iterator.

---

## Files to Create

```
src/rilai/runtime/
├── __init__.py
├── turn_runner.py        # Main orchestrator
├── stages.py             # Stage implementations
└── scheduler.py          # Agent scheduling with budgets
```

---

## File: `src/rilai/runtime/__init__.py`

```python
"""Rilai v3 Runtime - Turn execution pipeline."""

from rilai.runtime.turn_runner import TurnRunner
from rilai.runtime.scheduler import Scheduler

__all__ = ["TurnRunner", "Scheduler"]
```

---

## File: `src/rilai/runtime/turn_runner.py`

```python
"""TurnRunner - orchestrates a single turn, yielding ordered events."""

import time
import uuid
from typing import AsyncIterator, TYPE_CHECKING

from rilai.contracts.events import EngineEvent, EventKind
from rilai.store.event_log import EventLogWriter

if TYPE_CHECKING:
    from rilai.runtime.workspace import Workspace
    from rilai.runtime.scheduler import Scheduler


class TurnRunner:
    """Orchestrates a single turn, yielding ordered events.

    This is the main entry point for processing user messages.
    It yields events as an async iterator, which the TUI consumes.
    """

    def __init__(
        self,
        event_log: EventLogWriter,
        workspace: "Workspace",
        scheduler: "Scheduler",
    ):
        self.event_log = event_log
        self.workspace = workspace
        self.scheduler = scheduler
        self.session_id: str = ""
        self.turn_id: int = 0
        self._start_monotonic: float = 0.0

    def set_session(self, session_id: str) -> None:
        """Set the current session ID."""
        self.session_id = session_id
        self.turn_id = self.event_log.get_last_turn_id(session_id)

    def _emit(self, kind: EventKind, payload: dict) -> EngineEvent:
        """Create, persist, and return an event."""
        event = EngineEvent(
            session_id=self.session_id,
            turn_id=self.turn_id,
            seq=self.event_log.next_seq(self.session_id, self.turn_id),
            ts_monotonic=time.monotonic(),
            kind=kind,
            payload=payload,
        )
        self.event_log.append(event)
        return event

    async def run_turn(self, user_input: str) -> AsyncIterator[EngineEvent]:
        """Execute turn pipeline, yielding events as they occur.

        This is the main method called by the TUI/shell.

        Args:
            user_input: The user's message

        Yields:
            EngineEvent objects in order
        """
        self.turn_id += 1
        self._start_monotonic = time.monotonic()

        # ─────────────────────────────────────────────────────────────────
        # Stage 0: Ingest & Normalize
        # ─────────────────────────────────────────────────────────────────
        yield self._emit(
            EventKind.TURN_STARTED,
            {"user_input": user_input, "turn_id": self.turn_id},
        )
        yield self._emit(EventKind.TURN_STAGE_CHANGED, {"stage": "ingest"})

        self.workspace.set_user_message(user_input)
        self.workspace.turn_id = self.turn_id

        # ─────────────────────────────────────────────────────────────────
        # Stage 1: Fast Sensors
        # ─────────────────────────────────────────────────────────────────
        yield self._emit(EventKind.TURN_STAGE_CHANGED, {"stage": "sensing_fast"})

        sensors = self._run_fast_sensors(user_input)
        yield self._emit(EventKind.SENSORS_FAST_UPDATED, {"sensors": sensors})

        # Safety early-exit check
        if sensors.get("safety_risk", 0) > 0.8:
            yield self._emit(
                EventKind.SAFETY_INTERRUPT,
                {"reason": "high_safety_risk", "sensor": "safety_risk", "value": sensors["safety_risk"]},
            )
            async for event in self._run_safety_council():
                yield event
            yield self._complete_turn()
            return

        # ─────────────────────────────────────────────────────────────────
        # Stage 2: Context Build (Memory Retrieval)
        # ─────────────────────────────────────────────────────────────────
        yield self._emit(EventKind.TURN_STAGE_CHANGED, {"stage": "context"})

        async for event in self._run_memory_retrieval():
            yield event

        # ─────────────────────────────────────────────────────────────────
        # Stage 3-4: Agent Waves
        # ─────────────────────────────────────────────────────────────────
        yield self._emit(EventKind.TURN_STAGE_CHANGED, {"stage": "agents"})

        async for event in self._run_agent_waves():
            yield event

        # ─────────────────────────────────────────────────────────────────
        # Stage 5: Deliberation
        # ─────────────────────────────────────────────────────────────────
        yield self._emit(EventKind.TURN_STAGE_CHANGED, {"stage": "deliberation"})

        async for event in self._run_deliberation():
            yield event

        # ─────────────────────────────────────────────────────────────────
        # Stage 6: Council + Voice
        # ─────────────────────────────────────────────────────────────────
        yield self._emit(EventKind.TURN_STAGE_CHANGED, {"stage": "council"})

        async for event in self._run_council():
            yield event

        # ─────────────────────────────────────────────────────────────────
        # Stage 7: Critics
        # ─────────────────────────────────────────────────────────────────
        yield self._emit(EventKind.TURN_STAGE_CHANGED, {"stage": "critics"})

        async for event in self._run_critics():
            yield event

        # ─────────────────────────────────────────────────────────────────
        # Stage 8: Memory Commit
        # ─────────────────────────────────────────────────────────────────
        yield self._emit(EventKind.TURN_STAGE_CHANGED, {"stage": "memory_commit"})

        async for event in self._run_memory_commit():
            yield event

        # ─────────────────────────────────────────────────────────────────
        # Done
        # ─────────────────────────────────────────────────────────────────
        yield self._complete_turn()

    def _complete_turn(self) -> EngineEvent:
        """Create turn completion event."""
        total_time_ms = int((time.monotonic() - self._start_monotonic) * 1000)
        return self._emit(
            EventKind.TURN_COMPLETED,
            {
                "total_time_ms": total_time_ms,
                "response": self.workspace.current_response,
            },
        )

    # ─────────────────────────────────────────────────────────────────────
    # Stage Implementations (stubs - implemented in other documents)
    # ─────────────────────────────────────────────────────────────────────

    def _run_fast_sensors(self, text: str) -> dict[str, float]:
        """Stage 1: Deterministic sensor extraction.

        No LLM calls - pure keyword/pattern matching.
        """
        from rilai.runtime.stages import run_fast_sensors
        return run_fast_sensors(text)

    async def _run_memory_retrieval(self) -> AsyncIterator[EngineEvent]:
        """Stage 2: Retrieve episodic events, user facts, open threads."""
        from rilai.runtime.stages import run_memory_retrieval
        async for event in run_memory_retrieval(self, self.workspace):
            yield event

    async def _run_agent_waves(self) -> AsyncIterator[EngineEvent]:
        """Stage 3-4: Run scheduled agents in waves."""
        from rilai.runtime.stages import run_agent_waves
        async for event in run_agent_waves(self, self.workspace, self.scheduler):
            yield event

    async def _run_deliberation(self) -> AsyncIterator[EngineEvent]:
        """Stage 5: Claim-based deliberation."""
        from rilai.runtime.stages import run_deliberation
        async for event in run_deliberation(self, self.workspace):
            yield event

    async def _run_council(self) -> AsyncIterator[EngineEvent]:
        """Stage 6: Council decision + voice rendering."""
        from rilai.runtime.stages import run_council
        async for event in run_council(self, self.workspace):
            yield event

    async def _run_safety_council(self) -> AsyncIterator[EngineEvent]:
        """Safety-interrupt council (minimal)."""
        from rilai.runtime.stages import run_safety_council
        async for event in run_safety_council(self, self.workspace):
            yield event

    async def _run_critics(self) -> AsyncIterator[EngineEvent]:
        """Stage 7: Post-generation validation."""
        from rilai.runtime.stages import run_critics
        async for event in run_critics(self, self.workspace):
            yield event

    async def _run_memory_commit(self) -> AsyncIterator[EngineEvent]:
        """Stage 8: Commit durable memory updates."""
        from rilai.runtime.stages import run_memory_commit
        async for event in run_memory_commit(self, self.workspace):
            yield event
```

---

## File: `src/rilai/runtime/stages.py`

```python
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
# Stage 2: Memory Retrieval
# ─────────────────────────────────────────────────────────────────────────────

async def run_memory_retrieval(
    runner: "TurnRunner",
    workspace: "Workspace",
) -> AsyncIterator[EngineEvent]:
    """Retrieve context from memory system."""
    from rilai.memory.retrieval import retrieve_context

    context = await retrieve_context(
        workspace.user_message,
        workspace.conversation_history,
    )

    # Update workspace with retrieved context
    workspace.retrieved_episodes = context.get("episodes", [])
    workspace.user_facts = context.get("user_facts", [])
    workspace.open_threads = context.get("open_threads", [])

    yield runner._emit(
        EventKind.MEMORY_RETRIEVED,
        {
            "episodes": workspace.retrieved_episodes,
            "user_facts": workspace.user_facts,
            "open_threads": [t.dict() if hasattr(t, 'dict') else t for t in workspace.open_threads],
        },
    )

    yield runner._emit(
        EventKind.WORKSPACE_PATCHED,
        {
            "patch": {
                "retrieved_episodes_count": len(workspace.retrieved_episodes),
                "user_facts_count": len(workspace.user_facts),
                "open_threads_count": len(workspace.open_threads),
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
    """Run agents in waves, yielding events."""
    from rilai.agents.executor import execute_agents

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

        # Execute agents in parallel
        results = await execute_agents(
            agent_ids=agent_ids,
            workspace=workspace,
            emit_fn=runner._emit,
        )

        # Merge proposals into workspace
        for result in results:
            workspace.apply_agent_output(result)

        # Emit workspace update
        yield runner._emit(
            EventKind.WORKSPACE_PATCHED,
            {"patch": {"wave": wave_num, "agents_completed": len(results)}},
        )

        # Emit stance update if changed
        stance_delta = workspace.get_stance_delta()
        if stance_delta:
            yield runner._emit(
                EventKind.STANCE_UPDATED,
                {"delta": stance_delta, "current": workspace.stance.to_dict()},
            )

        yield runner._emit(
            EventKind.WAVE_COMPLETED,
            {"wave": wave_num, "results": len(results)},
        )


# ─────────────────────────────────────────────────────────────────────────────
# Stage 5: Deliberation
# ─────────────────────────────────────────────────────────────────────────────

async def run_deliberation(
    runner: "TurnRunner",
    workspace: "Workspace",
) -> AsyncIterator[EngineEvent]:
    """Run claim-based deliberation."""
    from rilai.runtime.deliberation import Deliberator

    deliberator = Deliberator()

    for round_num in range(3):  # Max 3 rounds
        yield runner._emit(
            EventKind.DELIB_ROUND_STARTED,
            {"round": round_num},
        )

        consensus = deliberator.compute_consensus(workspace.active_claims)
        workspace.consensus_level = consensus

        yield runner._emit(
            EventKind.CONSENSUS_UPDATED,
            {"level": consensus},
        )

        # Early exit if consensus high enough
        if consensus >= 0.9:
            break

        # Check if more deliberation needed
        if not deliberator.needs_more_rounds(workspace.active_claims):
            break

        yield runner._emit(
            EventKind.DELIB_ROUND_COMPLETED,
            {"round": round_num, "consensus": consensus},
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
    from rilai.runtime.voice import VoiceRenderer

    council = Council()
    decision = await council.decide(workspace)

    yield runner._emit(
        EventKind.COUNCIL_DECISION_MADE,
        {
            "speak": decision.speak,
            "urgency": decision.urgency,
            "intent": decision.speech_act.intent,
            "key_points": decision.speech_act.key_points,
            "thinking": decision.thinking,
        },
    )

    workspace.current_goal = decision.speech_act.intent
    workspace.constraints = decision.speech_act.do_not

    if decision.speak:
        voice = VoiceRenderer()
        result = await voice.render(decision.speech_act, workspace)

        workspace.current_response = result.text

        yield runner._emit(
            EventKind.VOICE_RENDERED,
            {"text": result.text},
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
    from rilai.runtime.critics import run_all_critics

    results = await run_all_critics(
        response=workspace.current_response,
        workspace=workspace,
    )

    yield runner._emit(
        EventKind.CRITICS_UPDATED,
        {"results": [r.dict() if hasattr(r, 'dict') else r for r in results]},
    )


# ─────────────────────────────────────────────────────────────────────────────
# Stage 8: Memory Commit
# ─────────────────────────────────────────────────────────────────────────────

async def run_memory_commit(
    runner: "TurnRunner",
    workspace: "Workspace",
) -> AsyncIterator[EngineEvent]:
    """Commit durable memory updates."""
    from rilai.memory.consolidation import commit_memory

    summary = await commit_memory(
        workspace=workspace,
        event_log=runner.event_log,
    )

    yield runner._emit(
        EventKind.MEMORY_COMMITTED,
        {"summary": summary},
    )
```

---

## File: `src/rilai/runtime/scheduler.py`

```python
"""Agent scheduler - decides which agents to run."""

from typing import TYPE_CHECKING

from rilai.contracts.agent import AgentPriority
from rilai.contracts.workspace import GlobalModulators

if TYPE_CHECKING:
    from rilai.agents.registry import AgentRegistry


class Scheduler:
    """Schedules agents based on sensors, modulators, and budgets.

    Replaces v2's GenericAgency gating with explicit scheduling.
    """

    def __init__(
        self,
        registry: "AgentRegistry | None" = None,
        max_agents_per_wave: int = 10,
        token_budget: int = 10000,
    ):
        self.registry = registry
        self.max_agents_per_wave = max_agents_per_wave
        self.token_budget = token_budget

        # Cooldown tracking
        self._cooldowns: dict[str, float] = {}

    def get_agent_waves(
        self,
        sensors: dict[str, float],
        modulators: GlobalModulators,
    ) -> list[list[str]]:
        """Get agents to run organized into waves.

        Wave 0: Always-on agents (censor, trigger_watcher, etc.)
        Wave 1+: Scheduled agents based on sensors/modulators

        Returns:
            List of waves, each wave is a list of agent_ids
        """
        if self.registry is None:
            # Return placeholder if no registry
            return [
                ["inhibition.censor", "monitoring.trigger_watcher", "monitoring.anomaly_detector"],
                ["emotion.stress", "emotion.wellbeing"],
            ]

        waves = []

        # Wave 0: Always-on agents
        always_on = [
            agent_id
            for agent_id, manifest in self.registry.manifests.items()
            if manifest.priority == AgentPriority.ALWAYS_ON
        ]
        if always_on:
            waves.append(always_on)

        # Wave 1: Scheduled based on sensors/modulators
        scheduled = self._schedule_agents(sensors, modulators)
        if scheduled:
            waves.append(scheduled)

        return waves

    def _schedule_agents(
        self,
        sensors: dict[str, float],
        modulators: GlobalModulators,
    ) -> list[str]:
        """Schedule agents based on current state."""
        if self.registry is None:
            return []

        candidates: list[tuple[str, float]] = []  # (agent_id, priority_score)

        for agent_id, manifest in self.registry.manifests.items():
            if manifest.priority == AgentPriority.ALWAYS_ON:
                continue  # Already in wave 0

            # Check cooldown
            if self._is_on_cooldown(agent_id):
                continue

            # Calculate priority score
            score = self._calculate_priority(agent_id, manifest, sensors, modulators)
            if score > 0:
                candidates.append((agent_id, score))

        # Sort by score and take top N
        candidates.sort(key=lambda x: x[1], reverse=True)
        return [agent_id for agent_id, _ in candidates[: self.max_agents_per_wave]]

    def _calculate_priority(
        self,
        agent_id: str,
        manifest: "AgentManifest",
        sensors: dict[str, float],
        modulators: GlobalModulators,
    ) -> float:
        """Calculate priority score for an agent."""
        score = 0.0
        agency = manifest.agency_id

        # Sensor-based activation
        if agency == "emotion" and sensors.get("vulnerability", 0) > 0.3:
            score += sensors["vulnerability"]
        if agency == "reasoning" and sensors.get("advice_requested", 0) > 0.3:
            score += sensors["advice_requested"]
        if agency == "social" and sensors.get("relational_bid", 0) > 0.3:
            score += sensors["relational_bid"]

        # Modulator-based activation
        if agency in ("emotion", "monitoring") and modulators.arousal > 0.6:
            score += 0.3
        if agency == "planning" and modulators.time_pressure > 0.5:
            score += 0.3
        if agency in ("social", "inhibition") and modulators.social_risk > 0.5:
            score += 0.3

        # Monitor agents get a base score
        if manifest.priority == AgentPriority.MONITOR:
            score += 0.2

        return score

    def _is_on_cooldown(self, agent_id: str) -> bool:
        """Check if agent is on cooldown."""
        import time
        cooldown_until = self._cooldowns.get(agent_id, 0)
        return time.time() < cooldown_until

    def mark_fired(self, agent_id: str, cooldown_seconds: float = 30.0) -> None:
        """Mark an agent as fired and set cooldown."""
        import time
        self._cooldowns[agent_id] = time.time() + cooldown_seconds
```

---

## v2 Files to DELETE

After implementing and verifying:

```
src/rilai/core/engine.py       # Replaced by TurnRunner
src/rilai/core/events.py       # EventBus replaced by direct streaming
```

---

## Tests

```python
"""Tests for runtime module."""

import pytest
from rilai.runtime.stages import run_fast_sensors


class TestFastSensors:
    def test_vulnerability_detection(self):
        sensors = run_fast_sensors("I'm feeling really sad today")
        assert sensors["vulnerability"] > 0.3

    def test_advice_requested(self):
        sensors = run_fast_sensors("I have a problem, can you help?")
        assert sensors["advice_requested"] > 0.3

    def test_safety_risk(self):
        sensors = run_fast_sensors("I want to hurt myself")
        assert sensors["safety_risk"] > 0.5
```

---

## Next Document

Proceed to `04-workspace.md` after runtime core is implemented.
