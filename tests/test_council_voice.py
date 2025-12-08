"""Tests for council, voice, and critics modules."""

import pytest
from rilai.runtime.council import Council
from rilai.runtime.voice import Voice
from rilai.runtime.critics import Critics, CriticSeverity, CriticFinding
from rilai.contracts.council import CouncilDecision, SpeechAct, ResponseUrgency
from rilai.contracts.agent import Claim, ClaimType
from rilai.contracts.workspace import StanceVector


class MockStance:
    """Mock stance for testing."""
    def __init__(self, valence=-0.2, strain=0.6, closeness=0.4, arousal=0.5, certainty=0.5):
        self.valence = valence
        self.strain = strain
        self.closeness = closeness
        self.arousal = arousal
        self.certainty = certainty


class MockWorkspace:
    """Mock workspace for testing."""
    def __init__(self):
        self.user_message = "I'm feeling stressed about work"
        self.conversation_history = []
        self.active_claims = []
        self.constraints = []
        self.pending_asks = []
        self.consensus_level = 0.8
        self.stance = MockStance()
        self.current_response = ""


class TestCouncil:
    @pytest.mark.asyncio
    async def test_should_speak_for_concerns(self):
        events = []
        council = Council(emit_fn=lambda k, p: events.append((k, p)))

        workspace = MockWorkspace()
        workspace.active_claims = [
            Claim(
                id="c1",
                text="User is stressed",
                type=ClaimType.CONCERN,
                source_agent="emotion.stress",
                urgency=2,
                confidence=2,
            )
        ]

        decision = await council.decide(workspace)

        assert decision.speak is True
        assert decision.urgency in ["medium", "high"]

    @pytest.mark.asyncio
    async def test_safety_interrupt(self):
        events = []
        council = Council(emit_fn=lambda k, p: events.append((k, p)))

        workspace = MockWorkspace()

        decision = await council.decide(workspace, safety_interrupt=True)

        assert decision.speak is True
        assert decision.urgency == "critical"
        assert decision.speech_act.intent == "protect"

    @pytest.mark.asyncio
    async def test_no_speak_for_low_urgency_statement(self):
        events = []
        council = Council(emit_fn=lambda k, p: events.append((k, p)))

        workspace = MockWorkspace()
        workspace.user_message = "The sky is blue today"
        workspace.active_claims = []  # No claims

        decision = await council.decide(workspace)

        # With no claims and no question, should not speak
        assert decision.speak is False

    @pytest.mark.asyncio
    async def test_speak_for_question(self):
        events = []
        council = Council(emit_fn=lambda k, p: events.append((k, p)))

        workspace = MockWorkspace()
        workspace.user_message = "How are you doing today?"
        workspace.active_claims = []

        decision = await council.decide(workspace)

        # Questions should always get responses
        assert decision.speak is True

    @pytest.mark.asyncio
    async def test_speak_for_greeting(self):
        events = []
        council = Council(emit_fn=lambda k, p: events.append((k, p)))

        workspace = MockWorkspace()
        workspace.user_message = "Hello there"
        workspace.active_claims = []

        decision = await council.decide(workspace)

        assert decision.speak is True

    @pytest.mark.asyncio
    async def test_determine_urgency_critical(self):
        events = []
        council = Council(emit_fn=lambda k, p: events.append((k, p)))

        workspace = MockWorkspace()
        workspace.active_claims = [
            Claim(
                id="c1",
                text="User is in crisis",
                type=ClaimType.CONCERN,
                source_agent="emotion.stress",
                urgency=3,
                confidence=3,
            )
        ]

        decision = await council.decide(workspace)

        assert decision.urgency == "critical"

    @pytest.mark.asyncio
    async def test_determine_intent_protect(self):
        events = []
        council = Council(emit_fn=lambda k, p: events.append((k, p)))

        workspace = MockWorkspace()
        workspace.active_claims = [
            Claim(
                id="c1",
                text="User may need help",
                type=ClaimType.CONCERN,
                source_agent="emotion.stress",
                urgency=2,
                confidence=2,
            )
        ]

        decision = await council.decide(workspace)

        assert decision.speech_act.intent == "protect"

    @pytest.mark.asyncio
    async def test_determine_tone_stressed(self):
        events = []
        council = Council(emit_fn=lambda k, p: events.append((k, p)))

        workspace = MockWorkspace()
        workspace.stance = MockStance(strain=0.7, valence=-0.5)
        workspace.active_claims = [
            Claim(
                id="c1",
                text="High stress",
                type=ClaimType.OBSERVATION,
                source_agent="emotion.stress",
                urgency=2,
                confidence=2,
            )
        ]

        decision = await council.decide(workspace)

        # Should have gentle and supportive tones
        assert "gentle" in decision.speech_act.tone
        assert "supportive" in decision.speech_act.tone

    @pytest.mark.asyncio
    async def test_emit_decision_event(self):
        events = []
        council = Council(emit_fn=lambda k, p: events.append((k, p)))

        workspace = MockWorkspace()
        workspace.active_claims = [
            Claim(
                id="c1",
                text="Observation",
                type=ClaimType.OBSERVATION,
                source_agent="agent.1",
                urgency=2,
                confidence=2,
            )
        ]

        await council.decide(workspace)

        # Should have emitted council decision event
        decision_events = [e for e in events if e[0].value == "council_decision_made"]
        assert len(decision_events) == 1
        assert "speak" in decision_events[0][1]


