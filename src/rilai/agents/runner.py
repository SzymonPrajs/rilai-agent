"""
Micro-Agent Runner

Loads agents from catalog.yaml and executes them in parallel.
Agents are "boxed" LLMs that output JSON with salience, stance deltas,
hypotheses, questions, and glimpses.
"""

import asyncio
import json
import logging
import re
from pathlib import Path

import yaml

from rilai.agents.micro import (
    MicroAgentOutput,
    MicroHypothesis,
    MicroQuestion,
    merge_stance_deltas,
    select_top_agents,
)
from rilai.core.stance import StanceVector
from rilai.providers.openrouter import OpenRouterClient

logger = logging.getLogger(__name__)


def repair_json(text: str) -> str:
    """Attempt to repair malformed JSON from LLM output.

    Common issues:
    - Trailing commas
    - Missing closing braces/brackets
    - Unterminated strings
    """
    # Remove trailing commas before } or ]
    text = re.sub(r',\s*([}\]])', r'\1', text)

    # Count braces and brackets
    open_braces = text.count('{') - text.count('}')
    open_brackets = text.count('[') - text.count(']')

    # Add missing closing brackets/braces
    text = text.rstrip()
    if open_brackets > 0:
        text += ']' * open_brackets
    if open_braces > 0:
        text += '}' * open_braces

    # Try to fix unterminated strings by finding unclosed quotes
    # This is a heuristic - look for odd number of quotes in a value position
    # Simple approach: if we have an odd number of unescaped quotes, add one at the end
    quote_count = len(re.findall(r'(?<!\\)"', text))
    if quote_count % 2 == 1:
        # Find the last key-value and try to close the string
        # Look for pattern like "key": "value without closing
        match = re.search(r'"[^"]*":\s*"[^"]*$', text)
        if match:
            text = text + '"'

    return text


def extract_json_fields(text: str) -> dict:
    """Fallback: extract key fields via regex when JSON parsing fails entirely."""
    result = {
        "salience": 0.0,
        "stance_delta": {},
        "hypotheses": [],
        "questions": [],
        "glimpse": "",
    }

    # Extract salience
    salience_match = re.search(r'"salience"\s*:\s*([\d.]+)', text)
    if salience_match:
        try:
            result["salience"] = float(salience_match.group(1))
        except ValueError:
            pass

    # Extract glimpse
    glimpse_match = re.search(r'"glimpse"\s*:\s*"([^"]*)"', text)
    if glimpse_match:
        result["glimpse"] = glimpse_match.group(1)

    return result

# Load catalog
CATALOG_PATH = Path(__file__).parent / "catalog.yaml"


def load_catalog() -> dict:
    """Load the micro-agent catalog from YAML."""
    if CATALOG_PATH.exists():
        with open(CATALOG_PATH) as f:
            return yaml.safe_load(f)
    return {"micro_agents": []}


def build_agent_prompt(agent_config: dict, sensors: dict[str, float], stance: StanceVector) -> str:
    """Build the prompt for a micro-agent from its config."""
    agent_id = agent_config["id"]
    sensitivity = agent_config.get("sensitivity", "")
    question_templates = agent_config.get("question_templates", [])
    guardrails = agent_config.get("guardrails", [])

    questions_text = "\n".join(f"  - {q}" for q in question_templates) if question_templates else "  (none)"
    guardrails_text = "\n".join(f"  - {g}" for g in guardrails) if guardrails else "  (none)"

    sensor_text = ", ".join(f"{k}={v:.2f}" for k, v in sensors.items())
    stance_text = f"valence={stance.valence:.2f}, arousal={stance.arousal:.2f}, closeness={stance.closeness:.2f}, curiosity={stance.curiosity:.2f}"

    return f"""SYSTEM — MICRO-AGENT: {agent_id.upper()}

You are a narrow perspective module. You do NOT answer the user directly.
You produce structured observations that feed into the workspace builder.

## Your Sensitivity
{sensitivity}

## Question Templates (adapt to context)
{questions_text}

## Guardrails (avoid these failure modes)
{guardrails_text}

## Current Context
Sensors: {sensor_text}
Stance: {stance_text}

## Output Rules
- JSON only
- salience: 0.0-1.0 (your relevance this turn)
- stance_delta: small nudges, max |Δ|=0.08 per dimension
- hypotheses: must cite evidence_ids if available
- questions: discriminating questions, priority 0.0-1.0
- glimpse: one short observation (optional)

If nothing arises: salience=0, empty lists, glimpse=""

## Output JSON
{{
  "agent": "{agent_id}",
  "salience": 0.0,
  "stance_delta": {{"safety": 0.0, "curiosity": 0.0, "arousal": 0.0, "closeness": 0.0}},
  "hypotheses": [{{"h": "", "p": 0.0, "evidence_ids": []}}],
  "questions": [{{"q": "", "priority": 0.0}}],
  "glimpse": ""
}}
"""


