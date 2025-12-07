"""Runs agencies in parallel and collects results."""

import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from rilai.agents.protocol import WorkingMemoryView
from rilai.core.events import Event, EventType, event_bus

from .base import Agency
from .messages import AgencyAssessment, EventSignature, RilaiEvent

if TYPE_CHECKING:
    from rilai.brain.modulators import AgentActivationState, GlobalModulators


@dataclass
class AgencyRunResult:
    """Result of running all agencies."""

    assessments: list[AgencyAssessment]
    total_time_ms: int
    agencies_succeeded: int
    agencies_failed: int
    errors: dict[str, str] = field(default_factory=dict)


class AgencyRunner:
    """Orchestrates parallel execution of agencies."""

    def __init__(
        self,
        timeout_ms: int = 5000,
        max_parallel: int = 7,
    ):
        self.agencies: dict[str, Agency] = {}
        self.timeout_ms = timeout_ms
        self.max_parallel = max_parallel

    def register_agency(self, agency: Agency) -> None:
        """Register an agency with the runner."""
        self.agencies[agency.agency_id] = agency

    async def run_all(
        self,
        event: RilaiEvent,
        context: WorkingMemoryView,
        activated_agencies: list[str] | None = None,
        event_sig: EventSignature | None = None,
        modulators: "GlobalModulators | None" = None,
        activation_states: dict[str, "AgentActivationState"] | None = None,
    ) -> AgencyRunResult:
        """Run all (or specified) agencies in parallel.

        Args:
            event: The input event
            context: Working memory view
            activated_agencies: Optional list of agency_ids to run
            event_sig: Event signature for gating
            modulators: Global modulator values
            activation_states: Per-agent activation states
        """
        start_time = time.time()

        # Determine which agencies to run
        agencies_to_run = (
            [
                self.agencies[aid]
                for aid in activated_agencies
                if aid in self.agencies
            ]
            if activated_agencies
            else list(self.agencies.values())
        )

        # Run in parallel with timeout
        tasks = [
            self._run_agency_safe(
                agency, event, context, event_sig, modulators, activation_states
            )
            for agency in agencies_to_run
        ]

        results = await asyncio.gather(*tasks)

        # Separate successes and failures
        assessments = []
        errors = {}
        for agency, result in zip(agencies_to_run, results):
            if isinstance(result, Exception):
                errors[agency.agency_id] = str(result)
            else:
                assessments.append(result)

        return AgencyRunResult(
            assessments=assessments,
            total_time_ms=int((time.time() - start_time) * 1000),
            agencies_succeeded=len(assessments),
            agencies_failed=len(errors),
            errors=errors,
        )

    async def run_all_traced(
        self,
        event: RilaiEvent,
        context: WorkingMemoryView,
        event_sig: EventSignature | None = None,
        modulators: "GlobalModulators | None" = None,
        activation_states: dict[str, "AgentActivationState"] | None = None,
    ) -> AgencyRunResult:
        """Run all agencies with event bus tracing."""
        start_time = time.time()

        # Emit processing started
        await event_bus.emit(
            Event(
                EventType.PROCESSING_STARTED,
                {"event_id": event.event_id, "agency_count": len(self.agencies)},
            )
        )

        async def on_agency_start(agency_id: str) -> None:
            await event_bus.emit(
                Event(EventType.AGENCY_STARTED, {"agency_id": agency_id})
            )

        async def on_agency_complete(agency_id: str, result: AgencyAssessment | Exception) -> None:
            if isinstance(result, Exception):
                await event_bus.emit(
                    Event(
                        EventType.ERROR,
                        {"agency_id": agency_id, "error": str(result)},
                    )
                )
            else:
                await event_bus.emit(
                    Event(
                        EventType.AGENCY_COMPLETED,
                        {
                            "agency_id": agency_id,
                            "agent_count": result.active_agents,
                            "agency_u_max": result.agency_u_max,
                            "processing_time_ms": result.processing_time_ms,
                        },
                    )
                )

        # Run all agencies
        tasks = []
        for agency in self.agencies.values():
            await on_agency_start(agency.agency_id)
            tasks.append(
                self._run_agency_safe(
                    agency, event, context, event_sig, modulators, activation_states,
                    emit_agent_events=True,
                )
            )

        results = await asyncio.gather(*tasks)

        # Process results
        assessments = []
        errors = {}
        for agency, result in zip(self.agencies.values(), results):
            await on_agency_complete(agency.agency_id, result)
            if isinstance(result, Exception):
                errors[agency.agency_id] = str(result)
            else:
                assessments.append(result)

        total_time_ms = int((time.time() - start_time) * 1000)

        # Emit processing completed
        await event_bus.emit(
            Event(
                EventType.PROCESSING_COMPLETED,
                {
                    "succeeded": len(assessments),
                    "failed": len(errors),
                    "total_time_ms": total_time_ms,
                },
            )
        )

        return AgencyRunResult(
            assessments=assessments,
            total_time_ms=total_time_ms,
            agencies_succeeded=len(assessments),
            agencies_failed=len(errors),
            errors=errors,
        )

    async def _run_agency_safe(
        self,
        agency: Agency,
        event: RilaiEvent,
        context: WorkingMemoryView,
        event_sig: EventSignature | None = None,
        modulators: "GlobalModulators | None" = None,
        activation_states: dict[str, "AgentActivationState"] | None = None,
        emit_agent_events: bool = False,
    ) -> AgencyAssessment | Exception:
        """Run a single agency with timeout and error handling."""
        # Create agent-level event callbacks if tracing enabled
        on_agent_start = None
        on_agent_complete = None

        if emit_agent_events:
            async def on_agent_start(agent_id: str) -> None:
                await event_bus.emit(
                    Event(EventType.AGENT_STARTED, {"agent_id": agent_id})
                )

            async def on_agent_complete(agent_id: str, result) -> None:
                if isinstance(result, Exception):
                    await event_bus.emit(
                        Event(
                            EventType.ERROR,
                            {"agent_id": agent_id, "error": str(result)},
                        )
                    )
                else:
                    # Extract thinking from trace
                    thinking = ""
                    if hasattr(result, "trace") and result.trace:
                        thinking = result.trace.thinking or ""
                    await event_bus.emit(
                        Event(
                            EventType.AGENT_COMPLETED,
                            {
                                "agent_id": agent_id,
                                "thinking": thinking,
                                "voice": getattr(result, "voice", ""),
                            },
                        )
                    )

        try:
            return await asyncio.wait_for(
                agency.assess(
                    event,
                    context,
                    event_sig=event_sig,
                    modulators=modulators,
                    activation_states=activation_states,
                    on_agent_start=on_agent_start,
                    on_agent_complete=on_agent_complete,
                ),
                timeout=self.timeout_ms / 1000,
            )
        except asyncio.TimeoutError:
            return TimeoutError(f"Agency {agency.agency_id} timed out")
        except Exception as e:
            return e
