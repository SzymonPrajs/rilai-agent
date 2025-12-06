"""Council pipeline orchestrator."""

import time
from dataclasses import dataclass, replace
from datetime import datetime

from rilai.agencies.base import GenericAgency
from rilai.agencies.runner import AgencyRunResult
from rilai.agents.protocol import WorkingMemoryView
from rilai.core.events import Event, EventType, event_bus

from .collector import AssessmentCollector, CollectedAssessments
from .deliberation import DeliberationEngine
from .messages import CouncilDecision, SelfModelView, VoiceResult
from .synthesizer import Synthesizer
from .voice import Voice


@dataclass
class CouncilResponse:
    """Full council deliberation result."""

    synthesis: CouncilDecision
    collected: CollectedAssessments
    voice_result: VoiceResult | None
    total_deliberation_time_ms: int
    deliberation_rounds: int
    final_consensus: float


class Council:
    """Orchestrates council deliberation with optional multi-round mode.

    Pipeline:
    1. Collect agency assessments
    2. Optionally run multi-round deliberation
    3. Synthesize into SpeechAct
    4. Render SpeechAct into natural language
    """

    def __init__(
        self,
        agencies: dict[str, GenericAgency] | None = None,
        self_model: SelfModelView | None = None,
        enable_deliberation: bool = True,
    ):
        self.collector = AssessmentCollector()
        self.synthesizer = Synthesizer()
        self.voice = Voice()
        self.self_model = self_model or SelfModelView()
        self.agencies = agencies or {}
        self.enable_deliberation = enable_deliberation

        if agencies and enable_deliberation:
            self.deliberation_engine = DeliberationEngine(agencies)
        else:
            self.deliberation_engine = None

    async def deliberate(
        self,
        user_input: str,
        run_result: AgencyRunResult,
        context: WorkingMemoryView,
        enable_multi_round: bool = False,
        event: "RilaiEvent | None" = None,
    ) -> CouncilResponse:
        """Run the full deliberation pipeline.

        Args:
            user_input: The original user input
            run_result: Results from running all agencies
            context: Working memory context
            enable_multi_round: Whether to use multi-round deliberation
            event: Original event (needed for deliberation)

        Returns:
            CouncilResponse with synthesis, collected assessments, and voice result
        """
        start_time = time.time()

        await event_bus.emit(
            Event(
                EventType.COUNCIL_STARTED,
                {"total_assessments": len(run_result.assessments)},
            )
        )

        # Collect assessments
        collected = self.collector.collect(run_result)
        deliberation_rounds = 0
        final_consensus = 0.0

        # Multi-round deliberation if enabled
        if (
            enable_multi_round
            and self.deliberation_engine
            and event
            and self.enable_deliberation
        ):
            # Get all agent assessments
            all_assessments = []
            for agency_result in run_result.assessments:
                all_assessments.extend(agency_result.sub_assessments)

            # Run deliberation
            delib_result = await self.deliberation_engine.deliberate(
                event=event,
                base_context=context,
                initial_assessments=all_assessments,
            )

            deliberation_rounds = len(delib_result.rounds)
            final_consensus = delib_result.consensus_level

            # Update collected with final voices
            # (The synthesizer will use these)

        # Synthesize
        synthesis = await self.synthesizer.synthesize(
            user_input=user_input,
            collected=collected,
            context=context,
            deliberation_rounds=deliberation_rounds,
            final_consensus=final_consensus,
        )

        await event_bus.emit(
            Event(
                EventType.COUNCIL_DECISION,
                {
                    "speak": synthesis.speak,
                    "urgency": synthesis.urgency,
                    "deliberation_rounds": deliberation_rounds,
                },
            )
        )

        # Voice rendering
        voice_result = None
        if synthesis.speak and synthesis.speech_act:
            voice_result = await self.voice.render(
                speech_act=synthesis.speech_act,
                self_model=self.self_model,
                last_user_message=user_input,
            )
            synthesis = replace(synthesis, message=voice_result.message)

        total_time_ms = int((time.time() - start_time) * 1000)

        await event_bus.emit(
            Event(
                EventType.COUNCIL_COMPLETED,
                {
                    "speak": synthesis.speak,
                    "total_time_ms": total_time_ms,
                    "voice_time_ms": voice_result.processing_time_ms if voice_result else 0,
                },
            )
        )

        return CouncilResponse(
            synthesis=synthesis,
            collected=collected,
            voice_result=voice_result,
            total_deliberation_time_ms=total_time_ms,
            deliberation_rounds=deliberation_rounds,
            final_consensus=final_consensus,
        )
