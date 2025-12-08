"""Voice - renders council decision into natural language."""

from typing import Callable, AsyncIterator, TYPE_CHECKING

from rilai.contracts.events import EngineEvent, EventKind
from rilai.contracts.council import CouncilDecision, VoiceResult

if TYPE_CHECKING:
    from rilai.runtime.workspace import Workspace


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
        provider=None,
    ) -> VoiceResult:
        """Render decision into natural language.

        Args:
            decision: Council decision with speech act
            workspace: Current workspace state
            provider: Optional LLM provider (for testing)

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

        # Get provider
        if provider is None:
            try:
                from rilai.providers.openrouter import get_provider
                provider = get_provider()
            except Exception:
                # Fallback if provider not available
                return VoiceResult(
                    text=self._generate_fallback_response(decision, workspace),
                    rendered=True,
                    token_count=0,
                    speech_act=decision.speech_act,
                )

        # Get model from config
        from rilai.config import get_config
        from rilai.providers.openrouter import Message
        config = get_config()
        model = config.MODELS.get("medium", config.MODELS.get("small"))

        response = await provider.complete(
            messages=[
                Message(role="system", content=self._get_system_prompt()),
                Message(role="user", content=prompt),
            ],
            model=model,
        )

        text = response.content.strip()
        token_count = response.usage.total_tokens if response.usage else 0

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

    def _generate_fallback_response(
        self,
        decision: CouncilDecision,
        workspace: "Workspace",
    ) -> str:
        """Generate a simple fallback response when provider unavailable."""
        intent = decision.speech_act.intent if decision.speech_act else "witness"

        if intent == "protect":
            return "I'm here for you. Would you like to talk about what's on your mind?"
        elif intent == "witness":
            return "I hear you."
        elif intent == "guide":
            return "That's a thoughtful approach."
        elif intent == "clarify":
            return "Could you tell me more?"
        elif intent == "celebrate":
            return "That sounds wonderful!"
        else:
            return "I'm listening."

    async def render_streaming(
        self,
        decision: CouncilDecision,
        workspace: "Workspace",
        provider=None,
    ) -> AsyncIterator[str]:
        """Render with streaming output.

        Yields chunks of text as they're generated.
        """
        if not decision.speak:
            return

        prompt = self._build_prompt(decision, workspace)

        # Get provider
        if provider is None:
            try:
                from rilai.providers.openrouter import get_provider
                provider = get_provider()
            except Exception:
                # Fallback
                yield self._generate_fallback_response(decision, workspace)
                return

        # Get model from config
        from rilai.config import get_config
        from rilai.providers.openrouter import Message
        config = get_config()
        model = config.MODELS.get("medium", config.MODELS.get("small"))

        full_text = ""
        async for chunk in provider.stream(
            messages=[
                Message(role="system", content=self._get_system_prompt()),
                Message(role="user", content=prompt),
            ],
            model=model,
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
