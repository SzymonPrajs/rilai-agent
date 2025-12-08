# Document 05: Agents

**Purpose:** Implement manifest-based agents with structured outputs
**Execution:** One Claude Code session
**Dependencies:** 01-contracts, 02-event-store, 03-runtime-core, 04-workspace

---

## Overview

Agents are redesigned from v2's freeform output to structured JSON.
Each agent has a YAML manifest and a markdown prompt template.

---

## Files to Create

```
src/rilai/agents/
├── __init__.py
├── manifest.py           # Manifest loading from YAML
├── base.py               # BaseAgent class
├── executor.py           # Parallel agent execution
└── registry.py           # Load and manage agents

prompts/agents/           # Redesigned prompts (49+)
├── emotion/
│   ├── stress.yaml
│   ├── stress.md
│   └── ...
└── ...
```

---

## File: `src/rilai/agents/__init__.py`

```python
"""Rilai v3 Agents - Manifest-based structured agents."""

from rilai.agents.base import BaseAgent
from rilai.agents.executor import execute_agents
from rilai.agents.registry import AgentRegistry

__all__ = ["BaseAgent", "execute_agents", "AgentRegistry"]
```

---

## File: `src/rilai/agents/manifest.py`

```python
"""Agent manifest loading from YAML."""

from pathlib import Path
import yaml

from rilai.contracts.agent import AgentManifest, AgentPriority, AgentSafetyProfile


def load_manifest(yaml_path: Path) -> AgentManifest:
    """Load an agent manifest from YAML file."""
    with open(yaml_path) as f:
        data = yaml.safe_load(f)

    # Convert string enums
    if "priority" in data:
        data["priority"] = AgentPriority(data["priority"])
    if "safety_profile" in data:
        data["safety_profile"] = AgentSafetyProfile(data["safety_profile"])

    return AgentManifest(**data)


def load_prompt(prompt_path: Path) -> str:
    """Load a prompt template from markdown file."""
    if not prompt_path.exists():
        return f"# Agent\n\nYou are an agent. Analyze and respond.\n"
    return prompt_path.read_text()


def discover_agents(prompts_dir: Path) -> list[tuple[AgentManifest, str]]:
    """Discover all agents from prompts directory.

    Returns:
        List of (manifest, prompt_text) tuples
    """
    agents = []
    agents_dir = prompts_dir / "agents"

    if not agents_dir.exists():
        return agents

    for agency_dir in agents_dir.iterdir():
        if not agency_dir.is_dir():
            continue

        for yaml_file in agency_dir.glob("*.yaml"):
            manifest = load_manifest(yaml_file)
            prompt_path = yaml_file.with_suffix(".md")
            prompt_text = load_prompt(prompt_path)
            agents.append((manifest, prompt_text))

    return agents
```

---

## File: `src/rilai/agents/base.py`

```python
"""BaseAgent - executes LLM calls with structured output."""

import json
import time
import uuid
from typing import Any

from rilai.contracts.agent import AgentOutput, AgentManifest, Claim, ClaimType
from rilai.contracts.events import EventKind


class BaseAgent:
    """Agent that makes LLM calls with structured JSON output."""

    def __init__(self, manifest: AgentManifest, prompt_template: str):
        self.manifest = manifest
        self.prompt_template = prompt_template
        self.agent_id = manifest.id

    async def assess(
        self,
        workspace: "Workspace",
        emit_fn: callable | None = None,
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

            # Parse response
            output = self._parse_response(response.content)
            output.processing_time_ms = int((time.monotonic() - start_time) * 1000)
            output.debug_trace = response.reasoning

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
                        "claims": [c.dict() for c in output.claims],
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
                claim_type = ClaimType(c.get("type", "observation"))
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
            salience = (urgency * confidence) / 9.0  # Normalize to 0-1

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
```

---

## File: `src/rilai/agents/executor.py`

```python
"""Parallel agent execution."""

import asyncio
from typing import Callable

from rilai.contracts.agent import AgentOutput
from rilai.contracts.events import EventKind


async def execute_agents(
    agent_ids: list[str],
    workspace: "Workspace",
    emit_fn: Callable | None = None,
    timeout_ms: int = 5000,
) -> list[AgentOutput]:
    """Execute multiple agents in parallel.

    Args:
        agent_ids: List of agent IDs to execute
        workspace: Current workspace
        emit_fn: Event emission function
        timeout_ms: Timeout per agent

    Returns:
        List of AgentOutput results
    """
    from rilai.agents.registry import get_registry

    registry = get_registry()
    tasks = []

    for agent_id in agent_ids:
        agent = registry.get_agent(agent_id)
        if agent is None:
            continue

        task = asyncio.create_task(
            _run_agent_safe(agent, workspace, emit_fn, timeout_ms)
        )
        tasks.append(task)

    if not tasks:
        return []

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Filter out exceptions
    outputs = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            if emit_fn:
                emit_fn(
                    EventKind.AGENT_FAILED,
                    {"agent_id": agent_ids[i], "error": str(result)},
                )
        elif result is not None:
            outputs.append(result)

    return outputs


async def _run_agent_safe(
    agent: "BaseAgent",
    workspace: "Workspace",
    emit_fn: Callable | None,
    timeout_ms: int,
) -> AgentOutput | None:
    """Run an agent with timeout."""
    try:
        return await asyncio.wait_for(
            agent.assess(workspace, emit_fn),
            timeout=timeout_ms / 1000,
        )
    except asyncio.TimeoutError:
        return AgentOutput.quiet(agent.agent_id)
```