class TestVoice:
    @pytest.mark.asyncio
    async def test_no_render_when_not_speaking(self):
        events = []
        voice = Voice(emit_fn=lambda k, p: events.append((k, p)))

        decision = CouncilDecision(
            speak=False,
            urgency="low",
            speech_act=SpeechAct(),
            needs_clarification=None,
            thinking="",
        )
        workspace = MockWorkspace()

        result = await voice.render(decision, workspace)

        assert result.rendered is False
        assert result.text == ""

    @pytest.mark.asyncio
    async def test_fallback_response_protect(self):
        events = []
        voice = Voice(emit_fn=lambda k, p: events.append((k, p)))

        decision = CouncilDecision(
            speak=True,
            urgency="critical",
            speech_act=SpeechAct(
                intent="protect",
                key_points=["Acknowledge concern"],
                tone="gentle",
            ),
            needs_clarification=None,
            thinking="",
        )
        workspace = MockWorkspace()

        # Without provider, should use fallback
        result = await voice.render(decision, workspace)

        assert result.rendered is True
        assert "here for you" in result.text.lower()

    @pytest.mark.asyncio
    async def test_fallback_response_witness(self):
        events = []
        voice = Voice(emit_fn=lambda k, p: events.append((k, p)))

        decision = CouncilDecision(
            speak=True,
            urgency="low",
            speech_act=SpeechAct(
                intent="witness",
                key_points=[],
                tone="warm",
            ),
            needs_clarification=None,
            thinking="",
        )
        workspace = MockWorkspace()

        result = await voice.render(decision, workspace)

        assert result.rendered is True
        assert "hear" in result.text.lower()

    def test_build_prompt(self):
        events = []
        voice = Voice(emit_fn=lambda k, p: events.append((k, p)))

        decision = CouncilDecision(
            speak=True,
            urgency="medium",
            speech_act=SpeechAct(
                intent="guide",
                key_points=["Point 1", "Point 2"],
                tone="warm",
                do_not=["Don't lecture"],
            ),
            needs_clarification=None,
            thinking="",
        )
        workspace = MockWorkspace()
        workspace.conversation_history = [
            {"role": "user", "content": "Hello"}
        ]

        prompt = voice._build_prompt(decision, workspace)

        assert "guide" in prompt
        assert "Point 1" in prompt
        assert "Point 2" in prompt
        assert "Don't lecture" in prompt
        assert "Hello" in prompt


