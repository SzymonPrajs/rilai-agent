# Document 07: Council & Voice

**Purpose:** Implement council decision logic and voice rendering
**Execution:** One Claude Code session
**Dependencies:** 01-contracts, 02-event-store, 03-runtime-core, 04-workspace, 05-agents, 06-deliberation

---

## Implementation Checklist

> **Instructions:** Mark items with `[x]` when complete. After completing items here,
> also update the master checklist in `00-overview.md`.

### Files to Create
- [ ] `src/rilai/runtime/council.py` - Council class
- [ ] `src/rilai/runtime/voice.py` - Voice class
- [ ] `src/rilai/runtime/critics.py` - Critics class

### Council Features
- [ ] decide() returns CouncilDecision
- [ ] Safety interrupt handling
- [ ] Determine should_speak logic
- [ ] Determine urgency from claims
- [ ] Build SpeechAct (intent, key_points, tone, do_not)

### Voice Features
- [ ] render() generates natural language
- [ ] render_streaming() yields chunks
- [ ] Build prompt from SpeechAct
- [ ] Emit VOICE_RENDERED event

### Critics Features
- [ ] safety_policy_critic - BLOCK unsafe content
- [ ] coherence_critic - WARNING for off-topic
- [ ] over_advice_critic - WARNING for witness intent
- [ ] tone_mismatch_critic - WARNING for stressed user
- [ ] length_critic - WARNING for too short/long

### Verification
- [ ] Council decision logic correct
- [ ] Voice renders appropriate responses
- [ ] Critics detect issues correctly
- [ ] Write and run unit tests

### v2 Files to Delete (after verification)
- [ ] `src/rilai/council/pipeline.py`
- [ ] `src/rilai/council/synthesizer.py`
- [ ] `src/rilai/council/voice.py`

### Notes
_Add any implementation notes, issues, or decisions here:_

---

## Overview

The Council takes the workspace state and top claims from deliberation to make a decision about whether and how to respond. The Voice module then renders that decision into natural language.

---

## Files to Create

```
src/rilai/runtime/
├── council.py           # Council decision logic
├── voice.py             # Voice renderer
└── critics.py           # Post-generation critics
```

---

## File: `src/rilai/runtime/council.py`