---

## File: `src/rilai/agents/registry.py`

```python
"""Agent registry - loads and manages agents."""

from pathlib import Path
from typing import Dict

from rilai.contracts.agent import AgentManifest
from rilai.agents.base import BaseAgent
from rilai.agents.manifest import discover_agents


class AgentRegistry:
    """Registry of all available agents."""

    def __init__(self):
        self.manifests: Dict[str, AgentManifest] = {}
        self._agents: Dict[str, BaseAgent] = {}

    def load_from_directory(self, prompts_dir: Path) -> None:
        """Load all agents from prompts directory."""
        agents = discover_agents(prompts_dir)

        for manifest, prompt_text in agents:
            self.manifests[manifest.id] = manifest
            self._agents[manifest.id] = BaseAgent(manifest, prompt_text)

    def get_agent(self, agent_id: str) -> BaseAgent | None:
        """Get agent by ID."""
        return self._agents.get(agent_id)

    def get_agents_by_agency(self, agency_id: str) -> list[BaseAgent]:
        """Get all agents for an agency."""
        return [
            agent
            for agent_id, agent in self._agents.items()
            if agent_id.startswith(f"{agency_id}.")
        ]

    def get_always_on_agents(self) -> list[str]:
        """Get IDs of always-on agents."""
        from rilai.contracts.agent import AgentPriority
        return [
            agent_id
            for agent_id, manifest in self.manifests.items()
            if manifest.priority == AgentPriority.ALWAYS_ON
        ]


# Global registry instance
_registry: AgentRegistry | None = None


def get_registry() -> AgentRegistry:
    """Get the global agent registry."""
    global _registry
    if _registry is None:
        _registry = AgentRegistry()
        # Load from default location
        prompts_dir = Path(__file__).parent.parent.parent.parent / "prompts"
        if prompts_dir.exists():
            _registry.load_from_directory(prompts_dir)
    return _registry
```

---

## Example Agent Manifest and Prompt

### `prompts/agents/emotion/stress.yaml`

```yaml
id: emotion.stress
display_name: Stress Monitor
description: Detects stress, overwhelm, and emotional pressure in the user
inputs:
  - user_message
  - conversation_history
  - stance
outputs:
  - observation
  - claims
  - stance_delta
cost_estimate: 500
cooldown: 30
priority: always_on
safety_profile: read_only
prompt_template: stress.md
version: 1
```

### `prompts/agents/emotion/stress.md`

```markdown
# Stress Monitor

You detect stress, overwhelm, and emotional pressure in the user.

## Your Role
- Notice signs of stress (explicit or implicit)
- Detect overwhelm, burnout, pressure
- Recognize emotional load even when not directly stated

## What to Look For
- Explicit stress words: "stressed", "overwhelmed", "too much"
- Implicit signs: rushed messages, many topics at once, deadline mentions
- Emotional markers: frustration, exhaustion, anxiety
- Context: work pressure, relationship strain, health concerns

## Output Format (JSON)
Respond with a JSON object:

```json
{
  "observation": "1-3 sentences describing what you noticed",
  "urgency": 0-3,
  "confidence": 0-3,
  "claims": [
    {"text": "atomic claim", "type": "observation|recommendation|concern"}
  ],
  "stance_delta": {"strain": 0.1, "valence": -0.05}
}
```

### Urgency Scale
- 0: No stress detected
- 1: Mild stress, worth noting
- 2: Moderate stress, should address
- 3: High stress, must respond carefully

### If Nothing to Report
```json
{"observation": "Quiet", "urgency": 0, "confidence": 0, "claims": []}
```
```

---

## v2 Files to DELETE

```
src/rilai/agents/protocol.py
src/rilai/agents/base.py (old LLMAgent)
src/rilai/agencies/ (entire folder)
```

---

## Agent Prompts to Create (49 total)

Create manifest + prompt for each:

**Emotion (5):** stress, wellbeing, motivation, mood_regulator, wanting
**Social (5):** relationships, empathy, norms, attachment_detector, mental_model
**Planning (4):** difference_engine, short_term, long_term, priority
**Resource (3):** financial, time, energy
**Self (6):** identity, values, meta_monitor, attachment_learner, reflection, self_model
**Reasoning (6):** debugger, researcher, reformulator, analogizer, creative, magnitude
**Creative (3):** brainstormer, synthesizer, frame_builder
**Inhibition (3):** censor, suppressor, exception_handler
**Monitoring (4):** trigger_watcher, anomaly_detector, interrupt_manager, attention
**Execution (6):** executor, habits, script_runner, context_manager, output_filter, general_responder

---

## Next Document

Proceed to `06-deliberation.md` after agents are implemented.