async def run_single_agent(
    provider: OpenRouterClient,
    agent_config: dict,
    user_text: str,
    sensors: dict[str, float],
    stance: StanceVector,
) -> MicroAgentOutput:
    """
    Run a single micro-agent.

    Args:
        provider: OpenRouter provider instance
        agent_config: Agent configuration from catalog
        user_text: User message to analyze
        sensors: Current sensor readings
        stance: Current stance vector

    Returns:
        MicroAgentOutput with salience, deltas, hypotheses, questions, glimpse
    """
    agent_id = agent_config["id"]
    tier = agent_config.get("tier", "tiny")

    # Check upgrade conditions
    for condition in agent_config.get("upgrade_if", []):
        # Parse conditions like "vulnerability>0.6"
        for sensor_name, threshold in _parse_condition(condition):
            if sensors.get(sensor_name, 0) > threshold:
                tier = "small"
                break

    system_prompt = build_agent_prompt(agent_config, sensors, stance)

    try:
        response = await provider.generate(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Analyze this message:\n\n{user_text}"},
            ],
            tier=tier,
            temperature=0.3,
            max_tokens=400,
        )

        # Parse JSON response
        content = response.content.strip()
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        # Try parsing JSON with repair fallback
        data = None
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            # Try repairing the JSON
            repaired = repair_json(content)
            try:
                data = json.loads(repaired)
                logger.debug(f"Agent {agent_id}: JSON repaired successfully")
            except json.JSONDecodeError:
                # Fall back to regex extraction
                data = extract_json_fields(content)
                logger.debug(f"Agent {agent_id}: Used regex fallback for JSON")

        # Build output
        hypotheses = [
            MicroHypothesis(
                text=h.get("h", ""),
                p=h.get("p", 0.0),
                evidence_ids=h.get("evidence_ids", []),
            )
            for h in data.get("hypotheses", [])
            if h.get("h")
        ]

        questions = [
            MicroQuestion(
                question=q.get("q", ""),
                priority=q.get("priority", 0.0),
            )
            for q in data.get("questions", [])
            if q.get("q")
        ]

        return MicroAgentOutput(
            agent=agent_id,
            salience=data.get("salience", 0.0),
            stance_delta=data.get("stance_delta", {}),
            hypotheses=hypotheses,
            questions=questions,
            glimpse=data.get("glimpse", ""),
            thinking=response.reasoning if hasattr(response, 'reasoning') else None,
        )

    except Exception as e:
        logger.warning(f"Agent {agent_id} failed: {e}")
        return MicroAgentOutput(agent=agent_id, salience=0.0, glimpse=f"Error: {str(e)[:30]}")


def _parse_condition(condition: str) -> list[tuple[str, float]]:
    """Parse a condition like 'vulnerability>0.6' into (sensor, threshold)."""
    results = []
    for op in [">", ">=", "<", "<="]:
        if op in condition:
            parts = condition.split(op)
            if len(parts) == 2:
                try:
                    sensor = parts[0].strip()
                    threshold = float(parts[1].strip())
                    results.append((sensor, threshold))
                except ValueError:
                    pass
            break
    return results


