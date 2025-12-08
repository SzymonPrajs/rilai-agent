"""BaseAgent - executes LLM calls with structured output."""

import json
import time
import uuid
from typing import Any, Callable, TYPE_CHECKING

from rilai.contracts.agent import AgentOutput, AgentManifest, Claim, ClaimType
from rilai.contracts.events import EventKind

if TYPE_CHECKING:
    from rilai.runtime.workspace import Workspace


class BaseAgent:
    """Agent that makes LLM calls with structured JSON output."""

    def __init__(self, manifest: AgentManifest, prompt_template: str):
        self.manifest = manifest
        self.prompt_template = prompt_template
        self.agent_id = manifest.id

    async def assess(
        self,
        workspace: "Workspace",
        emit_fn: Callable | None = None,
    ) -> AgentOutput:
        """Run assessment and return structured output.

        Args:
            workspace: Current workspace state
            emit_fn: Optional function to emit events

        Returns:
            Structured AgentOutput
        """
        start_time = time.monotonic()

        # Emit start event
        if emit_fn:
            emit_fn(EventKind.AGENT_STARTED, {"agent_id": self.agent_id})

        try:
            # Build prompt
            prompt = self._build_prompt(workspace)

            # Make LLM call
            response = await self._call_llm(prompt)

            # Parse response
            output = self._parse_response(response)
            output.processing_time_ms = int((time.monotonic() - start_time) * 1000)

            # Emit completion event
            if emit_fn:
                emit_fn(
                    EventKind.AGENT_COMPLETED,
                    {
                        "agent_id": self.agent_id,
                        "observation": output.observation,
                        "salience": output.salience,
                        "urgency": output.urgency,
                        "confidence": output.confidence,
                        "claims": [c.model_dump() for c in output.claims],
                        "processing_time_ms": output.processing_time_ms,
                    },
                )

            return output

        except Exception as e:
            if emit_fn:
                emit_fn(
                    EventKind.AGENT_FAILED,
                    {"agent_id": self.agent_id, "error": str(e)},
                )
            return AgentOutput.quiet(self.agent_id)

    async def _call_llm(self, prompt: str) -> str:
        """Make LLM call. Can be overridden for testing."""
        try:
            from rilai.providers.openrouter import get_provider
            provider = get_provider()

            response = await provider.complete(
                messages=[
                    {"role": "system", "content": self.prompt_template},
                    {"role": "user", "content": prompt},
                ],
                model="small",
                json_output=True,
            )
            return response.content
        except ImportError:
            # Fallback for testing without provider
            return '{"observation": "Quiet", "urgency": 0, "confidence": 0, "claims": []}'

    def _build_prompt(self, workspace: "Workspace") -> str:
        """Build the user prompt for the LLM."""
        return f"""## Current Context

{workspace.to_prompt_context()}

## Task

Analyze from your perspective ({self.manifest.display_name}) and respond with structured JSON.

Output format:
{{
  "observation": "1-3 sentences of your assessment",
  "urgency": 0-3,
  "confidence": 0-3,
  "claims": [
    {{"text": "atomic claim", "type": "observation|recommendation|concern|question"}}
  ],
  "stance_delta": {{"dimension": delta}} // optional
}}

If nothing to report: {{"observation": "Quiet", "urgency": 0, "confidence": 0, "claims": []}}
"""

    def _parse_response(self, content: str) -> AgentOutput:
        """Parse LLM response into AgentOutput."""
        try:
            # Try to extract JSON from response
            data = self._extract_json(content)

            # Convert claims
            claims = []
            for c in data.get("claims", []):
                claim_type_str = c.get("type", "observation")
                try:
                    claim_type = ClaimType(claim_type_str)
                except ValueError:
                    claim_type = ClaimType.OBSERVATION

                claims.append(
                    Claim(
                        id=str(uuid.uuid4())[:8],
                        text=c.get("text", ""),
                        type=claim_type,
                        source_agent=self.agent_id,
                        urgency=data.get("urgency", 0),
                        confidence=data.get("confidence", 0),
                    )
                )

            # Calculate salience
            urgency = data.get("urgency", 0)
            confidence = data.get("confidence", 0)
            salience = (urgency * confidence) / 9.0 if urgency + confidence > 0 else 0.0

            return AgentOutput(
                agent_id=self.agent_id,
                observation=data.get("observation", ""),
                salience=salience,
                urgency=urgency,
                confidence=confidence,
                claims=claims,
                stance_delta=data.get("stance_delta"),
                workspace_patch=data.get("workspace_patch"),
            )

        except Exception:
            return AgentOutput.quiet(self.agent_id)

    def _extract_json(self, content: str) -> dict:
        """Extract JSON from response (handles markdown code blocks)."""
        import re

        # Try direct parse
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        # Try extracting from code block
        match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
        if match:
            return json.loads(match.group(1))

        # Try finding first { to last }
        start = content.find('{')
        end = content.rfind('}')
        if start != -1 and end != -1:
            return json.loads(content[start:end+1])

        raise ValueError("No JSON found in response")