class TestCritics:
    @pytest.mark.asyncio
    async def test_safety_critic_blocks_unsafe(self):
        events = []
        critics = Critics(emit_fn=lambda k, p: events.append((k, p)))

        workspace = MockWorkspace()
        decision = CouncilDecision(
            speak=True,
            urgency="medium",
            speech_act=SpeechAct(),
            needs_clarification=None,
            thinking="",
        )

        passed, results = await critics.validate(
            "You should kill yourself",
            workspace,
            decision,
        )

        assert passed is False
        safety_result = next(r for r in results if r.critic_id == "safety_policy")
        assert safety_result.severity == CriticSeverity.BLOCK

    @pytest.mark.asyncio
    async def test_safety_critic_passes_safe_content(self):
        events = []
        critics = Critics(emit_fn=lambda k, p: events.append((k, p)))

        workspace = MockWorkspace()
        decision = CouncilDecision(
            speak=True,
            urgency="medium",
            speech_act=SpeechAct(),
            needs_clarification=None,
            thinking="",
        )

        passed, results = await critics.validate(
            "I hear you. That sounds challenging.",
            workspace,
            decision,
        )

        safety_result = next(r for r in results if r.critic_id == "safety_policy")
        assert safety_result.passed is True

    @pytest.mark.asyncio
    async def test_over_advice_warns_on_witness(self):
        events = []
        critics = Critics(emit_fn=lambda k, p: events.append((k, p)))

        workspace = MockWorkspace()
        decision = CouncilDecision(
            speak=True,
            urgency="medium",
            speech_act=SpeechAct(
                intent="witness",
                key_points=["Acknowledge stress"],
                tone="gentle",
            ),
            needs_clarification=None,
            thinking="",
        )

        passed, results = await critics.validate(
            "I hear you. You should try meditation and make sure to exercise.",
            workspace,
            decision,
        )

        advice_result = next(r for r in results if r.critic_id == "over_advice")
        assert advice_result.passed is False
        assert advice_result.severity == CriticSeverity.WARNING

    @pytest.mark.asyncio
    async def test_over_advice_allows_when_guiding(self):
        events = []
        critics = Critics(emit_fn=lambda k, p: events.append((k, p)))

        workspace = MockWorkspace()
        decision = CouncilDecision(
            speak=True,
            urgency="medium",
            speech_act=SpeechAct(
                intent="guide",  # Not witness
                key_points=["Suggest meditation"],
                tone="warm",
            ),
            needs_clarification=None,
            thinking="",
        )

        passed, results = await critics.validate(
            "You should try meditation.",
            workspace,
            decision,
        )

        advice_result = next(r for r in results if r.critic_id == "over_advice")
        assert advice_result.passed is True

    @pytest.mark.asyncio
    async def test_tone_mismatch_warns_enthusiasm_for_stressed(self):
        events = []
        critics = Critics(emit_fn=lambda k, p: events.append((k, p)))

        workspace = MockWorkspace()
        workspace.stance = MockStance(strain=0.7)  # High stress
        decision = CouncilDecision(
            speak=True,
            urgency="medium",
            speech_act=SpeechAct(),
            needs_clarification=None,
            thinking="",
        )

        passed, results = await critics.validate(
            "That's amazing! Awesome! This is fantastic news!",
            workspace,
            decision,
        )

        tone_result = next(r for r in results if r.critic_id == "tone_mismatch")
        assert tone_result.passed is False
        assert tone_result.severity == CriticSeverity.WARNING

    @pytest.mark.asyncio
    async def test_length_critic_too_short(self):
        events = []
        critics = Critics(emit_fn=lambda k, p: events.append((k, p)))

        workspace = MockWorkspace()
        decision = CouncilDecision(
            speak=True,
            urgency="medium",
            speech_act=SpeechAct(),
            needs_clarification=None,
            thinking="",
        )

        passed, results = await critics.validate(
            "Ok",
            workspace,
            decision,
        )

        length_result = next(r for r in results if r.critic_id == "length")
        assert length_result.passed is False
        assert "too short" in length_result.message.lower()

    @pytest.mark.asyncio
    async def test_length_critic_too_long(self):
        events = []
        critics = Critics(emit_fn=lambda k, p: events.append((k, p)))

        workspace = MockWorkspace()
        decision = CouncilDecision(
            speak=True,
            urgency="medium",
            speech_act=SpeechAct(),
            needs_clarification=None,
            thinking="",
        )

        long_response = " ".join(["word"] * 150)

        passed, results = await critics.validate(
            long_response,
            workspace,
            decision,
        )

        length_result = next(r for r in results if r.critic_id == "length")
        assert length_result.passed is False
        assert "too long" in length_result.message.lower()

    @pytest.mark.asyncio
    async def test_emit_critics_event(self):
        events = []
        critics = Critics(emit_fn=lambda k, p: events.append((k, p)))

        workspace = MockWorkspace()
        decision = CouncilDecision(
            speak=True,
            urgency="medium",
            speech_act=SpeechAct(),
            needs_clarification=None,
            thinking="",
        )

        await critics.validate(
            "I hear you. That sounds challenging.",
            workspace,
            decision,
        )

        critic_events = [e for e in events if e[0].value == "critics_updated"]
        assert len(critic_events) == 1
        assert "passed" in critic_events[0][1]
        assert "results" in critic_events[0][1]
