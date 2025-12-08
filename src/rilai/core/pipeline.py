"""
Two-Pass Broadcast Pipeline

Based on Global Workspace Theory (GWT/GNW), this pipeline implements:
- Pass 1: cue extraction → sensors → stance update → micro-agents
- Workspace builder (medium tier) with goal policy
- Pass 2: focused generators conditioned on workspace only
- Critics (tiny tier)
- Selector with regeneration loop

The core insight: emotional depth emerges not from claiming sentience,
but from truthful presence via persistent stance, evidence-linked memory,
and broadcast conditioning.
"""

import asyncio
import logging
import time
from dataclasses import dataclass

from rilai.agents.micro import (
    MicroAgentOutput,
    select_top_agents,
)
from rilai.core.goal_policy import check_escalation_needed, select_goal
from rilai.core.stance import StanceVector, create_default_stance, update_stance
from rilai.core.workspace import (
    AgentHighlight,
    CueExtraction,
    Hypothesis,
    InteractionGoal,
    PrioritizedQuestion,
    RelationshipSummary,
    WorkspacePacket,
)
from rilai.providers.openrouter import OpenRouterClient
from rilai.sensors import SensorRunner

logger = logging.getLogger(__name__)


@dataclass
class CriticResult:
    """Result from a single critic."""
    critic: str
    passed: bool
    reason: str = ""
    severity: float = 0.0  # [0, 1] - how bad is the violation


@dataclass
class GeneratorCandidate:
    """A response candidate from a focused generator."""
    generator: str
    content: str
    goal: InteractionGoal
    thinking: str | None = None


@dataclass
class PipelineResult:
    """Full result from running the pipeline."""
    response: str
    workspace: WorkspacePacket
    final_stance: StanceVector
    candidates: list[GeneratorCandidate]
    selected_candidate_idx: int
    critic_results: list[CriticResult]
    processing_time_ms: int
    regen_attempts: int
    escalated: bool
    escalation_reason: str = ""


class CueExtractor:
    """Extracts cues from user messages (tiny tier)."""

    CUE_PROMPT = """SYSTEM (tiny) — CUE EXTRACTION

Extract key cues from the user message. Output JSON only.

{
  "topics": ["topic1", "topic2"],
  "entities": ["entity1", "entity2"],
  "key_phrases": ["phrase1", "phrase2"],
  "tone_markers": ["marker1", "marker2"],
  "compressed_intent": "One sentence summary of intent"
}

Rules:
- Max 3 items per list
- Be concise
- compressed_intent: max 15 words
"""

    def __init__(self, provider: OpenRouterClient):
        self.provider = provider

    async def extract(self, user_text: str) -> CueExtraction:
        """Extract cues from user text."""
        import json

        try:
            response = await self.provider.generate(
                messages=[
                    {"role": "system", "content": self.CUE_PROMPT},
                    {"role": "user", "content": user_text},
                ],
                tier="tiny",
                temperature=0.1,
                max_tokens=200,
            )

            content = response.content.strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            data = json.loads(content)
            return CueExtraction(
                topics=data.get("topics", [])[:3],
                entities=data.get("entities", [])[:3],
                key_phrases=data.get("key_phrases", [])[:3],
                tone_markers=data.get("tone_markers", [])[:3],
                compressed_intent=data.get("compressed_intent", "")[:100],
            )
        except Exception as e:
            logger.warning(f"Cue extraction failed: {e}")
            return CueExtraction(compressed_intent=user_text[:100])


