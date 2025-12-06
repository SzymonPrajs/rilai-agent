"""Base agency implementation for Rilai v2.

Agencies are routers/compressors that gate agent activation and filter outputs.
"""

import asyncio
import time
from abc import ABC, abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING

from rilai.agents.base import LLMAgent
from rilai.agents.protocol import AgencyConfig, AgentConfig, WorkingMemoryView

from .messages import AgencyAssessment, AgentAssessment, EventSignature, RilaiEvent, Value

if TYPE_CHECKING:
    from rilai.brain.modulators import AgentActivationState, GlobalModulators


class Agency(ABC):
    """Abstract base class for agencies containing multiple sub-agents."""

    def __init__(
        self,
        agency_id: str,
        name: str,
        description: str,
        value: Value,
    ):
        self.agency_id = agency_id
        self.name = name
        self.description = description
        self.value = value
        self.agents: dict[str, LLMAgent] = {}

    def register_agent(self, agent: LLMAgent) -> None:
        """Register a sub-agent with this agency."""
        self.agents[agent.agent_id] = agent

    @abstractmethod
    async def assess(
        self,
        event: RilaiEvent,
        context: WorkingMemoryView,
        activated_agents: list[str] | None = None,
    ) -> AgencyAssessment:
        """Run all (or specified) sub-agents and synthesize results."""
        ...


