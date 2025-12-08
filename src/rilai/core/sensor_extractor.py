"""Sensor extraction from event signatures.

MVP implementation that maps EventSignature markers to sensor probabilities.
This is a deterministic computation (no LLM calls).

The full sensor ensemble would use LLM calls via SensorRunner, but this
provides immediate data for TUI display without added latency.
"""

from rilai.agencies.messages import EventSignature, RilaiEvent


# Sensor names matching the TUI panel expectations
SENSOR_NAMES = [
    "vulnerability",
    "advice_requested",
    "relational_bid",
    "ambiguity",
    "crisis",
    "routine_check_in",
    "info_seeking",
    "venting",
    "celebration",
]


def extract_sensors(event: RilaiEvent) -> dict[str, float]:
    """Extract sensor probabilities from event content.

    Uses EventSignature markers to infer sensor probabilities without LLM calls.
    This is an MVP approximation - the full implementation would run the
    sensor ensemble from src/rilai/sensors/.

    Args:
        event: The input event to analyze

    Returns:
        Dict mapping sensor names to probabilities [0, 1]
    """
    sig = EventSignature.from_event(event)
    content_lower = event.content.lower()

    sensors = {}

    # Vulnerability: emotional markers + short messages often indicate vulnerability
    vulnerability = 0.2
    if sig.has_emotion_markers:
        vulnerability += 0.4
    if sig.word_count < 10:
        vulnerability += 0.1
    if any(w in content_lower for w in ["scared", "afraid", "worried", "anxious", "hurt", "sad", "lonely"]):
        vulnerability += 0.3
    sensors["vulnerability"] = min(1.0, vulnerability)

    # Advice requested: problem markers + question
    advice_requested = 0.1
    if sig.has_problem_markers:
        advice_requested += 0.3
    if sig.is_question:
        advice_requested += 0.2
    if any(w in content_lower for w in ["should i", "what should", "how do i", "advice", "suggest", "recommend"]):
        advice_requested += 0.4
    sensors["advice_requested"] = min(1.0, advice_requested)

    # Relational bid: social markers + emotion + short utterances
    relational_bid = 0.1
    if sig.has_social_markers:
        relational_bid += 0.4
    if sig.has_emotion_markers:
        relational_bid += 0.2
    if sig.word_count < 15 and not sig.is_question:
        relational_bid += 0.1
    sensors["relational_bid"] = min(1.0, relational_bid)

    # Ambiguity: very short messages, no clear markers
    ambiguity = 0.3
    if sig.word_count < 5:
        ambiguity += 0.3
    if not any([sig.has_emotion_markers, sig.has_problem_markers, sig.has_social_markers, sig.is_question]):
        ambiguity += 0.2
    if "..." in event.content or "hmm" in content_lower or "idk" in content_lower:
        ambiguity += 0.2
    sensors["ambiguity"] = min(1.0, ambiguity)

    # Crisis: urgent markers + high emotion
    crisis = 0.0
    if sig.is_urgent:
        crisis += 0.5
    if any(w in content_lower for w in ["emergency", "crisis", "help me", "cant cope", "breaking down"]):
        crisis += 0.5
    if any(w in content_lower for w in ["suicide", "self harm", "end it", "give up"]):
        crisis = 1.0  # Override to max
    sensors["crisis"] = min(1.0, crisis)

    # Routine check-in: casual greetings, how-are-you patterns
    routine = 0.0
    if any(w in content_lower for w in ["hi", "hello", "hey", "good morning", "good evening"]):
        routine += 0.4
    if any(w in content_lower for w in ["how are you", "what's up", "checking in"]):
        routine += 0.4
    if sig.word_count < 8 and not sig.has_emotion_markers and not sig.has_problem_markers:
        routine += 0.2
    sensors["routine_check_in"] = min(1.0, routine)

    # Info seeking: questions + action/planning markers
    info_seeking = 0.1
    if sig.is_question:
        info_seeking += 0.3
    if sig.has_planning_markers:
        info_seeking += 0.2
    if sig.has_action_markers:
        info_seeking += 0.2
    if any(w in content_lower for w in ["what is", "how does", "can you explain", "tell me about"]):
        info_seeking += 0.3
    sensors["info_seeking"] = min(1.0, info_seeking)

    # Venting: emotion markers + not asking for advice
    venting = 0.0
    if sig.has_emotion_markers:
        venting += 0.3
    if not sig.is_question:
        venting += 0.2
    if any(w in content_lower for w in ["just need to", "vent", "frustrated", "annoyed", "ugh", "argh"]):
        venting += 0.4
    if sig.word_count > 20 and sig.has_emotion_markers:
        venting += 0.2  # Long emotional messages often are venting
    sensors["venting"] = min(1.0, venting)

    # Celebration: positive emotion markers
    celebration = 0.0
    if any(w in content_lower for w in ["excited", "happy", "great news", "awesome", "amazing", "yay", "woohoo"]):
        celebration += 0.5
    if any(w in content_lower for w in ["got the job", "passed", "won", "succeeded", "finally"]):
        celebration += 0.4
    if "!" in event.content:
        celebration += 0.1
    sensors["celebration"] = min(1.0, celebration)

    return sensors


def sensors_for_critics(sensors: dict[str, float]) -> dict[str, float]:
    """Format sensors dict for critic validation.

    Critics expect specific sensor names. This ensures compatibility.

    Args:
        sensors: Raw sensor dict from extract_sensors()

    Returns:
        Dict formatted for WorkspacePacket.sensor_summary
    """
    return {
        "vulnerability": sensors.get("vulnerability", 0.2),
        "advice_requested": sensors.get("advice_requested", 0.1),
        "relational_bid": sensors.get("relational_bid", 0.1),
        "ambiguity": sensors.get("ambiguity", 0.3),
        "crisis": sensors.get("crisis", 0.0),
        "routine_check_in": sensors.get("routine_check_in", 0.0),
        "info_seeking": sensors.get("info_seeking", 0.1),
        "venting": sensors.get("venting", 0.0),
        "celebration": sensors.get("celebration", 0.0),
    }
