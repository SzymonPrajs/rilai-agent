"""Tests for store module."""

import pytest
from pathlib import Path

from rilai.contracts.events import EngineEvent, EventKind
from rilai.store.event_log import EventLogWriter
from rilai.store.projections.turn_state import TurnStateProjection
from rilai.store.projections.session import SessionProjection
from rilai.store.projections.analytics import AnalyticsProjection
from rilai.store.projections.debug import DebugProjection


class TestEventLogWriter:
    def test_append_and_replay(self, tmp_path):
        db_path = tmp_path / "test.db"
        log = EventLogWriter(db_path)

        # Append events
        event1 = EngineEvent(
            session_id="test",
            turn_id=1,
            seq=0,
            ts_monotonic=1000.0,
            kind=EventKind.TURN_STARTED,
            payload={"user_input": "hello"},
        )
        event2 = EngineEvent(
            session_id="test",
            turn_id=1,
            seq=1,
            ts_monotonic=1001.0,
            kind=EventKind.TURN_COMPLETED,
            payload={"response": "hi"},
        )
        log.append(event1)
        log.append(event2)

        # Replay
        events = list(log.replay_turn("test", 1))
        assert len(events) == 2
        assert events[0].kind == EventKind.TURN_STARTED
        assert events[1].kind == EventKind.TURN_COMPLETED

    def test_next_seq(self, tmp_path):
        db_path = tmp_path / "test.db"
        log = EventLogWriter(db_path)

        assert log.next_seq("s1", 1) == 0
        assert log.next_seq("s1", 1) == 1
        assert log.next_seq("s1", 1) == 2
        assert log.next_seq("s1", 2) == 0  # New turn resets

    def test_append_batch(self, tmp_path):
        db_path = tmp_path / "test.db"
        log = EventLogWriter(db_path)

        events = [
            EngineEvent(
                session_id="test",
                turn_id=1,
                seq=i,
                ts_monotonic=1000.0 + i,
                kind=EventKind.AGENT_COMPLETED,
                payload={"agent_id": f"agent_{i}"},
            )
            for i in range(5)
        ]
        log.append_batch(events)

        assert log.count_events("test", 1) == 5

    def test_replay_session(self, tmp_path):
        db_path = tmp_path / "test.db"
        log = EventLogWriter(db_path)

        # Add events across multiple turns
        for turn_id in range(1, 4):
            log.append(EngineEvent(
                session_id="test",
                turn_id=turn_id,
                seq=0,
                ts_monotonic=1000.0 + turn_id,
                kind=EventKind.TURN_STARTED,
                payload={"turn_id": turn_id},
            ))

        events = list(log.replay_session("test"))
        assert len(events) == 3
        assert events[0].turn_id == 1
        assert events[2].turn_id == 3

    def test_get_events_by_kind(self, tmp_path):
        db_path = tmp_path / "test.db"
        log = EventLogWriter(db_path)

        log.append(EngineEvent(
            session_id="test",
            turn_id=1,
            seq=0,
            ts_monotonic=1000.0,
            kind=EventKind.TURN_STARTED,
            payload={},
        ))
        log.append(EngineEvent(
            session_id="test",
            turn_id=1,
            seq=1,
            ts_monotonic=1001.0,
            kind=EventKind.AGENT_COMPLETED,
            payload={"agent_id": "test"},
        ))
        log.append(EngineEvent(
            session_id="test",
            turn_id=1,
            seq=2,
            ts_monotonic=1002.0,
            kind=EventKind.AGENT_COMPLETED,
            payload={"agent_id": "test2"},
        ))

        agent_events = log.get_events_by_kind("test", EventKind.AGENT_COMPLETED)
        assert len(agent_events) == 2

    def test_get_last_turn_id(self, tmp_path):
        db_path = tmp_path / "test.db"
        log = EventLogWriter(db_path)

        assert log.get_last_turn_id("test") == 0

        for turn_id in range(1, 6):
            log.append(EngineEvent(
                session_id="test",
                turn_id=turn_id,
                seq=0,
                ts_monotonic=1000.0 + turn_id,
                kind=EventKind.TURN_STARTED,
                payload={},
            ))

        assert log.get_last_turn_id("test") == 5


class TestTurnStateProjection:
    def test_sensors_update(self):
        proj = TurnStateProjection()
        event = EngineEvent(
            session_id="test",
            turn_id=1,
            seq=0,
            ts_monotonic=1000.0,
            kind=EventKind.SENSORS_FAST_UPDATED,
            payload={"sensors": {"vulnerability": 0.8, "advice_requested": 0.2}},
        )
        updates = proj.apply(event)

        assert len(updates) == 1
        assert updates[0].kind == "sensors"
        assert proj.sensors["vulnerability"] == 0.8

    def test_agent_completed(self):
        proj = TurnStateProjection()
        event = EngineEvent(
            session_id="test",
            turn_id=1,
            seq=0,
            ts_monotonic=1000.0,
            kind=EventKind.AGENT_COMPLETED,
            payload={
                "agent_id": "emotion.stress",
                "observation": "High stress detected",
            },
        )
        updates = proj.apply(event)

        assert len(updates) == 1
        assert updates[0].kind == "agents"
        assert "emotion.stress" in proj.agent_logs[0]

    def test_quiet_agent_not_logged(self):
        proj = TurnStateProjection()
        event = EngineEvent(
            session_id="test",
            turn_id=1,
            seq=0,
            ts_monotonic=1000.0,
            kind=EventKind.AGENT_COMPLETED,
            payload={
                "agent_id": "emotion.stress",
                "observation": "Quiet",
            },
        )
        updates = proj.apply(event)

        assert len(updates) == 0
        assert len(proj.agent_logs) == 0

    def test_turn_lifecycle(self):
        proj = TurnStateProjection()

        # Start turn
        proj.apply(EngineEvent(
            session_id="test",
            turn_id=1,
            seq=0,
            ts_monotonic=1000.0,
            kind=EventKind.TURN_STARTED,
            payload={"turn_id": 1},
        ))
        assert proj.current_turn_id == 1

        # Stage change
        proj.apply(EngineEvent(
            session_id="test",
            turn_id=1,
            seq=1,
            ts_monotonic=1001.0,
            kind=EventKind.TURN_STAGE_CHANGED,
            payload={"stage": "agents"},
        ))
        assert proj.current_stage == "agents"

        # Complete turn
        proj.apply(EngineEvent(
            session_id="test",
            turn_id=1,
            seq=2,
            ts_monotonic=1002.0,
            kind=EventKind.TURN_COMPLETED,
            payload={"response": "Hello!"},
        ))
        assert proj.current_stage == "idle"
        assert proj.response == "Hello!"

    def test_reset_for_turn(self):
        proj = TurnStateProjection()
        proj.agent_logs.append("test log")
        proj.response = "old response"

        proj.reset_for_turn()
        assert len(proj.agent_logs) == 0
        assert proj.response == ""