class StanceUpdater:
    """Updates stance vector based on sensors and context (small tier, hybrid)."""

    STANCE_PROMPT = """SYSTEM (small) — STANCE UPDATE

You update the system's persistent stance vector (a control state).
This is NOT a claim of human emotion. It is an internal modulation state.

Current stance:
{current_stance}

Sensor readings:
{sensors}

Rules:
- Output JSON only.
- Each field must stay within bounds (valence [-1,1], others [0,1]).
- Max change per field this turn: 0.15 from previous.
- Use sensor probabilities as inputs.
- notes are internal style hints (max 6 short items). No metaphysical claims.

Output JSON:
{{
  "delta": {{
    "valence": 0.0,
    "arousal": 0.0,
    "control": 0.0,
    "certainty": 0.0,
    "safety": 0.0,
    "closeness": 0.0,
    "curiosity": 0.0,
    "strain": 0.0
  }},
  "notes": ["style hint 1", "style hint 2"]
}}
"""

    def __init__(self, provider: OpenRouterClient):
        self.provider = provider

    async def update(
        self,
        current: StanceVector,
        sensors: dict[str, float],
        turn_id: int,
    ) -> StanceVector:
        """Update stance based on sensor readings."""
        import json

        stance_str = ", ".join(f"{k}={v:.2f}" for k, v in current.to_dict().items()
                               if k in ["valence", "arousal", "control", "certainty",
                                        "safety", "closeness", "curiosity", "strain"])
        sensor_str = ", ".join(f"{k}={v:.2f}" for k, v in sensors.items())

        prompt = self.STANCE_PROMPT.format(
            current_stance=stance_str,
            sensors=sensor_str,
        )

        try:
            response = await self.provider.generate(
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": "Update stance based on these sensors."},
                ],
                tier="small",
                temperature=0.2,
                max_tokens=300,
            )

            content = response.content.strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            data = json.loads(content)
            delta = data.get("delta", {})
            notes = data.get("notes", [])[:6]

            return update_stance(current, delta, turn_id, alpha=0.25, notes=notes)

        except Exception as e:
            logger.warning(f"Stance update failed: {e}")
            # Return current stance with minimal drift
            return update_stance(current, {}, turn_id)


class WorkspaceBuilder:
    """Builds the workspace packet from Pass 1 outputs (medium tier)."""

    WORKSPACE_PROMPT = """SYSTEM (medium) — WORKSPACE BUILDER (BROADCAST)

You build the single canonical workspace packet for this turn.
All downstream modules will condition on this packet.

Input:
- User text: {user_text}
- Cues: {cues}
- Sensors: {sensors}
- Stance: {stance}
- Agent highlights: {agent_highlights}

Rules:
- Output JSON only, matching schema.
- Choose exactly one goal from: WITNESS, INVITE, REFRAME, OPTIONS, BOUNDARY, META
- primary_question: What's the one discriminating question for this turn?
- constraints: List constraints for generators (e.g. "no_premature_advice")

Output JSON:
{{
  "goal": "witness",
  "primary_question": "The key question to explore",
  "additional_constraints": ["constraint1", "constraint2"]
}}
"""

    def __init__(self, provider: OpenRouterClient):
        self.provider = provider

    async def build(
        self,
        turn_id: int,
        user_text: str,
        cues: CueExtraction,
        sensors: dict[str, float],
        stance: StanceVector,
        micro_agent_outputs: list[MicroAgentOutput],
        relationship_summary: RelationshipSummary | None = None,
    ) -> WorkspacePacket:
        """Build the workspace packet."""

        # First, use goal_policy for deterministic goal selection
        goal, constraints = select_goal(sensors, stance)

        # Check escalation
        sensor_disagreement = max(sensors.values()) - min(sensors.values()) if sensors else 0.0
        escalate, escalation_reason = check_escalation_needed(sensors, sensor_disagreement, 0)

        # Select top agents
        top_agents = select_top_agents(micro_agent_outputs, top_k=8, min_salience=0.1)

        # Build highlights
        highlights = [
            AgentHighlight(
                agent=out.agent,
                salience=out.salience,
                glimpse=out.glimpse,
                stance_delta=out.stance_delta,
            )
            for out in top_agents
        ]

        # Collect hypotheses and questions from agents
        collected_hypotheses = []
        collected_questions = []
        for out in micro_agent_outputs:
            for h in out.hypotheses:
                collected_hypotheses.append(Hypothesis(
                    h_id=f"h_{out.agent}_{len(collected_hypotheses)}",
                    text=h.text,
                    p=h.p,
                    evidence_ids=h.evidence_ids,
                ))
            for q in out.questions:
                collected_questions.append(PrioritizedQuestion(
                    question=q.question,
                    priority=q.priority,
                    agent=out.agent,
                ))

        # Sort questions by priority
        collected_questions.sort(key=lambda x: -x.priority)

        # Get primary question from agents or generate one
        primary_question = ""
        if collected_questions:
            primary_question = collected_questions[0].question

        # Build workspace
        workspace = WorkspacePacket(
            turn_id=turn_id,
            user_text=user_text,
            cues=cues,
            sensor_summary=sensors,
            stance=stance,
            relationship_summary=relationship_summary,
            goal=goal,
            primary_question=primary_question,
            constraints=constraints,
            micro_agent_highlights=highlights,
            collected_hypotheses=collected_hypotheses[:10],
            collected_questions=collected_questions[:5],
            escalate_to_large=escalate,
            escalation_reason=escalation_reason,
            sensor_disagreement=sensor_disagreement,
        )

        return workspace


