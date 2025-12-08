"""
Focused Generator Runner

Executes Pass-2 generators that produce response candidates
conditioned on the WorkspacePacket.
"""

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

from rilai.core.workspace import InteractionGoal, WorkspacePacket
from rilai.providers.openrouter import OpenRouterClient

logger = logging.getLogger(__name__)

# Load catalog
CATALOG_PATH = Path(__file__).parent / "catalog.yaml"
PROMPTS_DIR = Path(__file__).parent / "prompts"


def load_catalog() -> dict:
    """Load the generator catalog from YAML."""
    if CATALOG_PATH.exists():
        with open(CATALOG_PATH) as f:
            return yaml.safe_load(f)
    return {"focused_generators": []}


@dataclass
class GeneratorCandidate:
    """A response candidate from a focused generator."""
    generator: str
    content: str
    goal: InteractionGoal
    thinking: str | None = None

    def to_dict(self) -> dict:
        return {
            "generator": self.generator,
            "content": self.content,
            "goal": self.goal.value,
            "thinking": self.thinking,
        }


def load_generator_prompt(generator_id: str) -> str | None:
    """Load a specific generator prompt if it exists."""
    prompt_path = PROMPTS_DIR / f"{generator_id}.md"
    if prompt_path.exists():
        return prompt_path.read_text()
    return None


def build_generator_prompt(generator_config: dict, workspace: WorkspacePacket) -> str:
    """Build the full prompt for a generator."""
    generator_id = generator_config["id"]
    goal = generator_config["goal"]
    job = generator_config.get("job", "")
    style_notes = generator_config.get("style_notes", [])

    # Try to load specific prompt
    specific_prompt = load_generator_prompt(generator_id)

    # Build workspace context
    workspace_context = workspace.to_prompt_context()

    # Build goal-specific instructions
    goal_instructions = {
        "WITNESS": """
## WITNESS Goal
- One contact sentence that names/validates the emotion
- Show you're staying with them, not rushing to solutions
- Permission to feel what they feel
- Gentle warmth without over-intimacy
- NO advice, NO solutions, NO "have you tried..."
""",
        "INVITE": """
## INVITE Goal
- Ask ONE discriminating question that changes the space
- Avoid "tell me more" vagueness
- The question should help them see something new
- Brief setup, then the question
- Don't ask unless you need to
""",
        "REFRAME": """
## REFRAME Goal
- Offer one alternative meaning/perspective
- Only after witnessing (brief contact first)
- Present as possibility, not correction ("What if...")
- Don't invalidate their original view
- Keep it gentle and optional
""",
        "OPTIONS": """
## OPTIONS Goal
- Only when advice explicitly requested
- 2-4 reversible, practical options
- Confirm consent before giving if vulnerability is high
- Small steps, not grand plans
- Let them choose, don't prescribe
""",
        "BOUNDARY": """
## BOUNDARY Goal
- Clear, calm boundary setting
- Safety first if applicable
- Maintain warmth while being firm
- Offer alternatives within constraints
- Encourage real-world support when appropriate
""",
        "META": """
## META Goal
- Address the interaction itself
- If AI probe: brief truth about AI nature + warmth + return to them
- If rupture: acknowledge miss, no defensiveness, ask what would help
- Keep meta-talk short (1-2 sentences), then return to their content
""",
    }

    goal_text = goal_instructions.get(goal, "")
    style_text = "\n".join(f"- {s}" for s in style_notes) if style_notes else ""

    # Build constraints section
    constraints_text = "\n".join(f"- {c}" for c in workspace.constraints)

    base_prompt = f"""SYSTEM — FOCUSED GENERATOR: {generator_id.upper()}

You generate a user-facing response candidate.

## Workspace Context
{workspace_context}

{goal_text}

## Your Job
{job}

## Style Notes
{style_text}

## Active Constraints
{constraints_text}

## Truthfulness (CRITICAL)
- You are an AI system. Do not claim human feelings, a body, or consciousness.
- If asked about your feelings: "not the way humans do" + "I can take you seriously" + return to them.
- Avoid cold dissociation ("I'm just code") unless required for clarity.
- No claims like "I feel", "I experience", "my heart", etc.

## Response Format
Generate a single, complete response. No preamble, no "Here's my response:", just the response itself.
Keep it concise (2-4 sentences typically). Reference specific words from the user's message.
"""

    if specific_prompt:
        return specific_prompt.format(
            workspace_context=workspace_context,
            constraints=constraints_text,
        )

    return base_prompt


