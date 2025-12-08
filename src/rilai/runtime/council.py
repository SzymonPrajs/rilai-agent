"""Council - makes high-level decisions about response."""

from typing import Callable, TYPE_CHECKING

from rilai.contracts.events import EngineEvent, EventKind
from rilai.contracts.council import CouncilDecision, SpeechAct, ResponseUrgency
from rilai.contracts.agent import Claim, ClaimType

if TYPE_CHECKING:
    from rilai.runtime.workspace import Workspace


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
        should_speak = await self._should_speak(workspace, claims_analysis)

        if not should_speak:
            decision = CouncilDecision(
                speak=False,
                urgency="low",
                speech_act=SpeechAct(),
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
            urgency=urgency.value,
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
            urgency=ResponseUrgency.CRITICAL.value,
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

    async def _should_speak(self, workspace: "Workspace", analysis: dict) -> bool:
        """Determine if we should respond using LLM-based engagement detection."""
        import logging
        logger = logging.getLogger(__name__)

        # Always respond if there are concerns or questions from agents
        if analysis["concerns"] or analysis["questions"]:
            return True

        # Respond if high urgency detected
        if analysis["max_urgency"] >= 2:
            return True

        # Respond if there are recommendations
        if analysis["recommendations"]:
            return True

        # Use LLM to detect if message warrants a response
        # This replaces hardcoded keyword matching with semantic understanding
        user_msg = workspace.user_message.strip()

        try:
            from rilai.providers.openrouter import get_provider, Message
            from rilai.config import get_config

            provider = get_provider()
            config = get_config()
            model = config.MODELS.get("tiny", config.MODELS.get("small"))

            response = await provider.complete(
                messages=[
                    Message(
                        role="system",
                        content="You are a conversation analyzer. Answer YES or NO only.",
                    ),
                    Message(
                        role="user",
                        content=f"""Does this message expect, invite, or warrant a conversational response?
Consider: Is it a question? A greeting? An invitation to chat? A request? Something that would be rude to ignore?

Message: "{user_msg}"

Answer YES or NO:""",
                    ),
                ],
                model=model,
                max_tokens=10,
            )

            answer = response.content.strip().upper()
            if "YES" in answer:
                return True
            elif "NO" in answer:
                return False
            # LLM gave unclear answer - fall through to pattern matching

        except Exception as e:
            logger.warning(f"Engagement detector failed: {e}, using pattern fallback")

        # Pattern-based fallback when LLM unavailable or unclear
        # Check for questions (ends with ?)
        if user_msg.endswith("?"):
            return True
        # Check for greetings
        greeting_words = ["hi", "hello", "hey", "morning", "evening", "rilai"]
        if any(word in user_msg.lower().split() for word in greeting_words):
            return True

        # Final fallback: respond if any agent found something noteworthy
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
                "urgency": decision.urgency,
                "intent": decision.speech_act.intent if decision.speech_act else None,
                "thinking": decision.thinking,
            },
        )