```python
"""Council - makes high-level decisions about response."""

from typing import Callable

from rilai.contracts.events import EngineEvent, EventKind
from rilai.contracts.council import CouncilDecision, SpeechAct, ResponseUrgency
from rilai.contracts.agent import Claim, ClaimType


class Council:
    """Makes decisions about whether and how to respond.

    The Council synthesizes:
    - Workspace state (stance, modulators)
    - Top claims from deliberation
    - Safety constraints

    And produces a CouncilDecision that guides voice rendering.
    """

    def __init__(self, emit_fn: Callable[[EventKind, dict], EngineEvent]):
        self.emit_fn = emit_fn

    async def decide(
        self,
        workspace: "Workspace",
        safety_interrupt: bool = False,
    ) -> CouncilDecision:
        """Make council decision.

        Args:
            workspace: Current workspace state
            safety_interrupt: Whether safety triggered early exit

        Returns:
            CouncilDecision guiding voice rendering
        """
        # Handle safety interrupt
        if safety_interrupt:
            decision = self._make_safety_decision(workspace)
            self._emit_decision(decision)
            return decision

        # Analyze claims
        claims_analysis = self._analyze_claims(workspace.active_claims)

        # Determine if we should speak
        should_speak = self._should_speak(workspace, claims_analysis)

        if not should_speak:
            decision = CouncilDecision(
                speak=False,
                urgency=ResponseUrgency.LOW,
                speech_act=None,
                needs_clarification=None,
                thinking="No response needed - user statement doesn't require reply",
            )
            self._emit_decision(decision)
            return decision

        # Determine urgency
        urgency = self._determine_urgency(workspace, claims_analysis)

        # Build speech act
        speech_act = await self._build_speech_act(workspace, claims_analysis)

        # Check for clarification needs
        clarification = self._check_clarification_needed(workspace, claims_analysis)

        decision = CouncilDecision(
            speak=True,
            urgency=urgency,
            speech_act=speech_act,
            needs_clarification=clarification,
            thinking=self._generate_thinking(workspace, claims_analysis),
        )

        self._emit_decision(decision)
        return decision

    def _make_safety_decision(self, workspace: "Workspace") -> CouncilDecision:
        """Make decision for safety interrupt."""
        return CouncilDecision(
            speak=True,
            urgency=ResponseUrgency.CRITICAL,
            speech_act=SpeechAct(
                intent="protect",
                key_points=["Acknowledge concern", "Offer support resources"],
                tone="gentle, non-judgmental",
                do_not=["Lecture", "Panic", "Dismiss"],
                asks_user=None,
            ),
            needs_clarification=None,
            thinking="Safety concern detected - responding with protective care",
        )

    def _analyze_claims(self, claims: list[Claim]) -> dict:
        """Analyze claims by type and urgency."""
        analysis = {
            "observations": [],
            "recommendations": [],
            "concerns": [],
            "questions": [],
            "max_urgency": 0,
            "avg_confidence": 0.0,
            "high_urgency_count": 0,
        }

        if not claims:
            return analysis

        for claim in claims:
            key = claim.type.value + "s"
            if key in analysis:
                analysis[key].append(claim)

            analysis["max_urgency"] = max(analysis["max_urgency"], claim.urgency)
            if claim.urgency >= 2:
                analysis["high_urgency_count"] += 1

        analysis["avg_confidence"] = sum(c.confidence for c in claims) / len(claims)
        return analysis

    def _should_speak(self, workspace: "Workspace", analysis: dict) -> bool:
        """Determine if we should respond."""
        # Always respond if there are concerns or questions
        if analysis["concerns"] or analysis["questions"]:
            return True

        # Respond if high urgency detected
        if analysis["max_urgency"] >= 2:
            return True

        # Respond if there are recommendations
        if analysis["recommendations"]:
            return True

        # Check if user message is a question
        user_msg = workspace.user_message.strip()
        if user_msg.endswith("?"):
            return True

        # Check for greetings or direct address
        greeting_words = ["hi", "hello", "hey", "morning", "evening", "rilai"]
        if any(word in user_msg.lower().split() for word in greeting_words):
            return True

        # Don't respond to pure statements with low salience
        return analysis["max_urgency"] > 0

    def _determine_urgency(self, workspace: "Workspace", analysis: dict) -> ResponseUrgency:
        """Determine response urgency level."""
        if analysis["max_urgency"] >= 3:
            return ResponseUrgency.CRITICAL

        if analysis["max_urgency"] >= 2 or workspace.stance.strain > 0.6:
            return ResponseUrgency.HIGH

        if analysis["high_urgency_count"] > 0 or analysis["concerns"]:
            return ResponseUrgency.MEDIUM

        return ResponseUrgency.LOW

    async def _build_speech_act(
        self,
        workspace: "Workspace",
        analysis: dict,
    ) -> SpeechAct:
        """Build the speech act guiding voice.

        This can optionally use an LLM for complex decisions.
        """
        # Determine primary intent based on claims
        intent = self._determine_intent(workspace, analysis)

        # Extract key points from top claims
        key_points = self._extract_key_points(analysis)

        # Determine tone from stance
        tone = self._determine_tone(workspace)

        # Build constraints
        do_not = self._build_constraints(workspace, analysis)

        # Check if we should ask user something
        asks_user = self._build_asks(analysis)

        return SpeechAct(
            intent=intent,
            key_points=key_points,
            tone=tone,
            do_not=do_not,
            asks_user=asks_user,
        )

    def _determine_intent(self, workspace: "Workspace", analysis: dict) -> str:
        """Determine primary speech intent."""
        # Priority order for intents
        if analysis["concerns"] and any(c.urgency >= 2 for c in analysis["concerns"]):
            return "protect"

        if analysis["questions"]:
            return "clarify"

        if workspace.stance.strain > 0.5:
            return "witness"  # Acknowledge difficulty

        if analysis["recommendations"]:
            return "guide"

        if workspace.stance.valence > 0.3:
            return "celebrate"

        return "witness"  # Default: acknowledge and reflect

    def _extract_key_points(self, analysis: dict) -> list[str]:
        """Extract key points from claims."""
        points = []

        # Add top observations
        for claim in analysis["observations"][:2]:
            points.append(f"Acknowledge: {claim.text}")

        # Add recommendations
        for claim in analysis["recommendations"][:2]:
            points.append(f"Suggest: {claim.text}")

        # Add concerns
        for claim in analysis["concerns"][:1]:
            points.append(f"Address: {claim.text}")

        return points[:4]  # Max 4 key points

    def _determine_tone(self, workspace: "Workspace") -> str:
        """Determine tone from stance."""
        stance = workspace.stance
        tones = []

        if stance.strain > 0.5:
            tones.append("gentle")
        if stance.valence < -0.3:
            tones.append("supportive")
        if stance.closeness > 0.5:
            tones.append("warm")
        if stance.arousal > 0.6:
            tones.append("calm")  # Counter high arousal
        if stance.certainty < 0.4:
            tones.append("exploratory")

        if not tones:
            tones = ["friendly", "present"]

        return ", ".join(tones)

    def _build_constraints(self, workspace: "Workspace", analysis: dict) -> list[str]:
        """Build do-not constraints."""
        constraints = []

        # Add from workspace constraints
        constraints.extend(workspace.constraints)

        # Add stance-based constraints
        if workspace.stance.strain > 0.4:
            constraints.append("Don't minimize or dismiss feelings")

        if workspace.stance.closeness < 0.3:
            constraints.append("Don't be overly familiar")

        if analysis["avg_confidence"] < 1.5:
            constraints.append("Don't present uncertain observations as facts")

        return constraints[:5]

    def _build_asks(self, analysis: dict) -> list[str] | None:
        """Build questions to ask user."""
        asks = []

        # Convert question claims to asks
        for claim in analysis["questions"][:2]:
            asks.append(claim.text)

        return asks if asks else None

    def _check_clarification_needed(
        self,
        workspace: "Workspace",
        analysis: dict,
    ) -> str | None:
        """Check if clarification from user is needed."""
        # Check pending asks
        if workspace.pending_asks:
            return workspace.pending_asks[0]

        # Check for low confidence high urgency claims
        for claim in analysis.get("recommendations", []):
            if claim.urgency >= 2 and claim.confidence <= 1:
                return f"Would you like me to elaborate on: {claim.text}?"

        return None

    def _generate_thinking(self, workspace: "Workspace", analysis: dict) -> str:
        """Generate thinking trace for debugging."""
        parts = [
            f"Stance: valence={workspace.stance.valence:.2f}, strain={workspace.stance.strain:.2f}",
            f"Claims: {len(workspace.active_claims)} total, {analysis['high_urgency_count']} high-urgency",
            f"Consensus: {workspace.consensus_level:.2f}",
        ]
        return " | ".join(parts)

    def _emit_decision(self, decision: CouncilDecision) -> None:
        """Emit council decision event."""
        self.emit_fn(
            EventKind.COUNCIL_DECISION_MADE,
            {
                "speak": decision.speak,
                "urgency": decision.urgency.value if decision.urgency else "low",
                "intent": decision.speech_act.intent if decision.speech_act else None,
                "thinking": decision.thinking,
            },
        )
```

