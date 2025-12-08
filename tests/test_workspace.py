"""Tests for workspace module."""

import pytest
from rilai.runtime.workspace import Workspace
from rilai.runtime.reducer import apply_output, _claims_similar
from rilai.runtime.stance import (
    create_default_stance,
    stance_distance,
    stance_similarity,
    describe_stance,
)
from rilai.runtime.modulators import (
    update_modulators_from_agent,
    create_default_modulators,
)
from rilai.contracts.agent import AgentOutput, Claim, ClaimType
from rilai.contracts.workspace import StanceVector, GlobalModulators


class TestWorkspace:
    def test_initialization(self):
        ws = Workspace()
        assert ws.user_message == ""
        assert ws.turn_id == 0
        assert len(ws.active_claims) == 0

    def test_set_user_message(self):
        ws = Workspace()
        ws.set_user_message("Hello!")
        assert ws.user_message == "Hello!"

    def test_reset_for_turn(self):
        ws = Workspace()
        ws.set_user_message("test")
        ws.current_response = "response"
        ws.current_goal = "goal"
        ws.reset_for_turn()
        assert ws.current_response is None
        assert ws.current_goal is None
        assert len(ws.active_claims) == 0

    def test_to_prompt_context(self):
        ws = Workspace()
        ws.set_user_message("Test message")
        context = ws.to_prompt_context()
        assert "Test message" in context
        assert "Current stance" in context


class TestReducer:
    def test_stance_delta_application(self):
        ws = Workspace()
        initial_strain = ws.stance.strain

        output = AgentOutput(
            agent_id="emotion.stress",
            observation="High stress",
            salience=0.8,
            urgency=2,
            confidence=2,
            stance_delta={"strain": 0.1},
        )
        ws.apply_agent_output(output)

        # Strain should increase (with leaky integration)
        assert ws.stance.strain > initial_strain

    def test_stance_delta_clamping(self):
        ws = Workspace()

        # Try to apply a large delta
        output = AgentOutput(
            agent_id="test",
            observation="test",
            salience=1.0,
            urgency=3,
            confidence=3,
            stance_delta={"strain": 0.5},  # More than MAX_STANCE_DELTA
        )
        ws.apply_agent_output(output)

        # Should be clamped (leaky integration with clamped 0.15)
        assert ws.stance.strain <= 0.2  # Much less than 0.5

    def test_claim_addition(self):
        ws = Workspace()

        claim = Claim(
            id="1",
            text="User is stressed",
            type=ClaimType.OBSERVATION,
            source_agent="emotion.stress",
            urgency=2,
            confidence=2,
        )
        output = AgentOutput(
            agent_id="emotion.stress",
            observation="Stress detected",
            salience=0.67,
            urgency=2,
            confidence=2,
            claims=[claim],
        )
        ws.apply_agent_output(output)

        assert len(ws.active_claims) == 1
        assert ws.active_claims[0].text == "User is stressed"

    def test_claim_deduplication(self):
        ws = Workspace()

        claim1 = Claim(
            id="1",
            text="User appears stressed",
            type=ClaimType.OBSERVATION,
            source_agent="emotion.stress",
            urgency=1,
            confidence=2,
        )
        claim2 = Claim(
            id="2",
            text="User appears stressed",  # Identical text for >70% overlap
            type=ClaimType.OBSERVATION,
            source_agent="emotion.wellbeing",
            urgency=2,
            confidence=2,
        )

        output1 = AgentOutput(
            agent_id="a",
            observation="o",
            salience=0.5,
            urgency=1,
            confidence=2,
            claims=[claim1],
        )
        output2 = AgentOutput(
            agent_id="b",
            observation="o",
            salience=0.5,
            urgency=2,
            confidence=2,
            claims=[claim2],
        )

        ws.apply_agent_output(output1)
        ws.apply_agent_output(output2)

        # Should merge into one claim with max urgency
        assert len(ws.active_claims) == 1
        assert ws.active_claims[0].urgency == 2


class TestClaimsSimilar:
    def test_identical_claims(self):
        a = Claim(
            id="1", text="User is stressed", type=ClaimType.OBSERVATION,
            source_agent="a", urgency=1, confidence=1
        )
        b = Claim(
            id="2", text="User is stressed", type=ClaimType.OBSERVATION,
            source_agent="b", urgency=1, confidence=1
        )
        assert _claims_similar(a, b)

    def test_different_types(self):
        a = Claim(
            id="1", text="User is stressed", type=ClaimType.OBSERVATION,
            source_agent="a", urgency=1, confidence=1
        )
        b = Claim(
            id="2", text="User is stressed", type=ClaimType.RECOMMENDATION,
            source_agent="b", urgency=1, confidence=1
        )
        assert not _claims_similar(a, b)

    def test_low_overlap(self):
        a = Claim(
            id="1", text="The user seems very happy today", type=ClaimType.OBSERVATION,
            source_agent="a", urgency=1, confidence=1
        )
        b = Claim(
            id="2", text="Something entirely different here", type=ClaimType.OBSERVATION,
            source_agent="b", urgency=1, confidence=1
        )
        assert not _claims_similar(a, b)


class TestStanceUtilities:
    def test_create_default_stance(self):
        stance = create_default_stance()
        assert stance.valence == 0.0
        assert stance.arousal == 0.3
        assert stance.safety == 0.7

    def test_stance_distance(self):
        a = StanceVector()
        b = StanceVector(valence=1.0, arousal=1.0)
        distance = stance_distance(a, b)
        assert distance > 0

    def test_stance_similarity_same(self):
        a = StanceVector()
        b = StanceVector()
        assert stance_similarity(a, b) == 1.0

    def test_describe_stance_neutral(self):
        stance = StanceVector()
        desc = describe_stance(stance)
        # With default values, should be described as calm and distant
        assert "distant" in desc or desc == "neutral"

    def test_describe_stance_positive(self):
        stance = StanceVector(valence=0.5, arousal=0.7, closeness=0.8)
        desc = describe_stance(stance)
        assert "positive" in desc
        assert "activated" in desc
        assert "connected" in desc


class TestModulators:
    def test_create_default_modulators(self):
        mods = create_default_modulators()
        assert mods.arousal == 0.3
        assert mods.fatigue == 0.0

    def test_update_modulators_from_agent(self):
        mods = GlobalModulators()
        initial_arousal = mods.arousal

        changed = update_modulators_from_agent(mods, "emotion.stress", urgency=3)
        assert changed
        assert mods.arousal > initial_arousal

    def test_update_modulators_unknown_agent(self):
        mods = GlobalModulators()
        changed = update_modulators_from_agent(mods, "unknown.agent", urgency=3)
        assert not changed