class TestSessionProjection:
    def test_conversation_tracking(self):
        proj = SessionProjection()

        # Session start
        proj.apply(EngineEvent(
            session_id="test",
            turn_id=0,
            seq=0,
            ts_monotonic=1000.0,
            kind=EventKind.SESSION_STARTED,
            payload={},
        ))
        assert proj.session_id == "test"

        # User message
        proj.apply(EngineEvent(
            session_id="test",
            turn_id=1,
            seq=0,
            ts_monotonic=1001.0,
            kind=EventKind.TURN_STARTED,
            payload={"user_input": "Hello!"},
        ))
        assert proj.turn_count == 1

        # Assistant response
        proj.apply(EngineEvent(
            session_id="test",
            turn_id=1,
            seq=1,
            ts_monotonic=1002.0,
            kind=EventKind.VOICE_RENDERED,
            payload={"text": "Hi there!"},
        ))

        assert len(proj.messages) == 2
        assert proj.get_last_user_message() == "Hello!"
        assert proj.get_last_assistant_message() == "Hi there!"

    def test_get_history(self):
        proj = SessionProjection()

        for i in range(5):
            proj.apply(EngineEvent(
                session_id="test",
                turn_id=i + 1,
                seq=0,
                ts_monotonic=1000.0 + i,
                kind=EventKind.TURN_STARTED,
                payload={"user_input": f"Message {i}"},
            ))

        history = proj.get_history(limit=3)
        assert len(history) == 3


class TestAnalyticsProjection:
    def test_model_call_tracking(self):
        proj = AnalyticsProjection()

        proj.apply(EngineEvent(
            session_id="test",
            turn_id=1,
            seq=0,
            ts_monotonic=1000.0,
            kind=EventKind.MODEL_CALL_COMPLETED,
            payload={
                "model": "gpt-4",
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "reasoning_tokens": 20,
                "latency_ms": 500,
            },
        ))

        assert proj.total_prompt_tokens == 100
        assert proj.total_completion_tokens == 50
        assert proj.total_reasoning_tokens == 20
        assert proj.total_latency_ms == 500
        assert "gpt-4" in proj.model_usage

    def test_get_summary(self):
        proj = AnalyticsProjection()

        proj.apply(EngineEvent(
            session_id="test",
            turn_id=1,
            seq=0,
            ts_monotonic=1000.0,
            kind=EventKind.MODEL_CALL_COMPLETED,
            payload={
                "model": "gpt-4",
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "latency_ms": 500,
            },
        ))

        summary = proj.get_summary()
        assert summary["total_tokens"] == 150
        assert summary["call_count"] == 1


class TestDebugProjection:
    def test_agent_trace_tracking(self):
        proj = DebugProjection()

        # Turn started
        proj.apply(EngineEvent(
            session_id="test",
            turn_id=1,
            seq=0,
            ts_monotonic=1000.0,
            kind=EventKind.TURN_STARTED,
            payload={},
        ))

        # Agent started
        proj.apply(EngineEvent(
            session_id="test",
            turn_id=1,
            seq=1,
            ts_monotonic=1001.0,
            kind=EventKind.AGENT_STARTED,
            payload={"agent_id": "emotion.stress"},
        ))

        # Agent completed
        proj.apply(EngineEvent(
            session_id="test",
            turn_id=1,
            seq=2,
            ts_monotonic=1002.0,
            kind=EventKind.AGENT_COMPLETED,
            payload={
                "agent_id": "emotion.stress",
                "observation": "Stress detected",
                "urgency": 2,
                "confidence": 2,
            },
        ))

        assert len(proj.turn_traces[1]) == 1
        trace = proj.turn_traces[1][0]
        assert trace.agent_id == "emotion.stress"
        assert trace.urgency == 2

    def test_get_turn_summary(self):
        proj = DebugProjection()

        proj.apply(EngineEvent(
            session_id="test",
            turn_id=1,
            seq=0,
            ts_monotonic=1000.0,
            kind=EventKind.TURN_STARTED,
            payload={},
        ))
        proj.apply(EngineEvent(
            session_id="test",
            turn_id=1,
            seq=1,
            ts_monotonic=1001.0,
            kind=EventKind.AGENT_COMPLETED,
            payload={"agent_id": "test", "observation": "Test"},
        ))

        summary = proj.get_turn_summary(1)
        assert summary["agent_count"] == 1