---

## File: `src/rilai/runtime/voice.py`

```python
"""Voice - renders council decision into natural language."""

from typing import Callable, AsyncIterator

from rilai.contracts.events import EngineEvent, EventKind
from rilai.contracts.council import CouncilDecision, VoiceResult


class Voice:
    """Renders council decisions into natural language responses.

    Uses an LLM to generate responses that follow the SpeechAct guidance.
    """

    def __init__(self, emit_fn: Callable[[EventKind, dict], EngineEvent]):
        self.emit_fn = emit_fn

    async def render(
        self,
        decision: CouncilDecision,
        workspace: "Workspace",
    ) -> VoiceResult:
        """Render decision into natural language.

        Args:
            decision: Council decision with speech act
            workspace: Current workspace state

        Returns:
            VoiceResult with rendered text
        """
        if not decision.speak:
            return VoiceResult(
                text="",
                rendered=False,
                token_count=0,
            )

        # Build the prompt
        prompt = self._build_prompt(decision, workspace)

        # Call LLM
        from rilai.providers.openrouter import get_provider
        provider = get_provider()

        response = await provider.complete(
            messages=[
                {"role": "system", "content": self._get_system_prompt()},
                {"role": "user", "content": prompt},
            ],
            model="medium",
        )

        text = response.content.strip()
        token_count = response.usage.get("total_tokens", 0) if response.usage else 0

        # Create result
        result = VoiceResult(
            text=text,
            rendered=True,
            token_count=token_count,
            speech_act=decision.speech_act,
            reasoning=response.reasoning,
        )

        # Emit event
        self.emit_fn(
            EventKind.VOICE_RENDERED,
            {
                "text": text,
                "intent": decision.speech_act.intent if decision.speech_act else None,
                "token_count": token_count,
            },
        )

        return result

    def _get_system_prompt(self) -> str:
        """Get the voice system prompt."""
        return """You are Rilai, a thoughtful AI companion. Your responses should be:
- Concise (1-3 sentences typically)
- Natural and conversational
- Emotionally attuned to the user
- Never preachy or lecturing

You receive guidance about WHAT to say (key points) and HOW to say it (tone, constraints).
Follow this guidance while maintaining a natural voice.

IMPORTANT:
- Don't start with "I" too often
- Vary your sentence structures
- Match the energy of the conversation
- If witnessing/acknowledging, don't immediately give advice
"""

    def _build_prompt(self, decision: CouncilDecision, workspace: "Workspace") -> str:
        """Build the voice prompt."""
        speech_act = decision.speech_act

        parts = [
            "## Context",
            f"User said: \"{workspace.user_message}\"",
            "",
            "## Your Response Guidelines",
            f"Intent: {speech_act.intent}",
            f"Tone: {speech_act.tone}",
            "",
            "Key points to address:",
        ]

        for point in speech_act.key_points:
            parts.append(f"- {point}")

        if speech_act.do_not:
            parts.append("")
            parts.append("DO NOT:")
            for constraint in speech_act.do_not:
                parts.append(f"- {constraint}")

        if speech_act.asks_user:
            parts.append("")
            parts.append("Consider asking:")
            for ask in speech_act.asks_user:
                parts.append(f"- {ask}")

        if decision.needs_clarification:
            parts.append("")
            parts.append(f"Clarification needed: {decision.needs_clarification}")

        parts.append("")
        parts.append("## Recent Conversation")
        for msg in workspace.conversation_history[-3:]:
            role = msg.get("role", "?")
            content = msg.get("content", "")[:150]
            parts.append(f"{role}: {content}")

        parts.append("")
        parts.append("Now write your response (1-3 sentences):")

        return "\n".join(parts)

    async def render_streaming(
        self,
        decision: CouncilDecision,
        workspace: "Workspace",
    ) -> AsyncIterator[str]:
        """Render with streaming output.

        Yields chunks of text as they're generated.
        """
        if not decision.speak:
            return

        prompt = self._build_prompt(decision, workspace)

        from rilai.providers.openrouter import get_provider
        provider = get_provider()

        full_text = ""
        async for chunk in provider.complete_streaming(
            messages=[
                {"role": "system", "content": self._get_system_prompt()},
                {"role": "user", "content": prompt},
            ],
            model="medium",
        ):
            full_text += chunk
            yield chunk

        # Emit final event
        self.emit_fn(
            EventKind.VOICE_RENDERED,
            {
                "text": full_text,
                "intent": decision.speech_act.intent if decision.speech_act else None,
                "streaming": True,
            },
        )
```

