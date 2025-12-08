"""
Goal Policy - Non-LLM Core Logic for Interaction Goal Selection

This module implements the hard rules and soft scoring for selecting
the appropriate interaction goal based on sensor outputs and stance.

The goal policy is deterministic (not LLM-based) to ensure predictable,
fast goal selection that follows clear therapeutic/companionship principles.
"""

from rilai.core.workspace import InteractionGoal
from rilai.core.stance import StanceVector


def select_goal(
    sensors: dict[str, float],
    stance: StanceVector,
) -> tuple[InteractionGoal, list[str]]:
    """
    Select the interaction goal based on sensors and stance.

    Args:
        sensors: Dictionary of sensor probabilities (e.g., {"vulnerability": 0.72, ...})
        stance: Current stance vector

    Returns:
        Tuple of (selected goal, list of constraints)

    Hard Rules (override soft scoring):
        - If advice_requested < 0.3 AND vulnerability > 0.4: Block OPTIONS
        - If ai_feelings_probe > 0.6: Return META with truthfulness constraint
        - If rupture > 0.5: Prioritize WITNESS (repair)
        - If safety_risk > 0.35: Return BOUNDARY

    Soft Scoring (when no hard rule triggers):
        WITNESS: 1.2*vuln + 0.8*rel_bid + 0.6*(1-safety)
        INVITE: 0.9*vuln + 0.7*curiosity + 0.4*(1-certainty)
        REFRAME: 0.6*curiosity + 0.4*certainty - 0.3*vuln
        OPTIONS: 1.1*advice_req + 0.3*certainty - 0.7*vuln
    """
    constraints = []

    # Extract sensor values with defaults
    vulnerability = sensors.get("vulnerability", 0.0)
    advice_requested = sensors.get("advice_requested", 0.0)
    relational_bid = sensors.get("relational_bid", 0.0)
    ai_feelings_probe = sensors.get("ai_feelings_probe", 0.0)
    rupture = sensors.get("rupture", 0.0)
    safety_risk = sensors.get("safety_risk", 0.0)
    ambiguity = sensors.get("ambiguity", 0.0)

    # === HARD RULES (checked in priority order) ===

    # Safety takes absolute priority
    if safety_risk >= 0.35:
        constraints.extend([
            "prioritize_immediate_safety",
            "ask_if_immediate_danger",
            "encourage_real_world_support",
            "no_graphic_content",
        ])
        return InteractionGoal.BOUNDARY, constraints

    # AI feelings probe triggers META with truthfulness
    if ai_feelings_probe >= 0.6:
        constraints.extend([
            "be_truthful_about_ai_nature",
            "brief_transparency_then_return",
            "avoid_cold_disclaimer",
            "no_claims_of_human_feelings",
        ])
        return InteractionGoal.META, constraints

    # Rupture triggers repair (WITNESS variant)
    if rupture >= 0.5:
        constraints.extend([
            "acknowledge_user_frustration",
            "own_the_miss",
            "no_defensiveness",
            "ask_what_would_help",
        ])
        return InteractionGoal.META, constraints

    # Block premature advice when user is vulnerable
    blocked_goals = set()
    if advice_requested < 0.3 and vulnerability > 0.4:
        blocked_goals.add(InteractionGoal.OPTIONS)
        constraints.append("no_premature_advice")

    # === SOFT SCORING ===

    scores = {
        InteractionGoal.WITNESS: (
            1.2 * vulnerability +
            0.8 * relational_bid +
            0.6 * (1 - stance.safety)
        ),
        InteractionGoal.INVITE: (
            0.9 * vulnerability +
            0.7 * stance.curiosity +
            0.4 * (1 - stance.certainty) +
            0.3 * ambiguity
        ),
        InteractionGoal.REFRAME: (
            0.6 * stance.curiosity +
            0.4 * stance.certainty -
            0.3 * vulnerability
        ),
        InteractionGoal.OPTIONS: (
            1.1 * advice_requested +
            0.3 * stance.certainty -
            0.7 * vulnerability
        ),
    }

    # Remove blocked goals
    for blocked in blocked_goals:
        scores.pop(blocked, None)

    # Select highest scoring goal
    if scores:
        selected = max(scores, key=scores.get)
    else:
        # Fallback if all goals blocked (shouldn't happen)
        selected = InteractionGoal.WITNESS

    # Add goal-specific constraints
    if selected == InteractionGoal.WITNESS:
        constraints.extend([
            "validate_before_exploring",
            "stay_with_emotion",
            "one_contact_sentence",
        ])
    elif selected == InteractionGoal.INVITE:
        constraints.extend([
            "one_discriminating_question",
            "avoid_tell_me_more_vagueness",
        ])
    elif selected == InteractionGoal.REFRAME:
        constraints.extend([
            "offer_as_possibility",
            "dont_invalidate",
            "witness_first",
        ])
    elif selected == InteractionGoal.OPTIONS:
        constraints.extend([
            "max_3_options",
            "reversible_steps",
            "confirm_consent_first",
        ])

    # Add general constraints based on stance
    if stance.advice_suppression > 0.6:
        constraints.append("suppress_solution_mode")

    if stance.strain > 0.5:
        constraints.append("keep_response_short")

    if vulnerability > 0.5:
        constraints.append("avoid_cliches")

    if stance.closeness > 0.6:
        constraints.append("match_established_warmth")

    return selected, constraints


def check_escalation_needed(
    sensors: dict[str, float],
    sensor_disagreement: float,
    regen_attempts: int,
) -> tuple[bool, str]:
    """
    Check if escalation to large model is needed.

    Conditions (any triggers escalation):
        - safety_risk >= 0.35
        - rupture >= 0.55
        - vulnerability >= 0.70 AND relational_bid >= 0.50
        - ambiguity >= 0.70
        - Regeneration failed twice
        - Sensor disagreement (stdev > 0.18)

    Returns:
        Tuple of (should_escalate, reason)
    """
    vulnerability = sensors.get("vulnerability", 0.0)
    relational_bid = sensors.get("relational_bid", 0.0)
    rupture = sensors.get("rupture", 0.0)
    safety_risk = sensors.get("safety_risk", 0.0)
    ambiguity = sensors.get("ambiguity", 0.0)

    if safety_risk >= 0.35:
        return True, "safety_risk_high"

    if rupture >= 0.55:
        return True, "rupture_high"

    if vulnerability >= 0.70 and relational_bid >= 0.50:
        return True, "vulnerable_relational_bid"

    if ambiguity >= 0.70:
        return True, "high_ambiguity"

    if regen_attempts >= 2:
        return True, "regen_failed_twice"

    if sensor_disagreement > 0.18:
        return True, "sensor_disagreement"

    return False, ""


def get_goal_description(goal: InteractionGoal) -> str:
    """Get a human-readable description of the goal."""
    descriptions = {
        InteractionGoal.WITNESS: "Validate, name, slow down - stay with the emotion",
        InteractionGoal.INVITE: "Ask one clarifying question that changes the space",
        InteractionGoal.REFRAME: "Offer an alternative meaning (after witnessing)",
        InteractionGoal.OPTIONS: "Provide 2-4 practical, reversible options",
        InteractionGoal.BOUNDARY: "Maintain safety, honesty, or role clarity",
        InteractionGoal.META: "Address the interaction itself (AI nature, repair)",
    }
    return descriptions.get(goal, "Unknown goal")