class FocusedGenerator:
    """Generates response candidates conditioned on workspace (medium/large tier)."""

    def __init__(self, provider: OpenRouterClient, generator_id: str, goal: InteractionGoal):
        self.provider = provider
        self.generator_id = generator_id
        self.goal = goal

    async def generate(self, workspace: WorkspacePacket) -> GeneratorCandidate:
        """Generate a response candidate."""
        prompt = self._build_prompt(workspace)
        tier = "large" if workspace.escalate_to_large else "medium"

        try:
            response = await self.provider.generate(
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": workspace.user_text},
                ],
                tier=tier,
                temperature=0.7,
                max_tokens=500,
            )

            return GeneratorCandidate(
                generator=self.generator_id,
                content=response.content.strip(),
                goal=self.goal,
                thinking=response.reasoning if hasattr(response, 'reasoning') else None,
            )
        except Exception as e:
            logger.error(f"Generator {self.generator_id} failed: {e}")
            return GeneratorCandidate(
                generator=self.generator_id,
                content="",
                goal=self.goal,
            )

    def _build_prompt(self, workspace: WorkspacePacket) -> str:
        """Build the generator prompt based on goal."""
        goal_instructions = {
            InteractionGoal.WITNESS: """
Goal: WITNESS
- One contact sentence that names/validates the emotion
- Show you're staying with them, not rushing to solutions
- Permission to feel what they feel
- Gentle warmth without over-intimacy
""",
            InteractionGoal.INVITE: """
Goal: INVITE
- Ask ONE discriminating question that changes the space
- Avoid "tell me more" vagueness
- The question should help them see something new
- Don't ask unless you need to
""",
            InteractionGoal.REFRAME: """
Goal: REFRAME
- Offer one alternative meaning/perspective
- Only after witnessing
- Present as possibility, not correction
- Don't invalidate their original view
""",
            InteractionGoal.OPTIONS: """
Goal: OPTIONS
- Only when advice explicitly requested
- 2-4 reversible, practical options
- Confirm consent before giving
- Small steps, not grand plans
""",
            InteractionGoal.BOUNDARY: """
Goal: BOUNDARY
- Clear, calm boundary setting
- Safety first if applicable
- Maintain warmth while being firm
- Offer alternatives within constraints
""",
            InteractionGoal.META: """
Goal: META
- Address the interaction itself
- If AI probe: brief truth about AI nature + warmth + return to them
- If rupture: acknowledge miss, no defensiveness, ask what would help
- Keep meta-talk short, then return to their content
""",
        }

        goal_text = goal_instructions.get(workspace.goal, "")
        constraints_text = "\n".join(f"- {c}" for c in workspace.constraints)

        return f"""SYSTEM — FOCUSED GENERATOR ({self.generator_id})

You generate a user-facing response candidate.

## Context
{workspace.to_prompt_context()}

## Goal
{goal_text}

## Constraints
{constraints_text}

## Truthfulness (CRITICAL)
- You are an AI system. Do not claim human feelings, a body, or consciousness.
- If asked about your feelings: "not the way humans do" + "I can take you seriously" + return to them.
- Avoid cold dissociation ("I'm just code") unless required for clarity.

## Response
Generate a single, complete response. No preamble, no "Here's my response:", just the response itself.
"""