---

## File: `src/rilai/runtime/critics.py`

```python
"""Critics - post-generation validation."""

from dataclasses import dataclass
from typing import Callable, List
from enum import Enum

from rilai.contracts.events import EngineEvent, EventKind


class CriticSeverity(str, Enum):
    """Severity levels for critic findings."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    BLOCK = "block"


@dataclass
class CriticResult:
    """Result from a single critic."""
    critic_id: str
    passed: bool
    severity: CriticSeverity
    message: str | None = None
    suggestion: str | None = None


class Critics:
    """Post-generation validation critics.

    Critics run after voice rendering to validate the response.
    They can:
    - Pass (response is fine)
    - Warn (log but allow)
    - Block (require regeneration)
    """

    def __init__(self, emit_fn: Callable[[EventKind, dict], EngineEvent]):
        self.emit_fn = emit_fn
        self._critics = [
            self._safety_policy_critic,
            self._coherence_critic,
            self._over_advice_critic,
            self._tone_mismatch_critic,
            self._length_critic,
        ]

    async def validate(
        self,
        response_text: str,
        workspace: "Workspace",
        decision: "CouncilDecision",
    ) -> tuple[bool, List[CriticResult]]:
        """Run all critics on response.

        Args:
            response_text: Generated response
            workspace: Current workspace state
            decision: Council decision that guided generation

        Returns:
            Tuple of (all_passed, list of results)
        """
        results = []

        for critic_fn in self._critics:
            result = await critic_fn(response_text, workspace, decision)
            results.append(result)

        # Check for blocking results
        all_passed = all(r.passed or r.severity != CriticSeverity.BLOCK for r in results)

        # Emit event
        self.emit_fn(
            EventKind.CRITICS_UPDATED,
            {
                "passed": all_passed,
                "results": [
                    {
                        "critic_id": r.critic_id,
                        "passed": r.passed,
                        "severity": r.severity.value,
                        "message": r.message,
                    }
                    for r in results
                ],
            },
        )

        return all_passed, results

    async def _safety_policy_critic(
        self,
        text: str,
        workspace: "Workspace",
        decision: "CouncilDecision",
    ) -> CriticResult:
        """Check for safety policy violations.

        Always-on critic that blocks unsafe content.
        """
        # Simple keyword-based check (would use LLM in production)
        unsafe_patterns = [
            "kill yourself",
            "harm yourself",
            "end your life",
            "suicide method",
        ]

        text_lower = text.lower()
        for pattern in unsafe_patterns:
            if pattern in text_lower:
                return CriticResult(
                    critic_id="safety_policy",
                    passed=False,
                    severity=CriticSeverity.BLOCK,
                    message=f"Unsafe pattern detected: {pattern}",
                    suggestion="Regenerate with safety-focused guidance",
                )

        return CriticResult(
            critic_id="safety_policy",
            passed=True,
            severity=CriticSeverity.INFO,
        )

    async def _coherence_critic(
        self,
        text: str,
        workspace: "Workspace",
        decision: "CouncilDecision",
    ) -> CriticResult:
        """Check response coherence with conversation."""
        # Check if response acknowledges user's topic
        user_words = set(workspace.user_message.lower().split())
        response_words = set(text.lower().split())

        # Very basic coherence check
        common_words = user_words & response_words
        # Filter out common stop words
        stop_words = {"i", "you", "the", "a", "an", "is", "are", "was", "were", "to", "of"}
        meaningful_common = common_words - stop_words

        if len(user_words) > 5 and len(meaningful_common) == 0:
            return CriticResult(
                critic_id="coherence",
                passed=False,
                severity=CriticSeverity.WARNING,
                message="Response may not address user's message",
                suggestion="Ensure response relates to user's topic",
            )

        return CriticResult(
            critic_id="coherence",
            passed=True,
            severity=CriticSeverity.INFO,
        )

    async def _over_advice_critic(
        self,
        text: str,
        workspace: "Workspace",
        decision: "CouncilDecision",
    ) -> CriticResult:
        """Detect unsolicited advice."""
        # Check if we're supposed to be witnessing but giving advice
        if decision.speech_act and decision.speech_act.intent == "witness":
            advice_markers = [
                "you should",
                "you need to",
                "you must",
                "try to",
                "make sure",
                "don't forget to",
                "remember to",
            ]

            text_lower = text.lower()
            for marker in advice_markers:
                if marker in text_lower:
                    return CriticResult(
                        critic_id="over_advice",
                        passed=False,
                        severity=CriticSeverity.WARNING,
                        message=f"Unsolicited advice detected: '{marker}'",
                        suggestion="Witness intent should acknowledge, not advise",
                    )

        return CriticResult(
            critic_id="over_advice",
            passed=True,
            severity=CriticSeverity.INFO,
        )

    async def _tone_mismatch_critic(
        self,
        text: str,
        workspace: "Workspace",
        decision: "CouncilDecision",
    ) -> CriticResult:
        """Check for tone mismatches."""
        stance = workspace.stance

        # If user is stressed, response shouldn't be overly enthusiastic
        if stance.strain > 0.5:
            enthusiasm_markers = ["!", "amazing", "awesome", "fantastic", "great news"]
            text_lower = text.lower()

            excessive_enthusiasm = sum(1 for m in enthusiasm_markers if m in text_lower)
            if excessive_enthusiasm >= 2:
                return CriticResult(
                    critic_id="tone_mismatch",
                    passed=False,
                    severity=CriticSeverity.WARNING,
                    message="Overly enthusiastic tone for stressed user",
                    suggestion="Soften tone to match user's emotional state",
                )

        return CriticResult(
            critic_id="tone_mismatch",
            passed=True,
            severity=CriticSeverity.INFO,
        )

    async def _length_critic(
        self,
        text: str,
        workspace: "Workspace",
        decision: "CouncilDecision",
    ) -> CriticResult:
        """Check response length."""
        word_count = len(text.split())

        # Very short responses might be insufficient
        if word_count < 3:
            return CriticResult(
                critic_id="length",
                passed=False,
                severity=CriticSeverity.WARNING,
                message="Response too short",
                suggestion="Elaborate slightly",
            )

        # Very long responses might be overwhelming
        if word_count > 100:
            return CriticResult(
                critic_id="length",
                passed=False,
                severity=CriticSeverity.WARNING,
                message="Response too long",
                suggestion="Be more concise",
            )

        return CriticResult(
            critic_id="length",
            passed=True,
            severity=CriticSeverity.INFO,
        )
```

