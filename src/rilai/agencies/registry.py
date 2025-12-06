"""Registry of all agencies and their configurations.

This file defines the 10-agency, 49-agent architecture based on Society of Mind principles.
"""

from rilai.agents.protocol import AgencyConfig, AgentConfig
from rilai.config import get_config

from .base import GenericAgency
from .messages import Value
from .runner import AgencyRunner

# =============================================================================
# AGENCY CONFIGURATIONS (10 Agencies, 49 Agents)
# =============================================================================

AGENCY_CONFIGS: dict[str, AgencyConfig] = {
    # =========================================================================
    # GOAL-ORIENTED AGENCIES (What do we want?)
    # =========================================================================
    "planning": AgencyConfig(
        agency_id="planning",
        display_name="Planning Agency",
        description="Goal pursuit and task management across timescales",
        value=Value.PRODUCTIVITY,
        agents=[
            AgentConfig(name="difference_engine"),
            AgentConfig(name="short_term"),
            AgentConfig(name="long_term"),
            AgentConfig(name="priority"),
        ],
        domain_marker="has_planning_markers",
    ),
    "resource": AgencyConfig(
        agency_id="resource",
        display_name="Resource Agency",
        description="Resource awareness and management (money, time, energy)",
        value=Value.RESOURCES,
        agents=[
            AgentConfig(name="financial"),
            AgentConfig(name="time"),
            AgentConfig(name="energy"),
        ],
        domain_marker="has_planning_markers",
    ),
    "self": AgencyConfig(
        agency_id="self",
        display_name="Self Agency",
        description="Identity maintenance and meta-cognition (B-brain functions)",
        value=Value.IDENTITY,
        agents=[
            AgentConfig(name="identity"),
            AgentConfig(name="values"),
            AgentConfig(name="meta_monitor"),
            AgentConfig(name="attachment_learner"),
            AgentConfig(name="reflection"),
            AgentConfig(name="self_model"),
        ],
        always_active=True,
    ),
    # =========================================================================
    # EVALUATIVE AGENCIES (How do we feel about this?)
    # =========================================================================
    "emotion": AgencyConfig(
        agency_id="emotion",
        display_name="Emotion Agency",
        description="Affective assessment and homeostatic regulation",
        value=Value.WELLBEING,
        agents=[
            AgentConfig(name="wellbeing"),
            AgentConfig(name="stress", always_on=True),
            AgentConfig(name="motivation"),
            AgentConfig(name="mood_regulator"),
            AgentConfig(name="wanting"),
        ],
        domain_marker="has_emotion_markers",
    ),
    "social": AgencyConfig(
        agency_id="social",
        display_name="Social Agency",
        description="Social cognition and relationship management",
        value=Value.CONNECTION,
        agents=[
            AgentConfig(name="relationships"),
            AgentConfig(name="empathy"),
            AgentConfig(name="norms"),
            AgentConfig(name="attachment_detector"),
            AgentConfig(name="mental_model"),
        ],
        domain_marker="has_social_markers",
    ),
    # =========================================================================
    # PROBLEM-SOLVING AGENCIES (How do we think?)
    # =========================================================================
    "reasoning": AgencyConfig(
        agency_id="reasoning",
        display_name="Reasoning Agency",
        description="Analytical thinking, problem solving, and cross-realm reasoning",
        value=Value.UNDERSTANDING,
        agents=[
            AgentConfig(name="debugger"),
            AgentConfig(name="researcher"),
            AgentConfig(name="reformulator"),
            AgentConfig(name="analogizer"),
            AgentConfig(name="creative"),
            AgentConfig(name="magnitude"),
        ],
        domain_marker="has_problem_markers",
    ),
    "creative": AgencyConfig(
        agency_id="creative",
        display_name="Creative Agency",
        description="Idea generation and synthesis (suspends censors)",
        value=Value.CREATIVITY,
        agents=[
            AgentConfig(name="brainstormer"),
            AgentConfig(name="synthesizer"),
            AgentConfig(name="frame_builder"),
        ],
        domain_marker="has_problem_markers",
    ),
    # =========================================================================
    # CONTROL AGENCIES (What should we NOT do?)
    # =========================================================================
    "inhibition": AgencyConfig(
        agency_id="inhibition",
        display_name="Inhibition Agency",
        description="Prevent harmful actions and states (censors, suppressors)",
        value=Value.SAFETY,
        agents=[
            AgentConfig(name="censor", always_on=True),
            AgentConfig(name="suppressor"),
            AgentConfig(name="exception_handler", always_on=True),
        ],
        always_active=True,
    ),
    "monitoring": AgencyConfig(
        agency_id="monitoring",
        display_name="Monitoring Agency",
        description="Vigilant observation and interrupt handling (demons)",
        value=Value.AWARENESS,
        agents=[
            AgentConfig(name="trigger_watcher", always_on=True),
            AgentConfig(name="anomaly_detector", always_on=True),
            AgentConfig(name="interrupt_manager"),
            AgentConfig(name="attention"),
        ],
        always_active=True,
    ),
    # =========================================================================
    # ACTION AGENCIES (How do we execute?)
    # =========================================================================
    "execution": AgencyConfig(
        agency_id="execution",
        display_name="Execution Agency",
        description="Task execution, habits, and action sequences",
        value=Value.ACTION,
        agents=[
            AgentConfig(name="executor"),
            AgentConfig(name="habits"),
            AgentConfig(name="script_runner"),
            AgentConfig(name="context_manager"),
            AgentConfig(name="output_filter"),
        ],
        domain_marker="has_action_markers",
    ),
}