def should_run_agent(
    agent_config: dict,
    sensors: dict[str, float],
) -> bool:
    """Check if an agent should run based on its triggers."""
    triggers = agent_config.get("triggers", ["always"])

    if "always" in triggers:
        return True

    for trigger in triggers:
        for sensor_name, threshold in _parse_condition(trigger):
            if sensors.get(sensor_name, 0) > threshold:
                return True

    return False


async def run_agent_ensemble(
    provider: OpenRouterClient,
    user_text: str,
    sensors: dict[str, float],
    stance: StanceVector,
    agent_ids: list[str] | None = None,
) -> list[MicroAgentOutput]:
    """
    Run multiple micro-agents in parallel.

    Args:
        provider: OpenRouter provider instance
        user_text: User message to analyze
        sensors: Current sensor readings
        stance: Current stance vector
        agent_ids: Specific agents to run (default: all triggered agents)

    Returns:
        List of MicroAgentOutput from all agents
    """
    catalog = load_catalog()
    agents = catalog.get("micro_agents", [])

    # Filter to requested agents or triggered agents
    if agent_ids:
        agents = [a for a in agents if a["id"] in agent_ids]
    else:
        agents = [a for a in agents if should_run_agent(a, sensors)]

    if not agents:
        return []

    # Run all agents in parallel
    tasks = [
        run_single_agent(provider, agent, user_text, sensors, stance)
        for agent in agents
    ]

    outputs = await asyncio.gather(*tasks, return_exceptions=True)

    # Filter out exceptions
    valid_outputs = []
    for i, output in enumerate(outputs):
        if isinstance(output, Exception):
            agent_id = agents[i]["id"] if i < len(agents) else "unknown"
            valid_outputs.append(MicroAgentOutput(
                agent=agent_id,
                salience=0.0,
                glimpse=f"Error: {str(output)[:30]}",
            ))
        else:
            valid_outputs.append(output)

    return valid_outputs


class MicroAgentRunner:
    """
    High-level interface for running micro-agents.

    Usage:
        runner = MicroAgentRunner(provider)
        outputs = await runner.run(user_text, sensors, stance)
        top = runner.select_top(outputs, top_k=8)
    """

    def __init__(self, provider: OpenRouterClient):
        self.provider = provider
        self.catalog = load_catalog()

    async def run(
        self,
        user_text: str,
        sensors: dict[str, float],
        stance: StanceVector,
        agent_ids: list[str] | None = None,
    ) -> list[MicroAgentOutput]:
        """Run all triggered micro-agents."""
        return await run_agent_ensemble(
            provider=self.provider,
            user_text=user_text,
            sensors=sensors,
            stance=stance,
            agent_ids=agent_ids,
        )

    async def run_single(
        self,
        agent_id: str,
        user_text: str,
        sensors: dict[str, float],
        stance: StanceVector,
    ) -> MicroAgentOutput:
        """Run a single agent by ID."""
        agents = self.catalog.get("micro_agents", [])
        agent_config = next((a for a in agents if a["id"] == agent_id), None)

        if agent_config is None:
            return MicroAgentOutput(agent=agent_id, salience=0.0, glimpse="Agent not found")

        return await run_single_agent(
            provider=self.provider,
            agent_config=agent_config,
            user_text=user_text,
            sensors=sensors,
            stance=stance,
        )

    def select_top(
        self,
        outputs: list[MicroAgentOutput],
        top_k: int = 8,
        min_salience: float = 0.1,
    ) -> list[MicroAgentOutput]:
        """Select top agents by salience."""
        return select_top_agents(outputs, top_k, min_salience)

    def merge_deltas(self, outputs: list[MicroAgentOutput]) -> dict[str, float]:
        """Merge stance deltas using salience-weighted averaging."""
        return merge_stance_deltas(outputs)

    def get_agent_ids(self) -> list[str]:
        """Get all agent IDs from catalog."""
        return [a["id"] for a in self.catalog.get("micro_agents", [])]

    def get_agents_by_group(self, group: str) -> list[str]:
        """Get agent IDs for a specific group."""
        return [
            a["id"]
            for a in self.catalog.get("micro_agents", [])
            if a.get("group") == group
        ]