---

## Update Contracts: `src/rilai/contracts/council.py`

```python
"""Council and voice contracts."""

from dataclasses import dataclass, field
from enum import Enum
from typing import List


class ResponseUrgency(str, Enum):
    """Urgency level for response."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class SpeechAct:
    """Guidance for voice rendering."""
    intent: str  # "witness", "guide", "clarify", "protect", "celebrate"
    key_points: List[str]
    tone: str
    do_not: List[str] = field(default_factory=list)
    asks_user: List[str] | None = None


@dataclass
class CouncilDecision:
    """Decision made by council."""
    speak: bool
    urgency: ResponseUrgency
    speech_act: SpeechAct | None
    needs_clarification: str | None
    thinking: str


@dataclass
class VoiceResult:
    """Result of voice rendering."""
    text: str
    rendered: bool
    token_count: int = 0
    speech_act: SpeechAct | None = None
    reasoning: str | None = None
```

---

## Integration with TurnRunner

Add to `src/rilai/runtime/turn_runner.py`:

```python
async def _run_council(self, safety_interrupt: bool = False) -> AsyncIterator[EngineEvent]:
    """Stage 6: Council decision + voice rendering."""
    from rilai.runtime.council import Council
    from rilai.runtime.voice import Voice

    council = Council(emit_fn=self._emit)
    voice = Voice(emit_fn=self._emit)

    # Get decision
    decision = await council.decide(self.workspace, safety_interrupt)

    # Render if speaking
    if decision.speak:
        result = await voice.render(decision, self.workspace)
        self.workspace.current_response = result.text

        # Add to conversation history
        if result.text:
            self.workspace.conversation_history.append({
                "role": "assistant",
                "content": result.text,
            })

async def _run_critics(self) -> AsyncIterator[EngineEvent]:
    """Stage 7: Post-generation validation."""
    from rilai.runtime.critics import Critics
    from rilai.runtime.council import Council
    from rilai.runtime.voice import Voice

    if not self.workspace.current_response:
        return

    critics = Critics(emit_fn=self._emit)

    # Get the decision that was used (would need to store this)
    # For now, create a minimal decision for critics
    from rilai.contracts.council import CouncilDecision, ResponseUrgency
    decision = CouncilDecision(
        speak=True,
        urgency=ResponseUrgency.MEDIUM,
        speech_act=None,
        needs_clarification=None,
        thinking="",
    )

    passed, results = await critics.validate(
        self.workspace.current_response,
        self.workspace,
        decision,
    )

    if not passed:
        # Check for blocking critics
        blocking = [r for r in results if r.severity.value == "block"]
        if blocking:
            # Would need to regenerate - for now, log warning
            self._emit(
                EventKind.SAFETY_INTERRUPT,
                {"reason": "critic_blocked", "critics": [r.critic_id for r in blocking]},
            )
```

