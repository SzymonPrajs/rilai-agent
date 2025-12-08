"""Critics integration for engine pipeline.

Provides a simplified interface to run critics after council deliberation.
Builds a minimal WorkspacePacket from available engine data.
"""

import logging

from rilai.core.workspace import (
    CueExtraction,
    InteractionGoal,
    WorkspacePacket,
)
from rilai.council.pipeline import CouncilResponse
from rilai.providers.openrouter import OpenRouterClient

logger = logging.getLogger(__name__)


# Map speech act intents to interaction goals
INTENT_TO_GOAL = {
    "reflect": InteractionGoal.WITNESS,
    "nudge": InteractionGoal.REFRAME,
    "warn": InteractionGoal.BOUNDARY,
    "ask": InteractionGoal.INVITE,
    "summarize": InteractionGoal.WITNESS,
}


async def run_critics(
    response: str,
    user_input: str,
    turn_id: int,
    sensors: dict[str, float],
    council_response: CouncilResponse,
    provider: OpenRouterClient | None = None,
) -> list[dict]:
    """Run critics on the council response.

    Args:
        response: The final response text to validate
        user_input: The original user input
        turn_id: Current turn ID
        sensors: Sensor probabilities dict
        council_response: Full council response for context
        provider: OpenRouter client (optional, creates one if needed)

    Returns:
        List of critic result dicts for TUI display
    """
    # If no response, nothing to validate
    if not response or not response.strip():
        return []

    try:
        # Lazy import to avoid circular dependencies
        from rilai.critics.runner import CriticRunner

        # Create provider if not provided
        if provider is None:
            provider = OpenRouterClient()

        # Build minimal workspace packet for critics
        workspace = _build_workspace_for_critics(
            user_input=user_input,
            turn_id=turn_id,
            sensors=sensors,
            council_response=council_response,
        )

        # Run critics
        runner = CriticRunner(provider, tier="tiny")
        result = await runner.run(
            candidate=response,
            workspace=workspace,
        )

        # Convert to TUI format
        critics_list = [
            {
                "critic": output.critic,
                "passed": output.passed,
                "reason": output.reason,
                "severity": output.severity,
                "quote": output.quote,
            }
            for output in result.critic_outputs
        ]

        return critics_list

    except Exception as e:
        logger.error(f"Error running critics: {e}")
        # Return empty list on error - don't block the response
        return []


def _build_workspace_for_critics(
    user_input: str,
    turn_id: int,
    sensors: dict[str, float],
    council_response: CouncilResponse,
) -> WorkspacePacket:
    """Build a minimal WorkspacePacket for critic validation.

    Args:
        user_input: The original user input
        turn_id: Current turn ID
        sensors: Sensor probabilities dict
        council_response: Council response for extracting goal/constraints

    Returns:
        WorkspacePacket with required fields for critics
    """
    # Extract goal from speech act
    goal = InteractionGoal.WITNESS
    constraints = []

    synthesis = council_response.synthesis
    if synthesis.speech_act:
        intent = synthesis.speech_act.intent
        goal = INTENT_TO_GOAL.get(intent, InteractionGoal.WITNESS)
        constraints = synthesis.speech_act.do_not or []

    # Ensure required sensors for critics
    sensor_summary = {
        "vulnerability": sensors.get("vulnerability", 0.2),
        "advice_requested": sensors.get("advice_requested", 0.1),
        "relational_bid": sensors.get("relational_bid", 0.1),
        "ambiguity": sensors.get("ambiguity", 0.3),
        "crisis": sensors.get("crisis", 0.0),
    }

    # Build workspace
    workspace = WorkspacePacket(
        turn_id=turn_id,
        user_text=user_input,
        cues=CueExtraction(),  # Empty cues - not needed for critics
        sensor_summary=sensor_summary,
        goal=goal,
        constraints=constraints,
    )

    return workspace
