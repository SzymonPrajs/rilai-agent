"""Memory extraction for TUI panel.

Extracts memory summary from the Store for display in the TUI memory panel.
"""

from rilai.observability import Store


def extract_memory(store: Store) -> dict:
    """Extract memory summary for TUI panel.

    Args:
        store: The observability store

    Returns:
        Memory dict with summary, evidence, hypotheses
    """
    memory = {
        "summary": "",
        "evidence": [],
        "hypotheses": [],
    }

    # Get conversation history summary
    if store.stm:
        messages = store.stm.get_messages_as_dicts(limit=20)
        message_count = len(messages)

        if message_count > 0:
            # Count by role
            user_count = sum(1 for m in messages if m.get("role") == "user")
            assistant_count = sum(1 for m in messages if m.get("role") == "assistant")

            memory["summary"] = f"{message_count} messages ({user_count} user, {assistant_count} assistant)"

            # Extract any patterns from messages
            # For now, just provide counts - full implementation would use RelationalMemoryStore
            evidence = _extract_evidence(messages)
            if evidence:
                memory["evidence"] = evidence

    # Hypotheses would come from RelationalMemoryStore
    # For now, return empty list
    # TODO: Wire up RelationalMemoryStore when available

    return memory


def _extract_evidence(messages: list[dict]) -> list[dict]:
    """Extract evidence shards from recent messages.

    MVP implementation that extracts basic patterns.
    Full implementation would use RelationalMemoryStore.

    Args:
        messages: Recent conversation messages

    Returns:
        List of evidence shards
    """
    evidence = []

    # Look for patterns in recent messages
    for i, msg in enumerate(messages[-5:]):  # Last 5 messages
        content = msg.get("content", "")
        role = msg.get("role", "")

        if role == "user":
            # Look for emotional content
            emotion_words = ["feel", "feeling", "happy", "sad", "angry", "anxious", "stressed"]
            if any(w in content.lower() for w in emotion_words):
                evidence.append({
                    "type": "emotional_expression",
                    "source": f"message_{i}",
                    "brief": content[:50] + "..." if len(content) > 50 else content,
                })

            # Look for questions
            if "?" in content:
                evidence.append({
                    "type": "question",
                    "source": f"message_{i}",
                    "brief": content[:50] + "..." if len(content) > 50 else content,
                })

            # Look for goal/planning language
            planning_words = ["want to", "need to", "plan to", "going to", "should"]
            if any(w in content.lower() for w in planning_words):
                evidence.append({
                    "type": "goal_expression",
                    "source": f"message_{i}",
                    "brief": content[:50] + "..." if len(content) > 50 else content,
                })

    # Limit to 5 evidence items for display
    return evidence[:5]
