"""Background scheduler for Rilai with salience-based routing.

The Scheduler (formerly BrainDaemon) runs continuously in the background,
using global modulators and 2-stage activation to efficiently manage
which agencies/agents run each cycle.
"""

import asyncio
import logging
import uuid
from datetime import datetime

from rilai.agencies.base import GenericAgency
from rilai.agencies.messages import AgentAssessment, EventSignature, RilaiEvent
from rilai.agencies.runner import AgencyRunner, AgencyRunResult
from rilai.agents.protocol import WorkingMemoryView
from rilai.config import get_config
from rilai.core.events import Event, EventType, event_bus

from .modulators import (
    MODULATOR_MAP,
    AgentActivationState,
    GlobalModulators,
    get_archetype_weight,
)

logger = logging.getLogger(__name__)


# Phase 1 "watcher" agents - cheap, always-on monitors
PHASE1_AGENTS = {
    "monitoring.trigger_watcher",
    "monitoring.anomaly_detector",
    "inhibition.censor",
    "emotion.stress",
}


class Scheduler:
    """Salience-based scheduler with global modulators.

    Replaces the simple BrainDaemon with a more sophisticated system:
    - Maintains global modulators (arousal, fatigue, time_pressure, social_risk)
    - Maintains per-agent activation memory
    - Implements 2-stage tick: cheap watchers first, then selective deepening
    - Infers modulators from specific agent outputs
    """

    def __init__(
        self,
        council,  # Council instance
        agencies: dict[str, GenericAgency],
        tick_interval_seconds: float | None = None,
        user_id: str = "default",
        session_id: str | None = None,
    ):
        """Initialize the scheduler.

        Args:
            council: The Council instance to use for deliberation
            agencies: Dict of agency_id -> GenericAgency
            tick_interval_seconds: How often to run a thinking cycle
            user_id: User ID for events
            session_id: Session ID (generated if not provided)
        """
        config = get_config()
        self.council = council
        self.agencies = agencies
        self.tick_interval = tick_interval_seconds or config.DAEMON_TICK_INTERVAL
        self.user_id = user_id
        self.session_id = session_id or str(uuid.uuid4())

        self.running = False
        self._task: asyncio.Task | None = None

        # Global modulators
        self.modulators = GlobalModulators()

        # Per-agent activation states
        self.activation_states: dict[str, AgentActivationState] = {}
        self._init_activation_states()

        # Context accumulation
        self.context: dict = {
            "last_user_activity": None,
            "accumulated_observations": [],
            "tick_count": 0,
        }

    def _init_activation_states(self) -> None:
        """Initialize activation states for all agents."""
        for agency in self.agencies.values():
            for agent_id in agency.agents.keys():
                agent_name = agent_id.split(".")[-1]
                self.activation_states[agent_id] = AgentActivationState(
                    agent_id=agent_id,
                    archetype_weight=get_archetype_weight(agent_name),
                )

    async def start(self) -> None:
        """Start the background thinking loop."""
        if self.running:
            logger.warning("Scheduler already running")
            return

        self.running = True
        self._task = asyncio.create_task(self._think_loop())
        logger.info(f"Scheduler started (tick interval: {self.tick_interval}s)")

        await event_bus.emit(
            Event(EventType.DAEMON_STARTED, {"tick_interval": self.tick_interval})
        )

    async def stop(self) -> None:
        """Stop the background thinking loop."""
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Scheduler stopped")

        await event_bus.emit(Event(EventType.DAEMON_STOPPED, {}))

    async def _think_loop(self) -> None:
        """Main thinking loop with 2-stage activation."""
        config = get_config()
        urgency_levels = ["low", "medium", "high", "critical"]
        threshold = config.DAEMON_URGENCY_THRESHOLD
        threshold_index = (
            urgency_levels.index(threshold) if threshold in urgency_levels else 2
        )

        while self.running:
            try:
                # Build event for this tick
                event = self._build_context_event()
                event_sig = EventSignature.from_event(event)

                await event_bus.emit(
                    Event(
                        EventType.DAEMON_TICK,
                        {"tick": self.context["tick_count"], "modulators": self.modulators.to_dict()},
                    )
                )

                # Stage 1: Run cheap watchers
                phase1_result = await self._tick_phase_1(event, event_sig)

                # Check if any watcher triggered high urgency
                should_deepen = any(a.agency_u_max >= 2 for a in phase1_result)

                # Stage 2: Selective deepening if warranted
                if should_deepen:
                    agencies_to_deepen = self._select_agencies_for_deepening(
                        event_sig, phase1_result
                    )
                    decision = await self._tick_phase_2(
                        event, event_sig, agencies_to_deepen
                    )
                else:
                    # Just use phase 1 results for council
                    decision = await self._council_deliberate_light(event, phase1_result)

                # Emit if council wants to speak AND urgency meets threshold
                if decision.speak:
                    decision_urgency_index = (
                        urgency_levels.index(decision.urgency)
                        if decision.urgency in urgency_levels
                        else 0
                    )
                    if decision_urgency_index >= threshold_index:
                        await self._emit_proactive_message(decision)
                    else:
                        logger.debug(
                            f"Suppressed proactive message (urgency {decision.urgency} < threshold {threshold})"
                        )

                # Update modulators based on all assessments
                all_assessments = []
                for result in phase1_result:
                    all_assessments.extend(result.sub_assessments)
                self.update_modulators(all_assessments)

            except Exception as e:
                logger.error(f"Error in scheduler think cycle: {e}")

            # Wait for next tick
            await asyncio.sleep(self.tick_interval)

    async def _tick_phase_1(
        self, event: RilaiEvent, event_sig: EventSignature
    ) -> list:
        """Stage 1: Run cheap watchers/monitors.

        Returns: List of AgencyAssessments from watcher agencies.
        """
        self.context["tick_count"] += 1

        # Build working memory
        context = WorkingMemoryView(
            conversation_history=[],
            active_goals=[],
            recent_assessments=[],
            user_baseline=None,
            current_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )

        # Only run agencies that have phase 1 agents
        phase1_agencies = ["monitoring", "inhibition", "emotion"]
        results = []

        for agency_id in phase1_agencies:
            if agency_id not in self.agencies:
                continue

            agency = self.agencies[agency_id]

            # Only run phase 1 agents
            phase1_agent_ids = [
                aid for aid in agency.agents.keys() if aid in PHASE1_AGENTS
            ]

            if not phase1_agent_ids:
                continue

            try:
                result = await agency.assess(
                    event=event,
                    context=context,
                    activated_agents=phase1_agent_ids,
                    event_sig=event_sig,
                    modulators=self.modulators,
                    activation_states=self.activation_states,
                )
                results.append(result)

                # Update activation states
                for assessment in result.sub_assessments:
                    if assessment.agent_id in self.activation_states:
                        state = self.activation_states[assessment.agent_id]
                        state.mark_fired(cooldown_seconds=30.0)
                        if assessment.salience:
                            state.update_rolling_salience(assessment.salience.raw_score)

            except Exception as e:
                logger.error(f"Phase 1 error in {agency_id}: {e}")

        return results

    def _select_agencies_for_deepening(
        self, event_sig: EventSignature, phase1_results: list
    ) -> list[str]:
        """Select which agencies to run in phase 2 based on signals."""
        agencies_to_deepen = set()

        # Always include agencies based on event signature
        if event_sig.has_emotion_markers:
            agencies_to_deepen.add("emotion")
        if event_sig.has_planning_markers:
            agencies_to_deepen.add("planning")
            agencies_to_deepen.add("resource")
        if event_sig.has_social_markers:
            agencies_to_deepen.add("social")
        if event_sig.has_problem_markers:
            agencies_to_deepen.add("reasoning")
            agencies_to_deepen.add("creative")

        # Add based on modulator levels
        if self.modulators.arousal > 0.6:
            agencies_to_deepen.add("emotion")
            agencies_to_deepen.add("monitoring")
        if self.modulators.fatigue > 0.5:
            agencies_to_deepen.add("resource")
            agencies_to_deepen.add("self")
        if self.modulators.time_pressure > 0.5:
            agencies_to_deepen.add("planning")
        if self.modulators.social_risk > 0.5:
            agencies_to_deepen.add("social")
            agencies_to_deepen.add("inhibition")

        # Add based on phase 1 high-urgency signals
        for result in phase1_results:
            if result.agency_u_max >= 3:
                # Critical urgency - run related agencies
                agencies_to_deepen.add(result.agency_id)
                # Add complementary agencies
                if result.agency_id == "inhibition":
                    agencies_to_deepen.add("social")
                if result.agency_id == "emotion":
                    agencies_to_deepen.add("self")

        # Filter to available agencies
        return [a for a in agencies_to_deepen if a in self.agencies]

    async def _tick_phase_2(
        self, event: RilaiEvent, event_sig: EventSignature, agencies_to_deepen: list[str]
    ):
        """Stage 2: Run full agents in selected agencies."""
        context = WorkingMemoryView(
            conversation_history=[],
            active_goals=[],
            recent_assessments=[],
            user_baseline=None,
            current_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )

        config = get_config()
        # Create runner for full agency execution
        runner = AgencyRunner(
            agencies=[self.agencies[a] for a in agencies_to_deepen if a in self.agencies],
            timeout_ms=config.AGENCY_TIMEOUT_MS,
        )

        run_result = await runner.run_all_traced(event, context)

        # Update activation states
        for agency_result in run_result.assessments:
            for assessment in agency_result.sub_assessments:
                if assessment.agent_id in self.activation_states:
                    state = self.activation_states[assessment.agent_id]
                    state.mark_fired(cooldown_seconds=30.0)
                    if assessment.salience:
                        state.update_rolling_salience(assessment.salience.raw_score)

        # Run council deliberation
        council_response = await self.council.deliberate(
            user_input=event.content,
            run_result=run_result,
            context=context,
        )
        return council_response.synthesis

    async def _council_deliberate_light(self, event: RilaiEvent, phase1_results: list):
        """Light deliberation using only phase 1 results."""
        # Convert phase 1 results to AgencyRunResult format
        run_result = AgencyRunResult(
            assessments=phase1_results,
            total_time_ms=sum(r.processing_time_ms for r in phase1_results),
            agencies_succeeded=len(phase1_results),
            agencies_failed=0,
            errors={},
        )

        context = WorkingMemoryView(
            conversation_history=[],
            active_goals=[],
            recent_assessments=[],
            user_baseline=None,
            current_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )

        council_response = await self.council.deliberate(
            user_input=event.content,
            run_result=run_result,
            context=context,
        )
        return council_response.synthesis

    def update_modulators(self, assessments: list[AgentAssessment]) -> None:
        """Infer global modulators from specific agent outputs.

        Uses MODULATOR_MAP to determine which agents affect which modulators.
        """
        # Decay existing values
        self.modulators.decay(factor=0.9)

        # Update based on agent outputs
        for assessment in assessments:
            if assessment.salience is None:
                continue

            if assessment.agent_id in MODULATOR_MAP:
                modulator, weight, is_inverse = MODULATOR_MAP[assessment.agent_id]

                if assessment.salience.urgency >= 2:
                    # High urgency signals affect modulators
                    contribution = weight * (assessment.salience.confidence / 3.0)

                    if is_inverse:
                        # Inverse relationship (e.g., high wellbeing = low fatigue)
                        contribution = -contribution

                    self.modulators.update(
                        modulator, contribution, assessment.agent_id
                    )

        logger.debug(
            f"Modulators updated: arousal={self.modulators.arousal:.2f}, "
            f"fatigue={self.modulators.fatigue:.2f}, "
            f"time_pressure={self.modulators.time_pressure:.2f}, "
            f"social_risk={self.modulators.social_risk:.2f}"
        )

    def compute_salience(
        self, assessment: AgentAssessment, activation_state: AgentActivationState
    ) -> float:
        """Compute final salience score for an assessment.

        Formula: U * C * archetype_weight * recency_boost * (1 - cooldown_penalty)
        """
        if assessment.salience is None:
            return 0.0

        U = assessment.salience.urgency
        C = assessment.salience.confidence

        base = U * C
        archetype_w = activation_state.archetype_weight
        recency_boost = activation_state.get_recency_boost()
        cooldown_penalty = activation_state.get_cooldown_penalty()

        return base * archetype_w * recency_boost * (1 - cooldown_penalty)

    def _build_context_event(self) -> RilaiEvent:
        """Build an event from accumulated context."""
        context_parts = [
            f"[Background tick #{self.context['tick_count']}]",
            f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        ]

        if self.context.get("last_user_activity"):
            last = self.context["last_user_activity"]
            context_parts.append(f"Last user activity: {last}")

        if self.context.get("accumulated_observations"):
            obs = self.context["accumulated_observations"][-5:]
            context_parts.append(f"Recent observations: {obs}")

        # Include modulator state
        context_parts.append(
            f"Modulators: arousal={self.modulators.arousal:.1f}, "
            f"fatigue={self.modulators.fatigue:.1f}, "
            f"time_pressure={self.modulators.time_pressure:.1f}, "
            f"social_risk={self.modulators.social_risk:.1f}"
        )

        return RilaiEvent(
            event_id=f"background-{uuid.uuid4().hex[:8]}",
            type="background",
            content="\n".join(context_parts),
            user_id=self.user_id,
            session_id=self.session_id,
            timestamp=datetime.now(),
            metadata={"is_background": True, "tick": self.context["tick_count"]},
        )

    async def _emit_proactive_message(self, decision) -> None:
        """Emit a proactive message via event bus."""
        await event_bus.emit(
            Event(
                EventType.PROACTIVE_MESSAGE,
                {
                    "urgency": decision.urgency,
                    "message": decision.message,
                    "internal_state": decision.internal_state,
                    "modulators": self.modulators.to_dict(),
                    "timestamp": datetime.now().isoformat(),
                },
            )
        )
        logger.info(f"Proactive message emitted (urgency: {decision.urgency})")

    def update_context(self, key: str, value) -> None:
        """Update accumulated context."""
        self.context[key] = value

    def record_user_activity(self, activity: str) -> None:
        """Record user activity for context."""
        self.context["last_user_activity"] = {
            "activity": activity,
            "timestamp": datetime.now().isoformat(),
        }

    def add_observation(self, observation: str) -> None:
        """Add an observation to accumulated context."""
        self.context["accumulated_observations"].append(
            {
                "observation": observation,
                "timestamp": datetime.now().isoformat(),
            }
        )
        # Keep only last 20 observations
        if len(self.context["accumulated_observations"]) > 20:
            self.context["accumulated_observations"] = self.context[
                "accumulated_observations"
            ][-20:]

    def get_modulator_state(self) -> dict:
        """Get current modulator state for UI display."""
        return self.modulators.to_dict()


# Backwards compatibility alias
BrainDaemon = Scheduler
