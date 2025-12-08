"""Tests for TUI module."""

import pytest
from rilai.ui.projection import TurnStateProjection, UIUpdate
from rilai.contracts.events import EngineEvent, EventKind


class TestProjection:
    def test_turn_started_adds_user_message(self):
        projection = TurnStateProjection()

        event = EngineEvent(
            session_id="test",
            turn_id=1,
            seq=0,
            ts_monotonic=0.0,
            kind=EventKind.TURN_STARTED,
            payload={"user_input": "Hello", "turn_id": 1},
        )

        updates = projection.apply_event(event)

        assert any(u.kind == "chat" for u in updates)
        assert projection.messages[-1]["role"] == "user"
        assert projection.messages[-1]["content"] == "Hello"

    def test_agent_completed_logs_non_quiet(self):
        projection = TurnStateProjection()

        event = EngineEvent(
            session_id="test",
            turn_id=1,
            seq=1,
            ts_monotonic=0.1,
            kind=EventKind.AGENT_COMPLETED,
            payload={
                "agent_id": "emotion.stress",
                "observation": "User seems stressed",
                "urgency": 2,
                "salience": 0.8,
            },
        )

        updates = projection.apply_event(event)

        assert any(u.kind == "agents" for u in updates)
        assert len(projection.agent_logs) == 1
        assert projection.agent_logs[0]["agent_id"] == "emotion.stress"

    def test_agent_completed_ignores_quiet(self):
        projection = TurnStateProjection()

        event = EngineEvent(
            session_id="test",
            turn_id=1,
            seq=1,
            ts_monotonic=0.1,
            kind=EventKind.AGENT_COMPLETED,
            payload={
                "agent_id": "emotion.stress",
                "observation": "Quiet",
                "urgency": 0,
            },
        )

        updates = projection.apply_event(event)

        # No agent update for quiet
        assert not any(u.kind == "agents" and "completed" in u.payload for u in updates)
        assert len(projection.agent_logs) == 0

    def test_voice_rendered_adds_assistant_message(self):
        projection = TurnStateProjection()

        event = EngineEvent(
            session_id="test",
            turn_id=1,
            seq=10,
            ts_monotonic=1.0,
            kind=EventKind.VOICE_RENDERED,
            payload={"text": "I hear you're stressed."},
        )

        updates = projection.apply_event(event)

        assert any(u.kind == "chat" for u in updates)
        assert projection.messages[-1]["role"] == "assistant"

    def test_reset_for_turn_clears_transient(self):
        projection = TurnStateProjection()
        projection.agent_logs.append({"agent_id": "test"})
        projection.critics.append({"critic_id": "test"})
        projection.consensus = 0.9

        projection.reset_for_turn()

        assert len(projection.agent_logs) == 0
        assert len(projection.critics) == 0
        assert projection.consensus == 0.0

    def test_sensors_updated(self):
        projection = TurnStateProjection()

        event = EngineEvent(
            session_id="test",
            turn_id=1,
            seq=1,
            ts_monotonic=0.1,
            kind=EventKind.SENSORS_FAST_UPDATED,
            payload={"sensors": {"safety_risk": 0.2, "emotional_intensity": 0.5}},
        )

        updates = projection.apply_event(event)

        assert any(u.kind == "sensors" for u in updates)
        assert projection.sensors["safety_risk"] == 0.2
        assert projection.sensors["emotional_intensity"] == 0.5

    def test_stance_updated(self):
        projection = TurnStateProjection()
        projection.stance = {"valence": 0.0, "strain": 0.3}

        event = EngineEvent(
            session_id="test",
            turn_id=1,
            seq=2,
            ts_monotonic=0.2,
            kind=EventKind.STANCE_UPDATED,
            payload={"delta": {"valence": 0.1, "strain": 0.1}},
        )

        updates = projection.apply_event(event)

        assert any(u.kind == "stance" for u in updates)
        assert projection.stance["valence"] == 0.1
        assert projection.stance["strain"] == 0.4
        assert projection.stance_changes["valence"] == 0.1

    def test_turn_completed(self):
        projection = TurnStateProjection()
        projection.processing = True

        event = EngineEvent(
            session_id="test",
            turn_id=1,
            seq=100,
            ts_monotonic=2.0,
            kind=EventKind.TURN_COMPLETED,
            payload={"total_time_ms": 1500},
        )

        updates = projection.apply_event(event)

        assert projection.processing is False
        assert any(u.kind == "activity" for u in updates)

    def test_critics_updated(self):
        projection = TurnStateProjection()

        event = EngineEvent(
            session_id="test",
            turn_id=1,
            seq=50,
            ts_monotonic=1.5,
            kind=EventKind.CRITICS_UPDATED,
            payload={
                "passed": True,
                "results": [
                    {"critic_id": "safety", "passed": True},
                    {"critic_id": "tone", "passed": True},
                ]
            },
        )

        updates = projection.apply_event(event)

        assert any(u.kind == "critics" for u in updates)
        assert len(projection.critics) == 2

    def test_consensus_updated(self):
        projection = TurnStateProjection()

        event = EngineEvent(
            session_id="test",
            turn_id=1,
            seq=30,
            ts_monotonic=0.8,
            kind=EventKind.CONSENSUS_UPDATED,
            payload={"score": 0.85},
        )

        updates = projection.apply_event(event)

        assert projection.consensus == 0.85
        assert any(u.kind == "workspace" for u in updates)

    def test_council_decision_made(self):
        projection = TurnStateProjection()

        event = EngineEvent(
            session_id="test",
            turn_id=1,
            seq=40,
            ts_monotonic=1.0,
            kind=EventKind.COUNCIL_DECISION_MADE,
            payload={
                "speak": True,
                "urgency": "medium",
                "intent": "witness",
            },
        )

        updates = projection.apply_event(event)

        assert any(u.kind == "workspace" for u in updates)
        # Check the decision is in the update payload
        workspace_updates = [u for u in updates if u.kind == "workspace"]
        assert workspace_updates[0].payload["decision"]["speak"] is True

    def test_get_agent_summary_empty(self):
        projection = TurnStateProjection()
        summary = projection.get_agent_summary()
        assert summary == "No agent activity"

    def test_get_agent_summary_with_logs(self):
        projection = TurnStateProjection()
        projection.agent_logs = [
            {"agent_id": "emotion.stress", "observation": "User stressed", "urgency": 2},
            {"agent_id": "social.empathy", "observation": "High engagement", "urgency": 1},
        ]

        summary = projection.get_agent_summary()

        assert "emotion.stress" in summary
        assert "social.empathy" in summary
