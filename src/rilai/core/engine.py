"""Core engine for Rilai v2.

The Engine orchestrates:
- User message processing through agencies and council
- Background daemon operation
- Event bus integration
- Storage and observability
"""

import logging
import time
import uuid
from datetime import datetime

from rilai.agencies.messages import RilaiEvent
from rilai.agencies.registry import create_runner
from rilai.agents.protocol import WorkingMemoryView
from rilai.config import get_config
from rilai.council.pipeline import Council
from rilai.observability import get_store

from .events import Event, EventType, event_bus
from .turn_state import EngineResult, TurnState, build_turn_state
from .stance_aggregator import aggregate_stance
from .sensor_extractor import extract_sensors
from .workspace_aggregator import build_workspace
from .memory_extractor import extract_memory
from .critics_integration import run_critics

logger = logging.getLogger(__name__)


class Engine:
    """Main processing engine for Rilai.

    Coordinates:
    - Agency evaluation
    - Council deliberation
    - Voice rendering
    - Storage and tracing
    """

    def __init__(self):
        """Initialize the engine."""
        self.config = get_config()
        self.store = get_store()

        # Create agency runner
        self.agency_runner = create_runner()

        # Create council
        self.council = Council(
            agencies=self.agency_runner.agencies,
            enable_deliberation=True,
        )

        # User/session tracking
        self.user_id = "default"
        self.session_id: str | None = None

        # Processing state
        self._running = False

    async def start(self) -> None:
        """Start the engine."""
        if self._running:
            return

        self._running = True

        # Start event bus
        await event_bus.start()

        # Start session
        self.session_id = self.store.start_session(user_id=self.user_id)

        await event_bus.emit(
            Event(EventType.SESSION_STARTED, {"session_id": self.session_id})
        )

        logger.info(f"Engine started (session: {self.session_id})")

    async def stop(self) -> None:
        """Stop the engine."""
        if not self._running:
            return

        self._running = False

        # End session
        self.store.end_session()

        await event_bus.emit(
            Event(EventType.SESSION_ENDED, {"session_id": self.session_id})
        )

        # Stop event bus
        await event_bus.stop()

        logger.info("Engine stopped")

    async def process_message(self, user_input: str) -> EngineResult:
        """Process a user message through the full pipeline.

        Args:
            user_input: The user's message

        Returns:
            EngineResult with response and turn state for TUI panels
        """
        start_time = time.time()

        # Store user message
        self.store.add_message("user", user_input)

        # Start turn tracking
        turn_context = self.store.start_turn(user_input)

        await event_bus.emit(
            Event(
                EventType.PROCESSING_STARTED,
                {"user_input": user_input[:100], "turn_id": turn_context.turn_id},
            )
        )

        try:
            # Build event
            event = RilaiEvent(
                event_id=f"user-{uuid.uuid4().hex[:8]}",
                type="user_message",
                content=user_input,
                user_id=self.user_id,
                session_id=self.session_id,
                timestamp=datetime.now(),
            )

            # Build working memory context
            context = WorkingMemoryView(
                conversation_history=self.store.get_conversation_history(limit=10),
                active_goals=[],
                recent_assessments=[],
                user_baseline=None,
                current_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )

            # Run agencies
            run_result = await self.agency_runner.run_all_traced(event, context)

            # Log agent calls
            for agency_result in run_result.assessments:
                for assessment in agency_result.sub_assessments:
                    self.store.log_agent_call(
                        agent_id=assessment.agent_id,
                        output=assessment.output,
                        thinking=assessment.trace.thinking if assessment.trace else None,
                        urgency=assessment.salience.urgency if assessment.salience else 0,
                        confidence=assessment.salience.confidence if assessment.salience else 0,
                        processing_time_ms=assessment.processing_time_ms,
                    )

            # Council deliberation
            council_response = await self.council.deliberate(
                user_input=user_input,
                run_result=run_result,
                context=context,
                enable_multi_round=True,
                event=event,
            )

            # Log council decision
            self.store.log_council_call(
                speak=council_response.synthesis.speak,
                urgency=council_response.synthesis.urgency,
                speech_act=council_response.synthesis.speech_act.to_dict() if council_response.synthesis.speech_act else None,
                final_message=council_response.synthesis.message,
                thinking=council_response.synthesis.thinking,
                processing_time_ms=council_response.total_deliberation_time_ms,
            )

            # Get response
            if council_response.synthesis.speak:
                response = council_response.synthesis.message
            else:
                response = ""

            # Store response
            if response:
                self.store.add_message(
                    "assistant",
                    response,
                    urgency=council_response.synthesis.urgency,
                    thinking=council_response.synthesis.thinking,
                )

            # Build turn state for TUI panels
            collected = council_response.collected

            # Extract agents data for TUI
            agents_data = [
                {
                    "agent": agent.agent_id,
                    "salience": agent.salience.raw_score if agent.salience else 0,
                    "glimpse": agent.voice[:100] if agent.voice else "",
                    "stance_delta": {},  # Not tracked per-agent yet
                    "hypotheses": [],
                    "questions": [],
                }
                for agent in collected.all_agents
                if not agent.is_quiet
            ]

            # Aggregate stance from agents
            stance = aggregate_stance(collected)

            # Extract sensors from event
            sensors = extract_sensors(event)

            # Build workspace summary
            workspace = build_workspace(council_response, collected)

            # Extract memory summary
            memory = extract_memory(self.store)

            # Run critics (async, may add latency)
            critics = await run_critics(
                response=response,
                user_input=user_input,
                turn_id=turn_context.turn_id,
                sensors=sensors,
                council_response=council_response,
            )

            # Build complete turn state
            turn_state = build_turn_state(
                turn_id=turn_context.turn_id,
                stance=stance,
                sensors=sensors,
                agents=agents_data,
                workspace=workspace,
                critics=critics,
                memory=memory,
            )

            # End turn
            total_time_ms = int((time.time() - start_time) * 1000)
            self.store.end_turn(
                council_speak=council_response.synthesis.speak,
                council_urgency=council_response.synthesis.urgency,
                response=response,
            )

            await event_bus.emit(
                Event(
                    EventType.PROCESSING_COMPLETED,
                    {
                        "total_time_ms": total_time_ms,
                        "council_speak": council_response.synthesis.speak,
                        "urgency": council_response.synthesis.urgency,
                    },
                )
            )

            return EngineResult(response=response, turn_state=turn_state)

        except Exception as e:
            logger.error(f"Error processing message: {e}")
            await event_bus.emit(
                Event(EventType.ERROR, {"error": str(e)})
            )
            raise

    def get_conversation_history(self, limit: int = 20) -> list[dict]:
        """Get recent conversation history."""
        return self.store.get_conversation_history(limit)

    def get_stats(self) -> dict:
        """Get processing statistics."""
        return self.store.get_stats()
