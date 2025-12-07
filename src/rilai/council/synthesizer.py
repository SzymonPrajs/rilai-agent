"""LLM-based synthesizer for council deliberation."""

import json
import re
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from rilai.agents.protocol import PROMPTS_DIR, WorkingMemoryView
from rilai.config import get_config
from rilai.providers.openrouter import Message, openrouter

from .collector import CollectedAssessments
from .messages import CouncilDecision, SpeechAct


class Synthesizer:
    """LLM-based synthesizer that integrates all agency perspectives.

    The council is the only place where structured output parsing happens.
    It decides: should I speak? what should I say?
    """

    def __init__(self, prompt_path: Path | None = None):
        self.prompt_path = prompt_path or PROMPTS_DIR / "council" / "synthesizer.md"
        self._load_prompt()

    def _load_prompt(self) -> None:
        """Load the system prompt from file."""
        if self.prompt_path.exists():
            self.system_prompt = self.prompt_path.read_text()
        else:
            self.system_prompt = (
                "You are the inner voice - the part that speaks after all parts have spoken. "
                "Integrate perspectives from multiple agencies into a unified response. "
                "You decide whether to speak or stay quiet."
            )

    async def synthesize(
        self,
        user_input: str,
        collected: CollectedAssessments,
        context: WorkingMemoryView,
        deliberation_rounds: int = 0,
        final_consensus: float = 0.0,
    ) -> CouncilDecision:
        """Synthesize a decision from all agency assessments.

        Args:
            user_input: The original user input
            collected: Organized assessments from all agencies
            context: Working memory context
            deliberation_rounds: Number of deliberation rounds completed
            final_consensus: Final consensus level from deliberation

        Returns:
            CouncilDecision with speak/urgency/speech_act
        """
        start_time = time.time()
        config = get_config()

        prompt = self._build_synthesis_prompt(user_input, collected, context)

        # Use thinking model for council synthesis
        reasoning_effort = config.get_reasoning_effort("council_synthesis")

        thinking = ""
        try:
            response = await openrouter.complete(
                messages=[
                    Message(role="system", content=prompt),
                    Message(role="user", content="What is your decision?"),
                ],
                model=config.get_model("small"),
                temperature=0.7,
                reasoning_effort=reasoning_effort,
                capture_request=True,
            )

            # Extract thinking from reasoning field or tags
            if response.reasoning:
                thinking = response.reasoning
                content = response.content
            else:
                thinking, content = self._extract_thinking(response.content)

            # Parse the response
            result_data = self._parse_response(content)

        except Exception as e:
            result_data = {
                "speak": True,
                "urgency": "low",
                "speech_act": {
                    "intent": "reflect",
                    "key_points": ["I'm having trouble formulating a response right now."],
                    "tone": "warm",
                    "do_not": [],
                },
                "internal_state": f"Error during synthesis: {e}",
            }

        processing_time_ms = int((time.time() - start_time) * 1000)

        # Parse speech_act
        speech_act = None
        if result_data.get("speak", True) and "speech_act" in result_data:
            speech_act = SpeechAct.from_dict(result_data["speech_act"])

        return CouncilDecision(
            speak=result_data.get("speak", True),
            urgency=result_data.get("urgency", "low"),
            speech_act=speech_act,
            message="",  # Populated by Voice
            internal_state=result_data.get("internal_state", ""),
            thinking=thinking,
            processing_time_ms=processing_time_ms,
            timestamp=datetime.now(),
            deliberation_rounds=deliberation_rounds,
            final_consensus=final_consensus,
        )

    def _build_synthesis_prompt(
        self,
        user_input: str,
        collected: CollectedAssessments,
        context: WorkingMemoryView,
    ) -> str:
        """Build the full synthesis prompt."""
        agent_observations = self._format_agent_observations(collected)
        history = self._format_history(context.conversation_history)

        return f"""{self.system_prompt}

## Agent Observations

{agent_observations}

## Conversation Context

Recent messages:
{history}

## Current Input

The user said: {user_input}

## Your Decision

First, show your thinking in <thinking> tags.
Then respond with JSON:

<thinking>your deliberation here</thinking>
{{
  "speak": true/false,
  "urgency": "low/medium/high/critical",
  "speech_act": {{
    "intent": "reflect/nudge/warn/ask/summarize",
    "key_points": ["point 1", "point 2"],
    "tone": "warm/direct/playful/solemn",
    "do_not": ["constraint 1"]
  }},
  "internal_state": "brief summary"
}}

If speak=false, omit the speech_act field."""

    def _format_agent_observations(self, collected: CollectedAssessments) -> str:
        """Format agent observations for the prompt."""
        if not collected.all_agents:
            return "(No agent observations available)"

        lines = []
        for agent in collected.all_agents:
            agent_name = (
                agent.agent_id.split(".")[-1] if "." in agent.agent_id else agent.agent_id
            )
            lines.append(f"- **{agent.agency_id}/{agent_name}**: {agent.output}")

        return "\n".join(lines)

    def _format_history(self, history: list[dict]) -> str:
        """Format conversation history."""
        if not history:
            return "(No recent messages)"

        lines = []
        for msg in history[-5:]:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")[:300]
            lines.append(f"{role}: {content}")

        return "\n".join(lines)

    def _extract_thinking(self, content: str) -> tuple[str, str]:
        """Extract <thinking>...</thinking> from content."""
        pattern = r"<thinking>(.*?)</thinking>"
        match = re.search(pattern, content, re.DOTALL)
        if match:
            thinking = match.group(1).strip()
            remaining = re.sub(pattern, "", content, flags=re.DOTALL).strip()
            return thinking, remaining
        return "", content

    def _parse_response(self, content: str) -> dict:
        """Parse JSON from LLM response."""
        content = content.strip()

        # Strip markdown code blocks
        if content.startswith("```json"):
            content = content[7:]
        elif content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            # Try to find JSON
            start = content.find("{")
            end = content.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    return json.loads(content[start:end])
                except json.JSONDecodeError:
                    pass

            # Fallback
            return {
                "speak": True,
                "urgency": "low",
                "speech_act": {
                    "intent": "reflect",
                    "key_points": [
                        content[:500] if content else "Unable to formulate response."
                    ],
                    "tone": "warm",
                    "do_not": [],
                },
                "internal_state": "Failed to parse JSON",
            }
