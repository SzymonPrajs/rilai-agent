"""Stance aggregation from agent outputs.

Computes a stance vector by aggregating signals from emotion and social agents.
This is a deterministic computation (no LLM calls).
"""

from rilai.council.collector import CollectedAssessments


def aggregate_stance(collected: CollectedAssessments) -> dict:
    """Aggregate stance from agent assessments.

    Maps agent outputs to stance dimensions:
    - Emotion agents (stress, wellbeing, motivation) → arousal, valence, strain
    - Social agents (empathy, attachment) → closeness, safety
    - Urgency/confidence → arousal, certainty

    Args:
        collected: Collected assessments from all agencies

    Returns:
        Stance dict with dimensions and derived quantities
    """
    # Start with neutral defaults
    stance = {
        "valence": 0.0,      # [-1, 1]
        "arousal": 0.3,      # [0, 1]
        "control": 0.7,      # [0, 1]
        "certainty": 0.5,    # [0, 1]
        "safety": 0.8,       # [0, 1]
        "closeness": 0.3,    # [0, 1]
        "curiosity": 0.5,    # [0, 1]
        "strain": 0.1,       # [0, 1]
    }

    # Counters for weighted averaging
    emotion_signals = []
    social_signals = []

    for agent in collected.all_agents:
        if agent.salience is None:
            continue

        urgency = agent.salience.urgency
        confidence = agent.salience.confidence
        score = agent.salience.raw_score
        agent_name = agent.agent_id.lower()

        # Map emotion agents to stance
        if "stress" in agent_name:
            # High stress urgency → high strain, low valence
            if urgency >= 2:
                emotion_signals.append(("strain", min(urgency / 3.0, 1.0)))
                emotion_signals.append(("valence", -urgency / 3.0))
                emotion_signals.append(("arousal", min(urgency / 3.0 + 0.2, 1.0)))

        elif "wellbeing" in agent_name:
            # Wellbeing with high confidence → positive valence
            if confidence >= 2:
                valence_delta = (confidence - 1.5) / 1.5  # Map 0-3 to roughly -1 to 1
                emotion_signals.append(("valence", valence_delta))
            # Low urgency wellbeing = calm
            if urgency <= 1:
                emotion_signals.append(("arousal", max(0.2, stance["arousal"] - 0.1)))

        elif "motivation" in agent_name:
            # High motivation → high arousal, positive valence
            if urgency >= 2 or confidence >= 2:
                emotion_signals.append(("arousal", min(0.6, stance["arousal"] + 0.2)))
                if confidence >= 2:
                    emotion_signals.append(("valence", 0.2))

        elif "mood" in agent_name:
            # Mood regulator affects overall valence
            if confidence >= 2:
                emotion_signals.append(("valence", (confidence - 1.5) / 3.0))

        # Map social agents to stance
        elif "empathy" in agent_name:
            # High empathy engagement → increased closeness
            if urgency >= 1 or confidence >= 2:
                social_signals.append(("closeness", min(0.6, stance["closeness"] + 0.15)))

        elif "attachment" in agent_name:
            # Attachment signals → safety and closeness
            if "detector" in agent_name:
                if urgency >= 2:
                    # Strong attachment bid detected → lower safety (user may be vulnerable)
                    social_signals.append(("safety", max(0.5, stance["safety"] - 0.1)))
                    social_signals.append(("closeness", min(0.7, stance["closeness"] + 0.2)))
            elif "learner" in agent_name:
                if confidence >= 2:
                    social_signals.append(("closeness", min(0.6, stance["closeness"] + 0.1)))

        elif "relationship" in agent_name:
            # Relationship signals affect closeness
            if score > 0:
                social_signals.append(("closeness", min(0.5, 0.3 + score / 10.0)))

        # Map reasoning agents to certainty
        elif "debugger" in agent_name or "researcher" in agent_name:
            if confidence >= 2:
                emotion_signals.append(("certainty", min(0.8, stance["certainty"] + 0.15)))
            elif confidence <= 1 and urgency >= 1:
                emotion_signals.append(("certainty", max(0.3, stance["certainty"] - 0.1)))

        # Map creative agents to curiosity
        elif "creative" in agent_name or "brainstorm" in agent_name:
            if urgency >= 1 or confidence >= 2:
                emotion_signals.append(("curiosity", min(0.8, stance["curiosity"] + 0.15)))

        # Map inhibition agents to control/safety
        elif "censor" in agent_name or "suppressor" in agent_name:
            if urgency >= 2:
                emotion_signals.append(("control", max(0.5, stance["control"] - 0.1)))
                social_signals.append(("safety", max(0.6, stance["safety"] - 0.1)))

        # Map monitoring agents
        elif "anomaly" in agent_name or "trigger" in agent_name:
            if urgency >= 2:
                emotion_signals.append(("arousal", min(0.7, stance["arousal"] + 0.15)))
                emotion_signals.append(("certainty", max(0.4, stance["certainty"] - 0.1)))

    # Apply signals with averaging
    for dim, value in emotion_signals + social_signals:
        # Weighted blend toward signal
        stance[dim] = stance[dim] * 0.7 + value * 0.3

    # Clamp all values to valid ranges
    stance["valence"] = max(-1.0, min(1.0, stance["valence"]))
    for dim in ["arousal", "control", "certainty", "safety", "closeness", "curiosity", "strain"]:
        stance[dim] = max(0.0, min(1.0, stance[dim]))

    # Compute derived quantities
    stance["readiness_to_speak"] = _compute_readiness(stance)
    stance["advice_suppression"] = _compute_advice_suppression(stance)

    return stance


def _compute_readiness(stance: dict) -> float:
    """Compute readiness to speak from stance dimensions."""
    readiness = (
        0.35 * stance["curiosity"] +
        0.25 * stance["closeness"] +
        0.20 * stance["control"] +
        0.10 * stance["arousal"] +
        0.10 * (stance["valence"] + 1) / 2 -  # Normalize valence to [0,1]
        0.45 * stance["strain"] -
        0.25 * (1 - stance["safety"])
    )
    return max(0.0, min(1.0, readiness))


def _compute_advice_suppression(stance: dict) -> float:
    """Compute advice suppression from stance dimensions."""
    suppression = (
        0.6 * stance["closeness"] +
        0.3 * (1 - stance["safety"]) +
        0.2 * stance["arousal"]
    )
    return max(0.0, min(1.0, suppression))
