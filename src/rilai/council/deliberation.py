"""Multi-round deliberation engine for council.

Allows agents to hear each other's views and adjust their positions
over multiple rounds before council synthesis.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime

from rilai.agencies.base import GenericAgency
from rilai.agencies.messages import AgentAssessment, RilaiEvent, SalienceMetadata
from rilai.agents.protocol import WorkingMemoryView
from rilai.config import get_config
from rilai.core.events import Event, EventType, event_bus

from .messages import AgentVoice, DeliberationContext, DeliberationRound


@dataclass
class DeliberationResult:
    """Result of multi-round deliberation."""

    rounds: list[DeliberationRound]
    final_voices: dict[str, AgentVoice]
    consensus_level: float
    speaking_pressure: float
    should_speak_early: bool
    early_exit_reason: str | None


class DeliberationEngine:
    """Orchestrates multi-round deliberation among agents.

    In each round:
    1. Agents receive the previous round's voices
    2. Agents can maintain, adjust, defer, or dissent
    3. Consensus is evaluated
    4. Council can decide to speak early if consensus + urgency warrants it
    """

    def __init__(
        self,
        agencies: dict[str, GenericAgency],
        max_rounds: int | None = None,
        consensus_threshold: float | None = None,
    ):
        config = get_config()
        self.agencies = agencies
        self.max_rounds = max_rounds or config.DELIBERATION_MAX_ROUNDS
        self.consensus_threshold = (
            consensus_threshold or config.DELIBERATION_CONSENSUS_THRESHOLD
        )

    async def deliberate(
        self,
        event: RilaiEvent,
        base_context: WorkingMemoryView,
        initial_assessments: list[AgentAssessment],
    ) -> DeliberationResult:
        """Run multi-round deliberation.

        Args:
            event: The input event
            base_context: Base working memory context
            initial_assessments: Round 0 assessments from agencies

        Returns:
            DeliberationResult with all rounds and final state
        """
        rounds: list[DeliberationRound] = []

        # Convert initial assessments to voices
        current_voices = self._assessments_to_voices(initial_assessments)

        # Create round 0
        round_0 = DeliberationRound(
            round_number=0,
            voices=current_voices,
            consensus_level=self._compute_consensus(current_voices),
            speaking_pressure=self._compute_speaking_pressure(current_voices),
        )
        rounds.append(round_0)

        await event_bus.emit(
            Event(
                EventType.DELIBERATION_ROUND_COMPLETED,
                {
                    "round": 0,
                    "consensus": round_0.consensus_level,
                    "pressure": round_0.speaking_pressure,
                },
            )
        )

        # Check for critical urgency - speak immediately
        if self._has_critical_urgency(current_voices):
            return DeliberationResult(
                rounds=rounds,
                final_voices=current_voices,
                consensus_level=round_0.consensus_level,
                speaking_pressure=round_0.speaking_pressure,
                should_speak_early=True,
                early_exit_reason="critical_urgency",
            )

        # Run deliberation rounds
        for round_num in range(1, self.max_rounds + 1):
            await event_bus.emit(
                Event(EventType.DELIBERATION_ROUND_STARTED, {"round": round_num})
            )

            # Create deliberation context
            delib_context = DeliberationContext(
                round=round_num,
                previous_voices=current_voices,
                consensus_level=rounds[-1].consensus_level,
                speaking_pressure=rounds[-1].speaking_pressure,
                max_rounds=self.max_rounds,
            )

            # Run agents with deliberation context
            new_voices = await self._run_deliberation_round(
                event, base_context, delib_context
            )

            # Create round record
            round_record = DeliberationRound(
                round_number=round_num,
                voices=new_voices,
                consensus_level=self._compute_consensus(new_voices),
                speaking_pressure=self._compute_speaking_pressure(new_voices),
            )
            rounds.append(round_record)
            current_voices = new_voices

            await event_bus.emit(
                Event(
                    EventType.DELIBERATION_ROUND_COMPLETED,
                    {
                        "round": round_num,
                        "consensus": round_record.consensus_level,
                        "pressure": round_record.speaking_pressure,
                    },
                )
            )

            # Check for early exit conditions
            if round_record.consensus_level >= self.consensus_threshold:
                # Check if we have enough urgency to speak
                if round_record.speaking_pressure >= 0.5:
                    await event_bus.emit(
                        Event(
                            EventType.CONSENSUS_REACHED,
                            {"round": round_num, "consensus": round_record.consensus_level},
                        )
                    )
                    return DeliberationResult(
                        rounds=rounds,
                        final_voices=current_voices,
                        consensus_level=round_record.consensus_level,
                        speaking_pressure=round_record.speaking_pressure,
                        should_speak_early=True,
                        early_exit_reason="consensus_reached",
                    )

            # Check if all agents deferred
            if self._all_deferred(new_voices):
                return DeliberationResult(
                    rounds=rounds,
                    final_voices=current_voices,
                    consensus_level=round_record.consensus_level,
                    speaking_pressure=round_record.speaking_pressure,
                    should_speak_early=False,
                    early_exit_reason="all_deferred",
                )

        # Reached max rounds
        final_round = rounds[-1]
        return DeliberationResult(
            rounds=rounds,
            final_voices=current_voices,
            consensus_level=final_round.consensus_level,
            speaking_pressure=final_round.speaking_pressure,
            should_speak_early=False,
            early_exit_reason=None,
        )

    async def _run_deliberation_round(
        self,
        event: RilaiEvent,
        base_context: WorkingMemoryView,
        delib_context: DeliberationContext,
    ) -> dict[str, AgentVoice]:
        """Run all agents for a deliberation round."""
        # Create context with deliberation info
        context = WorkingMemoryView(
            conversation_history=base_context.conversation_history,
            active_goals=base_context.active_goals,
            recent_assessments=base_context.recent_assessments,
            user_baseline=base_context.user_baseline,
            current_time=base_context.current_time,
            self_model=base_context.self_model,
            deliberation=delib_context,
        )

        # Run all agencies in parallel
        tasks = []
        for agency in self.agencies.values():
            tasks.append(agency.assess(event, context))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Convert assessments to voices
        new_voices: dict[str, AgentVoice] = {}
        for result in results:
            if isinstance(result, Exception):
                continue
            for assessment in result.sub_assessments:
                voice = self._assessment_to_voice(assessment, delib_context)
                new_voices[assessment.agent_id] = voice

        return new_voices

    def _assessments_to_voices(
        self, assessments: list[AgentAssessment]
    ) -> dict[str, AgentVoice]:
        """Convert initial assessments to voices."""
        voices = {}
        for assessment in assessments:
            voice = AgentVoice(
                agent_id=assessment.agent_id,
                content=assessment.voice,
                stance="maintain",
                salience=assessment.salience
                or SalienceMetadata(urgency=0, confidence=0),
                reasoning=None,
                addressed_agents=[],
            )
            voices[assessment.agent_id] = voice
        return voices

    def _assessment_to_voice(
        self,
        assessment: AgentAssessment,
        delib_context: DeliberationContext,
    ) -> AgentVoice:
        """Convert an assessment to a voice with stance detection."""
        content = assessment.voice
        stance = "maintain"
        addressed = []

        # Detect stance from content
        content_lower = content.lower()
        if "i agree with" in content_lower or "building on" in content_lower:
            stance = "adjust"
            # Try to find which agent
            for agent_id in delib_context.previous_voices.keys():
                agent_name = agent_id.split(".")[-1]
                if agent_name in content_lower:
                    addressed.append(agent_id)

        elif "i defer to" in content_lower or "yield to" in content_lower:
            stance = "defer"

        elif "i disagree" in content_lower or "contrary to" in content_lower:
            stance = "dissent"

        return AgentVoice(
            agent_id=assessment.agent_id,
            content=content,
            stance=stance,
            salience=assessment.salience or SalienceMetadata(urgency=0, confidence=0),
            reasoning=assessment.trace.thinking if assessment.trace else None,
            addressed_agents=addressed,
        )

    def _compute_consensus(self, voices: dict[str, AgentVoice]) -> float:
        """Compute consensus level among agents.

        Returns: 0.0 to 1.0, where 1.0 is perfect consensus
        """
        if not voices:
            return 0.0

        # Count stances
        stance_counts = {"maintain": 0, "adjust": 0, "defer": 0, "dissent": 0}
        for voice in voices.values():
            stance_counts[voice.stance] = stance_counts.get(voice.stance, 0) + 1

        total = len(voices)
        dissent_count = stance_counts.get("dissent", 0)
        defer_count = stance_counts.get("defer", 0)

        # High dissent = low consensus
        if dissent_count > 0:
            return max(0.0, 1.0 - (dissent_count / total))

        # High defer = high consensus (agents stepping back)
        if defer_count >= total * 0.5:
            return 0.9

        # Mostly maintain/adjust = moderate consensus
        return 0.5 + (defer_count / total) * 0.3

    def _compute_speaking_pressure(self, voices: dict[str, AgentVoice]) -> float:
        """Compute speaking pressure from urgency signals.

        Returns: 0.0 to 1.0
        """
        if not voices:
            return 0.0

        max_urgency = 0
        total_urgency = 0
        for voice in voices.values():
            urgency = voice.salience.urgency
            max_urgency = max(max_urgency, urgency)
            total_urgency += urgency

        # Combine max and average
        avg_urgency = total_urgency / len(voices)
        return (max_urgency / 3.0 * 0.7) + (avg_urgency / 3.0 * 0.3)

    def _has_critical_urgency(self, voices: dict[str, AgentVoice]) -> bool:
        """Check if any agent has critical urgency (U=3)."""
        for voice in voices.values():
            if voice.salience.urgency >= 3:
                return True
        return False

    def _all_deferred(self, voices: dict[str, AgentVoice]) -> bool:
        """Check if all agents deferred."""
        if not voices:
            return False
        return all(v.stance == "defer" for v in voices.values())