# =============================================================================
# AGENCY GROUPS (for selective loading)
# =============================================================================

AGENCY_GROUPS = {
    "goal_oriented": ["planning", "resource", "self"],
    "evaluative": ["emotion", "social"],
    "problem_solving": ["reasoning", "creative"],
    "control": ["inhibition", "monitoring"],
    "action": ["execution"],
    "core": ["planning", "emotion", "execution"],
    "all": list(AGENCY_CONFIGS.keys()),
}


# =============================================================================
# FACTORY FUNCTIONS
# =============================================================================


def create_agency(agency_id: str, timeout_ms: int | None = None) -> GenericAgency:
    """Create an agency by ID."""
    if agency_id not in AGENCY_CONFIGS:
        raise ValueError(f"Unknown agency: {agency_id}")

    config = get_config()
    return GenericAgency(
        config=AGENCY_CONFIGS[agency_id],
        timeout_ms=timeout_ms or config.AGENT_TIMEOUT_MS,
    )


def create_all_agencies(timeout_ms: int | None = None) -> dict[str, GenericAgency]:
    """Create all agencies."""
    return {
        agency_id: create_agency(agency_id, timeout_ms) for agency_id in AGENCY_CONFIGS
    }


def create_agencies_by_group(
    group: str, timeout_ms: int | None = None
) -> dict[str, GenericAgency]:
    """Create agencies from a predefined group."""
    if group not in AGENCY_GROUPS:
        raise ValueError(
            f"Unknown agency group: {group}. Available: {list(AGENCY_GROUPS.keys())}"
        )

    return {
        agency_id: create_agency(agency_id, timeout_ms)
        for agency_id in AGENCY_GROUPS[group]
    }


def create_runner(
    agency_ids: list[str] | None = None,
    agency_timeout_ms: int | None = None,
    agent_timeout_ms: int | None = None,
) -> AgencyRunner:
    """Create an AgencyRunner with specified or all agencies."""
    config = get_config()

    # Determine which agencies to create
    if agency_ids is None:
        enabled = config.ENABLED_AGENCIES
        if enabled == "all":
            agency_ids = list(AGENCY_CONFIGS.keys())
        elif isinstance(enabled, list):
            agency_ids = enabled
        else:
            agency_ids = list(AGENCY_CONFIGS.keys())

    # Create runner
    runner = AgencyRunner(
        timeout_ms=agency_timeout_ms or config.AGENCY_TIMEOUT_MS,
        max_parallel=7,
    )

    # Create and register agencies
    for agency_id in agency_ids:
        if agency_id in AGENCY_CONFIGS:
            agency = create_agency(agency_id, agent_timeout_ms)
            runner.register_agency(agency)

    return runner


# =============================================================================
# VALIDATION
# =============================================================================


def validate_registry() -> list[str]:
    """Validate all agencies have required prompts and configs."""
    issues = []

    for agency_id, config in AGENCY_CONFIGS.items():
        if not config.agents:
            issues.append(f"Agency '{agency_id}' has no agents")

        agent_names = [a.name for a in config.agents]
        if len(agent_names) != len(set(agent_names)):
            issues.append(f"Agency '{agency_id}' has duplicate agent names")

    return issues


def get_agent_count() -> int:
    """Get total number of agents across all agencies."""
    return sum(len(config.agents) for config in AGENCY_CONFIGS.values())