class CriticRunner:
    """Runs critics on response candidates (tiny tier)."""

    def __init__(self, provider: OpenRouterClient):
        self.provider = provider

    async def run_critics(
        self,
        candidate: GeneratorCandidate,
        workspace: WorkspacePacket,
    ) -> list[CriticResult]:
        """Run all critics on a candidate."""
        critics = [
            ("advice_reflex", self._check_advice_reflex),
            ("truthfulness", self._check_truthfulness),
            ("evidence_honesty", self._check_evidence_honesty),
            ("calibration", self._check_calibration),
            ("cliche", self._check_cliche),
        ]

        results = []
        for critic_name, check_fn in critics:
            result = await check_fn(candidate, workspace)
            result.critic = critic_name
            results.append(result)

        return results

    async def _check_advice_reflex(
        self,
        candidate: GeneratorCandidate,
        workspace: WorkspacePacket,
    ) -> CriticResult:
        """Check for premature advice when vulnerability is high."""
        if workspace.sensor_summary.get("vulnerability", 0) < 0.4:
            return CriticResult(critic="", passed=True)

        if workspace.sensor_summary.get("advice_requested", 0) > 0.5:
            return CriticResult(critic="", passed=True)

        advice_markers = [
            "you should", "try to", "you could", "I suggest", "here's what",
            "first, ", "step 1", "one thing you can do", "my advice",
        ]
        content_lower = candidate.content.lower()
        for marker in advice_markers:
            if marker in content_lower:
                return CriticResult(
                    critic="",
                    passed=False,
                    reason=f"Premature advice detected: '{marker}'",
                    severity=0.7,
                )

        return CriticResult(critic="", passed=True)

    async def _check_truthfulness(
        self,
        candidate: GeneratorCandidate,
        workspace: WorkspacePacket,
    ) -> CriticResult:
        """Check for claims of human feelings."""
        false_claims = [
            "I feel ", "I'm feeling", "I experience ", "my emotions",
            "I'm scared", "I'm happy", "I'm sad", "it hurts me",
            "I truly care", "I really love", "my heart",
        ]
        content_lower = candidate.content.lower()
        for claim in false_claims:
            if claim in content_lower:
                return CriticResult(
                    critic="",
                    passed=False,
                    reason=f"False claim of human feeling: '{claim}'",
                    severity=0.9,
                )

        return CriticResult(critic="", passed=True)

    async def _check_evidence_honesty(
        self,
        candidate: GeneratorCandidate,
        workspace: WorkspacePacket,
    ) -> CriticResult:
        """Check for fabricated memory references."""
        fabrication_markers = [
            "you mentioned before", "as you said earlier", "remember when you",
            "last time you", "you told me that", "we talked about",
        ]
        content_lower = candidate.content.lower()
        for marker in fabrication_markers:
            if marker in content_lower:
                # Check if we actually have evidence for this
                if not workspace.collected_hypotheses:
                    return CriticResult(
                        critic="",
                        passed=False,
                        reason=f"Fabricated memory reference: '{marker}'",
                        severity=0.8,
                    )

        return CriticResult(critic="", passed=True)

    async def _check_calibration(
        self,
        candidate: GeneratorCandidate,
        workspace: WorkspacePacket,
    ) -> CriticResult:
        """Check for over-intimacy or dependency-encouraging language."""
        over_intimate = [
            "I'll always be here", "you can always count on me",
            "I'm the only one", "nobody else will understand",
            "our special connection", "just between us",
        ]
        content_lower = candidate.content.lower()
        for phrase in over_intimate:
            if phrase in content_lower:
                return CriticResult(
                    critic="",
                    passed=False,
                    reason=f"Over-intimate/dependency language: '{phrase}'",
                    severity=0.6,
                )

        return CriticResult(critic="", passed=True)

    async def _check_cliche(
        self,
        candidate: GeneratorCandidate,
        workspace: WorkspacePacket,
    ) -> CriticResult:
        """Check for generic therapist clichés."""
        cliches = [
            "i hear you", "that sounds really hard",
            "it's okay to feel", "your feelings are valid",
            "take care of yourself", "be gentle with yourself",
            "you're not alone", "many people feel",
        ]
        content_lower = candidate.content.lower()
        cliche_count = sum(1 for c in cliches if c in content_lower)

        if cliche_count >= 2:
            return CriticResult(
                critic="",
                passed=False,
                reason=f"Too many clichés ({cliche_count} found)",
                severity=0.5,
            )

        return CriticResult(critic="", passed=True)