class GenericAgency(Agency):
    """Generic agency that works for all agency types.

    Uses LLMAgent for all sub-agents, loading prompts from markdown files.
    Acts as router/compressor:
    - Gates which agents to run based on event signature + modulators
    - Compresses outputs to top_hits + optional brief
    - Filters to high-salience outputs
    """

    # Agents that always run regardless of gating
    ALWAYS_ON_AGENTS = {"censor", "exception_handler", "trigger_watcher", "anomaly_detector"}

    # Domain markers for each agency type
    AGENCY_DOMAIN_MAP = {
        "emotion": "has_emotion_markers",
        "planning": "has_planning_markers",
        "social": "has_social_markers",
        "reasoning": "has_problem_markers",
        "execution": "has_action_markers",
        "creative": "has_problem_markers",
        "resource": "has_planning_markers",
        "self": None,  # Self runs on most inputs
        "inhibition": None,  # Control agencies always relevant
        "monitoring": None,  # Control agencies always relevant
    }

    def __init__(
        self,
        config: AgencyConfig,
        timeout_ms: int = 2000,
        salience_threshold: float = 0.5,
        max_agents_per_cycle: int | None = None,
    ):
        super().__init__(
            agency_id=config.agency_id,
            name=config.display_name,
            description=config.description,
            value=config.value,
        )
        self.config = config
        self.timeout_ms = timeout_ms
        self.salience_threshold = salience_threshold
        self.max_agents_per_cycle = max_agents_per_cycle

        # Create and register all sub-agents
        for agent_config in config.agents:
            agent = LLMAgent(
                agency_id=config.agency_id,
                agent_name=agent_config.name,
                value=config.value,
            )
            self.register_agent(agent)

    def gate_agents(
        self,
        event_sig: EventSignature | None,
        modulators: "GlobalModulators | None" = None,
        activation_states: dict[str, "AgentActivationState"] | None = None,
    ) -> list[str]:
        """Decide which agents to run based on event + global state.

        Returns: List of agent_ids to activate.
        """
        if event_sig is None:
            return list(self.agents.keys())

        candidates = []

        for agent_id, agent in self.agents.items():
            agent_name = agent_id.split(".")[-1] if "." in agent_id else agent_id

            # Always-on agents
            if agent_name in self.ALWAYS_ON_AGENTS:
                candidates.append(agent_id)
                continue

            # Domain matching
            domain_marker = self.AGENCY_DOMAIN_MAP.get(self.agency_id)
            if domain_marker is None or getattr(event_sig, domain_marker, False):
                candidates.append(agent_id)
                continue

            # Question events activate reasoning
            if event_sig.is_question and self.agency_id in ("reasoning", "creative"):
                candidates.append(agent_id)
                continue

            # Modulator-based activation
            if modulators and self._modulator_activates(modulators, agent_name):
                candidates.append(agent_id)
                continue

        # Apply cooldown filter
        if activation_states:
            candidates = self._filter_cooldowns(candidates, activation_states)

        # Apply budget limit
        if self.max_agents_per_cycle and len(candidates) > self.max_agents_per_cycle:
            candidates = candidates[: self.max_agents_per_cycle]

        return candidates

    def _modulator_activates(
        self, modulators: "GlobalModulators", agent_name: str
    ) -> bool:
        """Check if modulator values should activate this agent."""
        if modulators.arousal > 0.6 and self.agency_id in ("emotion", "monitoring"):
            return True
        if modulators.fatigue > 0.5 and self.agency_id in ("resource", "emotion"):
            return True
        if modulators.time_pressure > 0.5 and self.agency_id == "planning":
            return True
        if modulators.social_risk > 0.5 and self.agency_id in ("social", "inhibition"):
            return True
        return False

    def _filter_cooldowns(
        self,
        candidates: list[str],
        activation_states: dict[str, "AgentActivationState"],
    ) -> list[str]:
        """Filter out agents on cooldown."""
        filtered = []
        for agent_id in candidates:
            state = activation_states.get(agent_id)
            if state is None or not state.is_on_cooldown():
                filtered.append(agent_id)
            else:
                agent_name = agent_id.split(".")[-1]
                if agent_name in self.ALWAYS_ON_AGENTS:
                    filtered.append(agent_id)
        return filtered

    def compress_outputs(
        self,
        assessments: list[AgentAssessment],
        top_k: int = 3,
    ) -> tuple[list[str], str, int]:
        """Compress agent outputs to top_hits and compute agency_u_max.

        Returns: (top_hit_agent_ids, brief_summary, agency_u_max)
        """
        with_salience = [
            a for a in assessments if a.salience is not None and not a.is_quiet
        ]

        sorted_assessments = sorted(
            with_salience,
            key=lambda a: a.salience.raw_score if a.salience else 0,
            reverse=True,
        )

        top_hits = [a.agent_id for a in sorted_assessments[:top_k]]

        agency_u_max = 0
        for a in assessments:
            if a.salience is not None:
                agency_u_max = max(agency_u_max, a.salience.urgency)

        brief = ""
        if top_hits and sorted_assessments:
            top_agent = sorted_assessments[0]
            brief = f"{top_agent.agent_id.split('.')[-1]}: {top_agent.voice[:100]}"

        return top_hits, brief, agency_u_max

    async def assess(
        self,
        event: RilaiEvent,
        context: WorkingMemoryView,
        activated_agents: list[str] | None = None,
        event_sig: EventSignature | None = None,
        modulators: "GlobalModulators | None" = None,
        activation_states: dict[str, "AgentActivationState"] | None = None,
        on_agent_start=None,
        on_agent_complete=None,
    ) -> AgencyAssessment:
        """Run sub-agents with gating and compress results."""
        start_time = time.time()

        # Determine which agents to run
        gated_count = 0
        if activated_agents:
            agents_to_run = [
                self.agents[aid] for aid in activated_agents if aid in self.agents
            ]
        else:
            if event_sig is not None:
                gated_agent_ids = self.gate_agents(event_sig, modulators, activation_states)
                agents_to_run = [self.agents[aid] for aid in gated_agent_ids]
                gated_count = len(self.agents) - len(agents_to_run)
            else:
                agents_to_run = list(self.agents.values())

        # Run agents in parallel
        tasks = [
            self._run_agent_safe(agent, event, context, on_agent_start, on_agent_complete)
            for agent in agents_to_run
        ]
        results = await asyncio.gather(*tasks)

        # Filter out errors
        assessments: list[AgentAssessment] = [
            r for r in results if isinstance(r, AgentAssessment)
        ]

        # Compress outputs
        top_hits, brief, agency_u_max = self.compress_outputs(assessments)

        # Filter to high-salience assessments
        high_salience_assessments = [
            a
            for a in assessments
            if a.salience is not None
            and (a.salience.raw_score >= self.salience_threshold or not a.is_quiet)
        ]
        if len(high_salience_assessments) < 2 and assessments:
            high_salience_assessments = assessments

        processing_time_ms = int((time.time() - start_time) * 1000)

        return AgencyAssessment(
            agency_id=self.agency_id,
            value=self.value,
            agency_u_max=agency_u_max,
            top_hits=top_hits,
            brief=brief,
            sub_assessments=high_salience_assessments,
            active_agents=len(assessments),
            total_agents=len(self.agents),
            gated_agents=gated_count,
            processing_time_ms=processing_time_ms,
            timestamp=datetime.now(),
        )

    async def _run_agent_safe(
        self,
        agent: LLMAgent,
        event: RilaiEvent,
        context: WorkingMemoryView,
        on_agent_start=None,
        on_agent_complete=None,
    ) -> AgentAssessment | Exception:
        """Run a single agent with timeout and error handling."""
        if on_agent_start:
            await on_agent_start(agent.agent_id)

        result = None
        try:
            result = await asyncio.wait_for(
                agent.assess(event, context),
                timeout=self.timeout_ms / 1000,
            )
            return result
        except asyncio.TimeoutError:
            result = TimeoutError(f"Agent {agent.agent_id} timed out")
            return result
        except Exception as e:
            result = e
            return result
        finally:
            if on_agent_complete and result is not None:
                await on_agent_complete(agent.agent_id, result)