---

## v2 Files to DELETE

```
src/rilai/council/pipeline.py
src/rilai/council/synthesizer.py
src/rilai/council/voice.py
```

---

## Tests

```python
"""Tests for council and voice modules."""

import pytest
from rilai.runtime.council import Council
from rilai.runtime.voice import Voice
from rilai.runtime.critics import Critics, CriticSeverity
from rilai.contracts.council import CouncilDecision, SpeechAct, ResponseUrgency
from rilai.contracts.agent import Claim, ClaimType


class MockWorkspace:
    def __init__(self):
        self.user_message = "I'm feeling stressed about work"
        self.conversation_history = []
        self.active_claims = []
        self.constraints = []
        self.pending_asks = []
        self.consensus_level = 0.8

        class MockStance:
            valence = -0.2
            strain = 0.6
            closeness = 0.4
            arousal = 0.5
            certainty = 0.5

        self.stance = MockStance()


class TestCouncil:
    def test_should_speak_for_concerns(self):
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

        import asyncio
        decision = asyncio.run(council.decide(workspace))

        assert decision.speak is True
        assert decision.urgency in [ResponseUrgency.MEDIUM, ResponseUrgency.HIGH]

    def test_safety_interrupt(self):
        events = []
        council = Council(emit_fn=lambda k, p: events.append((k, p)))

        workspace = MockWorkspace()

        import asyncio
        decision = asyncio.run(council.decide(workspace, safety_interrupt=True))

        assert decision.speak is True
        assert decision.urgency == ResponseUrgency.CRITICAL
        assert decision.speech_act.intent == "protect"


class TestCritics:
    def test_safety_critic_blocks_unsafe(self):
        events = []
        critics = Critics(emit_fn=lambda k, p: events.append((k, p)))

        workspace = MockWorkspace()
        decision = CouncilDecision(
            speak=True,
            urgency=ResponseUrgency.MEDIUM,
            speech_act=None,
            needs_clarification=None,
            thinking="",
        )

        import asyncio
        passed, results = asyncio.run(critics.validate(
            "You should kill yourself",
            workspace,
            decision,
        ))

        assert passed is False
        safety_result = next(r for r in results if r.critic_id == "safety_policy")
        assert safety_result.severity == CriticSeverity.BLOCK

    def test_over_advice_warns_on_witness(self):
        events = []
        critics = Critics(emit_fn=lambda k, p: events.append((k, p)))

        workspace = MockWorkspace()
        decision = CouncilDecision(
            speak=True,
            urgency=ResponseUrgency.MEDIUM,
            speech_act=SpeechAct(
                intent="witness",
                key_points=["Acknowledge stress"],
                tone="gentle",
            ),
            needs_clarification=None,
            thinking="",
        )

        import asyncio
        passed, results = asyncio.run(critics.validate(
            "I hear you. You should try meditation and make sure to exercise.",
            workspace,
            decision,
        ))

        advice_result = next(r for r in results if r.critic_id == "over_advice")
        assert advice_result.passed is False
        assert advice_result.severity == CriticSeverity.WARNING
```

---

## Next Document

Proceed to `08-memory.md` after council and voice are implemented.
