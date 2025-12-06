"""Base agent implementation for Rilai v2."""

import re
import time
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path

from rilai.agencies.messages import (
    AgentAssessment,
    AgentTraceData,
    RilaiEvent,
    SalienceMetadata,
    Value,
)
from rilai.config import get_config
from rilai.providers.openrouter import Message, ModelResponse, openrouter

from .protocol import PROMPTS_DIR, WorkingMemoryView


class BaseAgent(ABC):
    """Abstract base class implementing common agent functionality."""

    def __init__(
        self,
        agency_id: str,
        name: str,
        description: str,
        value: Value,
        system_prompt: str,
    ):
        self.agency_id = agency_id
        self.name = name
        self.agent_id = f"{agency_id}.{name.lower().replace(' ', '_')}"
        self.description = description
        self.value = value
        self.system_prompt = system_prompt

    @abstractmethod
    async def assess(
        self, event: RilaiEvent, context: WorkingMemoryView
    ) -> AgentAssessment:
        """Evaluate the event. Must be implemented by subclasses."""
        ...

    def _build_prompt(self, event: RilaiEvent, context: WorkingMemoryView) -> str:
        """Build the prompt for LLM assessment."""
        prompt = f"""{self.system_prompt}

## Current Context
Time: {context.current_time}
Recent conversation:
{self._format_history(context.conversation_history)}
"""
        # Add deliberation context if in multi-round mode
        if context.deliberation:
            prompt += f"""
## Deliberation Context
{context.deliberation.format_for_prompt()}
"""
        return prompt

    def _format_history(self, history: list[dict]) -> str:
        """Format conversation history for prompt."""
        if not history:
            return "(No recent messages)"
        lines = []
        for msg in history[-5:]:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")[:200]
            lines.append(f"{role}: {content}")
        return "\n".join(lines)


class LLMAgent(BaseAgent):
    """Generic LLM-powered agent that loads prompts from markdown files.

    All sub-agents use this single class with different prompt files.
    Supports thinking models with reasoning extraction.
    """

    def __init__(
        self,
        agency_id: str,
        agent_name: str,
        value: Value,
        prompt_path: Path | None = None,
    ):
        # Load prompt from markdown file
        if prompt_path is None:
            prompt_path = PROMPTS_DIR / agency_id / f"{agent_name}.md"

        if prompt_path.exists():
            system_prompt = prompt_path.read_text()
        else:
            system_prompt = f"You are the {agent_name} agent for the {agency_id} agency."

        # Convert agent_name to display name
        display_name = agent_name.replace("_", " ").title()

        super().__init__(
            agency_id=agency_id,
            name=display_name,
            description=f"{display_name} agent for {agency_id}",
            value=value,
            system_prompt=system_prompt,
        )
        self.prompt_path = prompt_path

    def _extract_thinking(self, content: str) -> tuple[str, str]:
        """Extract <thinking>...</thinking> from content.

        Returns: (thinking_content, remaining_content)
        """
        pattern = r"<thinking>(.*?)</thinking>"
        match = re.search(pattern, content, re.DOTALL)
        if match:
            thinking = match.group(1).strip()
            remaining = re.sub(pattern, "", content, flags=re.DOTALL).strip()
            return thinking, remaining
        return "", content

    def _parse_salience(self, output: str) -> tuple[str, SalienceMetadata | None]:
        """Parse [U:N C:N] metadata from output tail.

        Returns: (cleaned_output, salience_metadata)
        """
        # Check for "Quiet." pattern first
        if output.strip().lower().startswith("quiet"):
            pattern = r"\[U:(\d)\s*C:(\d)\]"
            match = re.search(pattern, output)
            if match:
                urgency = int(match.group(1))
                confidence = int(match.group(2))
                cleaned = re.sub(pattern, "", output).strip()
                return cleaned, SalienceMetadata(
                    urgency=urgency,
                    confidence=confidence,
                    raw_score=float(urgency * confidence),
                )
            return output.strip(), SalienceMetadata(urgency=0, confidence=0, raw_score=0.0)

        # Try to parse [U:N C:N] from end of output
        pattern = r"\[U:(\d)\s*C:(\d)\]\s*$"
        match = re.search(pattern, output)
        if match:
            urgency = int(match.group(1))
            confidence = int(match.group(2))
            cleaned = re.sub(pattern, "", output).strip()
            return cleaned, SalienceMetadata(
                urgency=urgency,
                confidence=confidence,
                raw_score=float(urgency * confidence),
            )

        return output, None

    async def assess(
        self, event: RilaiEvent, context: WorkingMemoryView
    ) -> AgentAssessment:
        """Evaluate the event using LLM with optional thinking model support."""
        start_time = time.time()
        config = get_config()

        # Build the prompt
        prompt = self._build_prompt(event, context)

        # Initialize trace data
        trace_data = AgentTraceData(
            system_prompt=self.system_prompt,
            full_prompt=prompt,
            event_content=event.content,
            conversation_history=list(context.conversation_history),
        )

        # Determine if we should use thinking model
        use_thinking = context.deliberation is not None and config.DELIBERATION_USE_THINKING
        reasoning_effort = config.get_reasoning_effort("agent_assess") if use_thinking else None

        try:
            response: ModelResponse = await openrouter.complete(
                messages=[
                    Message(role="system", content=prompt),
                    Message(role="user", content=f"The user said: {event.content}\n\nWhat do you observe?"),
                ],
                model=config.get_model("small", thinking=use_thinking),
                temperature=0.3,
                reasoning_effort=reasoning_effort,
                capture_request=True,
            )

            raw_output = response.content.strip()

            # Extract thinking - from reasoning field or <thinking> tags
            if response.reasoning:
                thinking = response.reasoning
                output = raw_output
            else:
                thinking, output = self._extract_thinking(raw_output)

            # Parse salience metadata from output
            output, salience = self._parse_salience(output)

            # Enrich trace data
            trace_data.llm_model = response.model
            trace_data.llm_temperature = response.request_temperature
            trace_data.llm_latency_ms = response.latency_ms
            trace_data.llm_usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "reasoning_tokens": response.usage.reasoning_tokens,
            }
            trace_data.llm_request_messages = response.request_messages
            trace_data.thinking = thinking if thinking else None
            trace_data.reasoning_tokens = response.usage.reasoning_tokens

        except Exception as e:
            output = f"Error during observation: {e}"
            salience = None

        processing_time_ms = int((time.time() - start_time) * 1000)

        return AgentAssessment(
            agent_id=self.agent_id,
            agency_id=self.agency_id,
            output=output,
            salience=salience,
            value=self.value,
            processing_time_ms=processing_time_ms,
            timestamp=datetime.now(),
            trace=trace_data,
        )
