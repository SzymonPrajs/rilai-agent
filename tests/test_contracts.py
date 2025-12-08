"""Tests for contracts module."""

import pytest
from datetime import datetime
from rilai.contracts import (
    EngineEvent,
    EventKind,
    AgentOutput,
    Claim,
    ClaimType,
    StanceVector,
    GlobalModulators,
    CouncilDecision,
    SpeechAct,
    SensorOutput,
    MemoryCandidate,
    EpisodicEvent,
    UserFact,
    WorkspaceState,
    Goal,
)


class TestEngineEvent:
    def test_event_creation(self):
        event = EngineEvent(
            session_id="test-session",
            turn_id=1,
            seq=0,
            ts_monotonic=1000.0,
            kind=EventKind.TURN_STARTED,
            payload={"user_input": "hello"},
        )
        assert event.session_id == "test-session"
        assert event.turn_id == 1
        assert event.kind == EventKind.TURN_STARTED

    def test_event_immutable(self):
        event = EngineEvent(
            session_id="test",
            turn_id=1,
            seq=0,
            ts_monotonic=1000.0,
            kind=EventKind.TURN_STARTED,
        )
        with pytest.raises(Exception):  # ValidationError for frozen
            event.turn_id = 2

    def test_all_event_kinds_exist(self):
        """Ensure key event kinds are defined."""
        assert EventKind.TURN_STARTED.value == "turn_started"
        assert EventKind.AGENT_COMPLETED.value == "agent_completed"
        assert EventKind.COUNCIL_DECISION_MADE.value == "council_decision_made"
        assert EventKind.MEMORY_COMMITTED.value == "memory_committed"


class TestAgentOutput:
    def test_quiet_output(self):
        output = AgentOutput.quiet("emotion.stress")
        assert output.observation == "Quiet"
        assert output.salience == 0.0
        assert output.urgency == 0
        assert output.confidence == 0

    def test_output_with_claims(self):
        claim = Claim(
            id="claim-1",
            text="User seems stressed",
            type=ClaimType.OBSERVATION,
            source_agent="emotion.stress",
            urgency=2,
            confidence=2,
        )
        output = AgentOutput(
            agent_id="emotion.stress",
            observation="High stress detected",
            salience=0.67,
            urgency=2,
            confidence=2,
            claims=[claim],
        )
        assert len(output.claims) == 1
        assert output.claims[0].type == ClaimType.OBSERVATION

    def test_output_validation(self):
        """Test field constraints."""
        with pytest.raises(Exception):
            AgentOutput(
                agent_id="test",
                observation="Test",
                salience=1.5,  # Out of bounds
                urgency=0,
                confidence=0,
            )


class TestClaim:
    def test_claim_creation(self):
        claim = Claim(
            id="c1",
            text="Test claim",
            type=ClaimType.RECOMMENDATION,
            source_agent="planning.short_term",
            urgency=1,
            confidence=2,
        )
        assert claim.type == ClaimType.RECOMMENDATION
        assert claim.supports == []
        assert claim.opposes == []

    def test_claim_with_relations(self):
        claim = Claim(
            id="c2",
            text="Another claim",
            type=ClaimType.CONCERN,
            source_agent="emotion.wellbeing",
            urgency=2,
            confidence=1,
            supports=["c1"],
            opposes=["c0"],
        )
        assert "c1" in claim.supports
        assert "c0" in claim.opposes


class TestStanceVector:
    def test_defaults(self):
        stance = StanceVector()
        assert stance.valence == 0.0
        assert stance.arousal == 0.3
        assert stance.strain == 0.0

    def test_derived_properties(self):
        stance = StanceVector(certainty=0.8, control=0.6)
        assert stance.readiness_to_speak == 0.7

    def test_to_dict(self):
        stance = StanceVector()
        d = stance.to_dict()
        assert "valence" in d
        assert "arousal" in d
        assert len(d) == 8  # All 8 dimensions

    def test_warmth_level(self):
        stance = StanceVector(closeness=0.8, valence=0.5)
        assert stance.warmth_level == (0.8 + 0.5) / 2


class TestGlobalModulators:
    def test_decay(self):
        mods = GlobalModulators(arousal=0.8, fatigue=0.5)
        changed = mods.decay(factor=0.9)
        assert changed
        assert mods.arousal < 0.8  # Decayed toward 0.3
        assert mods.fatigue < 0.5  # Decayed toward 0.0

    def test_to_dict(self):
        mods = GlobalModulators()
        d = mods.to_dict()
        assert "arousal" in d
        assert "fatigue" in d
        assert "time_pressure" in d
        assert "social_risk" in d


class TestCouncilDecision:
    def test_council_decision_creation(self):
        decision = CouncilDecision(
            speak=True,
            urgency="high",
            speech_act=SpeechAct(
                intent="witness",
                key_points=["I hear you"],
                tone="warm",
            ),
        )
        assert decision.speak is True
        assert decision.urgency == "high"
        assert decision.speech_act.intent == "witness"

    def test_default_speech_act(self):
        decision = CouncilDecision(speak=False)
        assert decision.speech_act.intent == "observe"
        assert decision.speech_act.tone == "warm"


class TestSensorOutput:
    def test_sensor_creation(self):
        sensor = SensorOutput(
            sensor="vulnerability",
            probability=0.7,
            evidence=["mentions anxiety"],
            notes="High stress indicators",
        )
        assert sensor.probability == 0.7
        assert len(sensor.evidence) == 1


class TestMemoryContracts:
    def test_memory_candidate(self):
        candidate = MemoryCandidate(
            type="episodic",
            content="User shared a difficult experience",
            importance=0.8,
            source_agent="emotion.wellbeing",
        )
        assert candidate.type == "episodic"
        assert candidate.importance == 0.8

    def test_episodic_event(self):
        event = EpisodicEvent(
            id="ep-1",
            summary="User shared about their job loss",
            emotions=["sad", "anxious"],
            participants=["user", "rilai"],
            tags=["employment", "stress"],
            importance=0.9,
        )
        assert event.importance == 0.9
        assert "sad" in event.emotions

    def test_user_fact(self):
        fact = UserFact(
            id="uf-1",
            text="Prefers direct communication",
            category="preference",
            confidence=0.8,
            source="turn_5",
        )
        assert fact.category == "preference"
        assert fact.mention_count == 1


class TestWorkspaceState:
    def test_workspace_defaults(self):
        ws = WorkspaceState()
        assert ws.user_message == ""
        assert ws.turn_id == 0
        assert isinstance(ws.stance, StanceVector)
        assert isinstance(ws.modulators, GlobalModulators)

    def test_workspace_with_goals(self):
        goal = Goal(
            id="g-1",
            text="Help user prepare for interview",
            priority=2,
        )
        ws = WorkspaceState(open_threads=[goal])
        assert len(ws.open_threads) == 1
        assert ws.open_threads[0].priority == 2
