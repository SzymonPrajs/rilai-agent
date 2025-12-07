"""Voice renderer for transforming speech acts into natural language."""

import time
from datetime import datetime
from pathlib import Path

from rilai.agents.protocol import PROMPTS_DIR
from rilai.config import get_config
from rilai.providers.openrouter import Message, openrouter

from .messages import SelfModelView, SpeechAct, VoiceResult


class Voice:
    """Renders structured speech acts into natural language.

    This is a pure transformation layer - it adds no new claims or decisions.
    """

    def __init__(self, prompt_path: Path | None = None):
        self.prompt_path = prompt_path or PROMPTS_DIR / "council" / "voice.md"
        self._load_prompt()

    def _load_prompt(self) -> None:
        """Load the voice prompt from file."""
        if self.prompt_path.exists():
            self.system_prompt = self.prompt_path.read_text()
        else:
            self.system_prompt = (
                "You transform structured speech intents into natural language. "
                "Do not add new information. Do not make new decisions. "
                "Simply express the given intent naturally."
            )

    async def render(
        self,
        speech_act: SpeechAct,
        self_model: SelfModelView,
        last_user_message: str,
    ) -> VoiceResult:
        """Render a speech act into natural language.

        Args:
            speech_act: The structured intent to render
            self_model: Identity/personality context
            last_user_message: The message being responded to

        Returns:
            VoiceResult with the final message text
        """
        start_time = time.time()
        config = get_config()

        prompt = self._build_render_prompt(speech_act, self_model, last_user_message)

        try:
            response = await openrouter.complete(
                messages=[
                    Message(role="system", content=prompt),
                    Message(role="user", content="Render this speech act."),
                ],
                model=config.get_model("small"),
            )
            message = response.content.strip()

            # Clean up artifacts
            if message.startswith('"') and message.endswith('"'):
                message = message[1:-1]

        except Exception:
            message = self._fallback_render(speech_act)

        processing_time_ms = int((time.time() - start_time) * 1000)

        return VoiceResult(
            message=message,
            processing_time_ms=processing_time_ms,
            timestamp=datetime.now(),
        )

    def _build_render_prompt(
        self,
        speech_act: SpeechAct,
        self_model: SelfModelView,
        last_user_message: str,
    ) -> str:
        """Build the rendering prompt."""
        do_not_section = ""
        if speech_act.do_not:
            do_not_section = "\n## Do NOT\n" + "\n".join(
                f"- {x}" for x in speech_act.do_not
            )

        key_points_formatted = "\n".join(f"- {point}" for point in speech_act.key_points)
        self_model_section = self_model.to_prompt_section()

        return f"""{self.system_prompt}

## Self Model (Who I Am)

{self_model_section}

## Speech Act to Render

Intent: {speech_act.intent}
Tone: {speech_act.tone}

Key points to include:
{key_points_formatted}
{do_not_section}

## Context

The user said: "{last_user_message[:500]}"

## Your Task

Transform the key points into natural speech that:
1. Matches the specified intent ({speech_act.intent})
2. Uses the specified tone ({speech_act.tone})
3. Includes ALL key points
4. Respects the do_not constraints
5. Sounds natural, not like a list

Output ONLY the final message text. No JSON. No explanation."""

    def _fallback_render(self, speech_act: SpeechAct) -> str:
        """Fallback rendering when LLM fails."""
        intros = {
            "reflect": "I'm noticing that",
            "nudge": "You might consider",
            "warn": "I want to flag that",
            "ask": "I'm curious about",
            "summarize": "Taking all of this together,",
        }

        intro = intros.get(speech_act.intent, "")
        points = " ".join(speech_act.key_points)

        if intro:
            return f"{intro} {points}"
        return points
