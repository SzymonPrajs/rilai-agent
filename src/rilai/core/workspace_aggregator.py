"""Workspace aggregation from council response.

Builds a workspace summary dict for the TUI panel from council deliberation results.
"""

from rilai.council.collector import CollectedAssessments
from rilai.council.pipeline import CouncilResponse


def build_workspace(
    council_response: CouncilResponse,
    collected: CollectedAssessments,
) -> dict:
    """Build workspace summary from council response.

    Args:
        council_response: The full council deliberation result
        collected: Collected agent assessments

    Returns:
        Workspace dict with goal, primary_question, constraints, escalation
    """
    workspace = {
        "goal": "witness",  # default
        "primary_question": "",
        "constraints": [],
        "escalate_to_large": False,
        "escalation_reason": "",
    }

    synthesis = council_response.synthesis

    # Extract goal from speech act intent
    if synthesis.speech_act:
        intent = synthesis.speech_act.intent
        # Map speech act intent to goal
        goal_mapping = {
            "reflect": "witness",
            "nudge": "guide",
            "warn": "protect",
            "ask": "explore",
            "summarize": "synthesize",
        }
        workspace["goal"] = goal_mapping.get(intent, intent)

        # Extract constraints from do_not list
        workspace["constraints"] = synthesis.speech_act.do_not or []

    # Determine if speak decision indicates goal
    if not synthesis.speak:
        workspace["goal"] = "observe"  # Silent observation

    # Extract primary question from highest-salience agent
    primary_question = _extract_primary_question(collected)
    if primary_question:
        workspace["primary_question"] = primary_question

    # Check for escalation
    if council_response.deliberation_rounds > 1:
        workspace["escalate_to_large"] = True
        if council_response.final_consensus < 0.5:
            workspace["escalation_reason"] = "low_consensus"
        else:
            workspace["escalation_reason"] = "multiple_rounds"

    # High urgency also indicates escalation
    if synthesis.urgency in ("high", "critical"):
        workspace["escalate_to_large"] = True
        if not workspace["escalation_reason"]:
            workspace["escalation_reason"] = f"urgency_{synthesis.urgency}"

    return workspace


def _extract_primary_question(collected: CollectedAssessments) -> str:
    """Extract the primary question from agent assessments.

    Looks for question patterns in high-salience agent outputs.

    Args:
        collected: Collected agent assessments

    Returns:
        The primary question, or empty string if none found
    """
    # Get top agents by salience
    top_agents = collected.get_top_agents(n=5)

    for agent in top_agents:
        output = agent.voice

        # Look for explicit question markers
        if "?" in output:
            # Extract the question
            sentences = output.replace("...", ".").split(".")
            for sentence in sentences:
                sentence = sentence.strip()
                if "?" in sentence:
                    # Clean up and return
                    question = sentence.split("?")[0] + "?"
                    # Remove leading "Q:" or similar
                    if question.lower().startswith("q:"):
                        question = question[2:].strip()
                    if len(question) > 10:  # Avoid trivial questions
                        return question[:100]  # Truncate for display

        # Look for "wondering" or similar patterns
        if "wondering" in output.lower() or "curious" in output.lower():
            # Extract the relevant part
            for phrase in ["wondering if", "wondering about", "curious about", "curious whether"]:
                if phrase in output.lower():
                    idx = output.lower().index(phrase)
                    snippet = output[idx:idx + 80]
                    # Clean up
                    if "." in snippet:
                        snippet = snippet.split(".")[0]
                    return snippet.strip()[:100]

    return ""