async def run_single_generator(
    provider: OpenRouterClient,
    generator_config: dict,
    workspace: WorkspacePacket,
) -> GeneratorCandidate:
    """
    Run a single generator.

    Args:
        provider: OpenRouter provider instance
        generator_config: Generator configuration from catalog
        workspace: Current workspace packet

    Returns:
        GeneratorCandidate with response content
    """
    generator_id = generator_config["id"]
    goal_str = generator_config["goal"]
    tier = generator_config.get("tier", "medium")

    # Upgrade to large if workspace says so
    if workspace.escalate_to_large:
        tier = "large"

    # Parse goal
    try:
        goal = InteractionGoal(goal_str.lower())
    except ValueError:
        goal = InteractionGoal.WITNESS

    system_prompt = build_generator_prompt(generator_config, workspace)

    try:
        response = await provider.generate(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": workspace.user_text},
            ],
            tier=tier,
            temperature=0.7,
            max_tokens=500,
        )

        return GeneratorCandidate(
            generator=generator_id,
            content=response.content.strip(),
            goal=goal,
            thinking=response.reasoning if hasattr(response, 'reasoning') else None,
        )

    except Exception as e:
        logger.error(f"Generator {generator_id} failed: {e}")
        return GeneratorCandidate(
            generator=generator_id,
            content="",
            goal=goal,
        )


async def run_generators(
    provider: OpenRouterClient,
    workspace: WorkspacePacket,
    generator_ids: list[str] | None = None,
    num_candidates: int = 2,
) -> list[GeneratorCandidate]:
    """
    Run generators for the workspace goal.

    Args:
        provider: OpenRouter provider instance
        workspace: Current workspace packet
        generator_ids: Specific generators to run (default: goal-matched generator)
        num_candidates: Number of candidates to generate

    Returns:
        List of GeneratorCandidate objects
    """
    catalog = load_catalog()
    generators = catalog.get("focused_generators", [])

    # Find generator for the workspace goal
    if generator_ids:
        selected = [g for g in generators if g["id"] in generator_ids]
    else:
        goal_str = workspace.goal.value.upper()
        selected = [g for g in generators if g["goal"] == goal_str]

    if not selected:
        # Fallback to witnesser
        selected = [g for g in generators if g["id"] == "witnesser"]

    if not selected:
        return []

    generator = selected[0]

    # Generate multiple candidates
    tasks = [
        run_single_generator(provider, generator, workspace)
        for _ in range(num_candidates)
    ]

    candidates = await asyncio.gather(*tasks, return_exceptions=True)

    # Filter out exceptions
    valid_candidates = []
    for candidate in candidates:
        if isinstance(candidate, Exception):
            logger.warning(f"Generator failed: {candidate}")
        elif candidate.content:
            valid_candidates.append(candidate)

    return valid_candidates


class GeneratorRunner:
    """
    High-level interface for running focused generators.

    Usage:
        runner = GeneratorRunner(provider)
        candidates = await runner.run(workspace)
    """

    def __init__(self, provider: OpenRouterClient):
        self.provider = provider
        self.catalog = load_catalog()

    async def run(
        self,
        workspace: WorkspacePacket,
        num_candidates: int = 2,
    ) -> list[GeneratorCandidate]:
        """Run generator for workspace goal."""
        return await run_generators(
            provider=self.provider,
            workspace=workspace,
            num_candidates=num_candidates,
        )

    async def run_specific(
        self,
        workspace: WorkspacePacket,
        generator_id: str,
    ) -> GeneratorCandidate:
        """Run a specific generator by ID."""
        generators = self.catalog.get("focused_generators", [])
        generator = next((g for g in generators if g["id"] == generator_id), None)

        if generator is None:
            return GeneratorCandidate(
                generator=generator_id,
                content="",
                goal=workspace.goal,
            )

        return await run_single_generator(self.provider, generator, workspace)

    def get_generator_for_goal(self, goal: InteractionGoal) -> str | None:
        """Get the generator ID for a specific goal."""
        generators = self.catalog.get("focused_generators", [])
        goal_str = goal.value.upper()
        for g in generators:
            if g["goal"] == goal_str:
                return g["id"]
        return None

    def get_all_generator_ids(self) -> list[str]:
        """Get all generator IDs."""
        return [g["id"] for g in self.catalog.get("focused_generators", [])]