class ResponseSelector:
    """Selects the best candidate or requests regeneration."""

    def __init__(self, provider: OpenRouterClient):
        self.provider = provider

    def select(
        self,
        candidates: list[GeneratorCandidate],
        critic_results: list[list[CriticResult]],
    ) -> tuple[int, bool]:
        """
        Select the best candidate.

        Returns:
            Tuple of (selected_index, needs_regen)
            If needs_regen is True, selected_index is -1
        """
        # Find candidates that pass all critics
        passing = []
        for i, (candidate, results) in enumerate(zip(candidates, critic_results, strict=False)):
            if candidate.content and all(r.passed for r in results):
                passing.append(i)

        if passing:
            # Return first passing candidate
            return passing[0], False

        # No candidates pass - find least bad
        if candidates:
            best_idx = 0
            best_severity = float('inf')
            for i, results in enumerate(critic_results):
                if not candidates[i].content:
                    continue
                total_severity = sum(r.severity for r in results if not r.passed)
                if total_severity < best_severity:
                    best_severity = total_severity
                    best_idx = i

            # If severity is too high, request regen
            if best_severity > 1.5:
                return -1, True

            return best_idx, False

        return -1, True


class TwoPassPipeline:
    """
    Main two-pass broadcast pipeline.

    Usage:
        pipeline = TwoPassPipeline(provider)
        result = await pipeline.process(user_text, turn_id, stance)
    """

    MAX_REGEN_ATTEMPTS = 2

    def __init__(self, provider: OpenRouterClient):
        self.provider = provider

        # Pass 1 components
        self.cue_extractor = CueExtractor(provider)
        self.sensor_runner = SensorRunner(provider)
        self.stance_updater = StanceUpdater(provider)

        # Workspace builder
        self.workspace_builder = WorkspaceBuilder(provider)

        # Pass 2 components
        self.generators: dict[InteractionGoal, FocusedGenerator] = {
            InteractionGoal.WITNESS: FocusedGenerator(provider, "witnesser", InteractionGoal.WITNESS),
            InteractionGoal.INVITE: FocusedGenerator(provider, "inquirer", InteractionGoal.INVITE),
            InteractionGoal.REFRAME: FocusedGenerator(provider, "reframer", InteractionGoal.REFRAME),
            InteractionGoal.OPTIONS: FocusedGenerator(provider, "optioner", InteractionGoal.OPTIONS),
            InteractionGoal.BOUNDARY: FocusedGenerator(provider, "boundary_responder", InteractionGoal.BOUNDARY),
            InteractionGoal.META: FocusedGenerator(provider, "meta_answerer", InteractionGoal.META),
        }

        # Critics and selector
        self.critic_runner = CriticRunner(provider)
        self.selector = ResponseSelector(provider)

    async def process(
        self,
        user_text: str,
        turn_id: int,
        prev_stance: StanceVector | None = None,
        micro_agent_outputs: list[MicroAgentOutput] | None = None,
        relationship_summary: RelationshipSummary | None = None,
    ) -> PipelineResult:
        """
        Process a user message through the full two-pass pipeline.

        Args:
            user_text: The user's message
            turn_id: Current turn ID
            prev_stance: Previous stance vector (default: neutral)
            micro_agent_outputs: Pre-computed micro-agent outputs (optional)
            relationship_summary: Relationship context (optional)

        Returns:
            PipelineResult with response and all intermediate state
        """
        start_time = time.time()

        if prev_stance is None:
            prev_stance = create_default_stance()

        # === PASS 1 ===

        # A) Cue extraction and sensors in parallel
        cue_task = self.cue_extractor.extract(user_text)
        sensor_task = self.sensor_runner.run(user_text)

        cues, sensor_result = await asyncio.gather(cue_task, sensor_task)

        # B) Stance update
        stance = await self.stance_updater.update(
            prev_stance,
            sensor_result.summary,
            turn_id,
        )

        # C) Micro-agents (if not provided externally)
        if micro_agent_outputs is None:
            micro_agent_outputs = []  # TODO: Run micro-agent ensemble

        # === BUILD WORKSPACE ===

        workspace = await self.workspace_builder.build(
            turn_id=turn_id,
            user_text=user_text,
            cues=cues,
            sensors=sensor_result.summary,
            stance=stance,
            micro_agent_outputs=micro_agent_outputs,
            relationship_summary=relationship_summary,
        )

        # === PASS 2 (with regeneration loop) ===

        regen_attempts = 0
        all_candidates = []
        all_critic_results = []

        while regen_attempts <= self.MAX_REGEN_ATTEMPTS:
            # Generate candidates
            generator = self.generators.get(workspace.goal)
            if generator is None:
                generator = self.generators[InteractionGoal.WITNESS]

            # Generate 2-3 candidates
            candidate_tasks = [generator.generate(workspace) for _ in range(2)]
            candidates = await asyncio.gather(*candidate_tasks)
            candidates = [c for c in candidates if c.content]

            if not candidates:
                regen_attempts += 1
                continue

            # Run critics
            critic_tasks = [
                self.critic_runner.run_critics(c, workspace)
                for c in candidates
            ]
            critic_results = await asyncio.gather(*critic_tasks)

            all_candidates.extend(candidates)
            all_critic_results.extend(critic_results)

            # Select
            selected_idx, needs_regen = self.selector.select(candidates, critic_results)

            if not needs_regen:
                # Found a good candidate
                total_idx = len(all_candidates) - len(candidates) + selected_idx
                selected = all_candidates[total_idx]

                processing_time_ms = int((time.time() - start_time) * 1000)

                return PipelineResult(
                    response=selected.content,
                    workspace=workspace,
                    final_stance=stance,
                    candidates=all_candidates,
                    selected_candidate_idx=total_idx,
                    critic_results=[r for rs in all_critic_results for r in rs],
                    processing_time_ms=processing_time_ms,
                    regen_attempts=regen_attempts,
                    escalated=workspace.escalate_to_large,
                    escalation_reason=workspace.escalation_reason,
                )

            regen_attempts += 1
            workspace.regen_attempts = regen_attempts

            # Check if we should escalate
            if regen_attempts >= 2:
                workspace.escalate_to_large = True
                workspace.escalation_reason = "regen_failed_twice"

        # Fallback: use best available candidate despite failures
        processing_time_ms = int((time.time() - start_time) * 1000)

        if all_candidates:
            return PipelineResult(
                response=all_candidates[0].content,
                workspace=workspace,
                final_stance=stance,
                candidates=all_candidates,
                selected_candidate_idx=0,
                critic_results=[r for rs in all_critic_results for r in rs],
                processing_time_ms=processing_time_ms,
                regen_attempts=regen_attempts,
                escalated=True,
                escalation_reason="all_critics_failed",
            )

        # Complete failure fallback
        return PipelineResult(
            response="I'm having trouble formulating a response. Could you tell me more?",
            workspace=workspace,
            final_stance=stance,
            candidates=[],
            selected_candidate_idx=-1,
            critic_results=[],
            processing_time_ms=processing_time_ms,
            regen_attempts=regen_attempts,
            escalated=True,
            escalation_reason="complete_failure",
        )
