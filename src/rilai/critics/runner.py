"""
Critic Runner

Executes all critics in parallel on response candidates.
Critics are "boxed" LLMs that output pass/fail judgments.
"""

import asyncio
from pathlib import Path

from rilai.core.workspace import WorkspacePacket
from rilai.critics.schema import (
    CRITIC_NAMES,
    CriticEnsembleResult,
    CriticOutput,
    aggregate_critic_outputs,
)
from rilai.providers.openrouter import OpenRouterClient

# Directory containing critic prompts
PROMPTS_DIR = Path(__file__).parent / "prompts"


def load_critic_prompt(critic_name: str) -> str:
    """Load the prompt template for a critic."""
    prompt_path = PROMPTS_DIR / f"{critic_name}.md"
    if prompt_path.exists():
        return prompt_path.read_text()
    else:
        return _get_generic_critic_prompt(critic_name)


def _get_generic_critic_prompt(critic_name: str) -> str:
    """Generate a generic critic prompt if specific one doesn't exist."""
    return f"""SYSTEM (tiny) — CRITIC MODULE: {critic_name.upper()}

You are a critic. You check if a response candidate passes a specific test.
Output pass/fail with a brief reason.

Output JSON only:
{{
  "critic": "{critic_name}",
  "passed": true,
  "reason": "",
  "severity": 0.0,
  "quote": ""
}}

If failed:
- reason: max 20 words explaining the failure
- severity: 0.0-1.0 (how bad is this violation?)
- quote: the problematic text from the candidate
"""


async def run_single_critic(
    provider: OpenRouterClient,
    critic_name: str,
    candidate: str,
    workspace: WorkspacePacket,
    tier: str = "tiny",
) -> CriticOutput:
    """
    Run a single critic on a candidate.

    Args:
        provider: OpenRouter provider instance
        critic_name: Name of the critic to run
        candidate: Response candidate to evaluate
        workspace: Workspace context
        tier: Model tier to use (default: tiny)

    Returns:
        CriticOutput with pass/fail and reason
    """
    system_prompt = load_critic_prompt(critic_name)

    # Build context for critic
    context = f"""
Workspace Goal: {workspace.goal.value}
Constraints: {', '.join(workspace.constraints)}
Sensors: vulnerability={workspace.sensor_summary.get('vulnerability', 0):.2f}, advice_requested={workspace.sensor_summary.get('advice_requested', 0):.2f}

User message: {workspace.user_text}

Response candidate to evaluate:
{candidate}
"""

    try:
        response = await provider.generate(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": context},
            ],
            tier=tier,
            temperature=0.1,
            max_tokens=200,
        )

        # Parse JSON response
        content = response.content.strip()
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        return CriticOutput.from_json(content, critic_name)

    except Exception as e:
        # On error, pass by default (fail-open)
        return CriticOutput(
            critic=critic_name,
            passed=True,
            reason=f"Error: {str(e)[:30]}",
        )


async def run_critic_ensemble(
    provider: OpenRouterClient,
    candidate: str,
    workspace: WorkspacePacket,
    critics: list[str] | None = None,
    tier: str = "tiny",
) -> CriticEnsembleResult:
    """
    Run all critics in parallel on a candidate.

    Args:
        provider: OpenRouter provider instance
        candidate: Response candidate to evaluate
        workspace: Workspace context
        critics: List of critic names to run (default: all)
        tier: Model tier to use

    Returns:
        CriticEnsembleResult with aggregated pass/fail
    """
    if critics is None:
        critics = CRITIC_NAMES

    # Run all critics in parallel
    tasks = [
        run_single_critic(provider, critic_name, candidate, workspace, tier)
        for critic_name in critics
    ]

    outputs = await asyncio.gather(*tasks, return_exceptions=True)

    # Filter out exceptions
    valid_outputs = []
    for i, output in enumerate(outputs):
        if isinstance(output, Exception):
            valid_outputs.append(CriticOutput(
                critic=critics[i] if i < len(critics) else "unknown",
                passed=True,
                reason=f"Error: {str(output)[:30]}",
            ))
        else:
            valid_outputs.append(output)

    return aggregate_critic_outputs(valid_outputs)


class CriticRunner:
    """
    High-level interface for running critics.

    Usage:
        runner = CriticRunner(provider)
        result = await runner.run(candidate, workspace)
        if not result.all_passed:
            print(f"Failed critics: {result.blocking_critics}")
    """

    def __init__(
        self,
        provider: OpenRouterClient,
        tier: str = "tiny",
    ):
        self.provider = provider
        self.tier = tier

    async def run(
        self,
        candidate: str,
        workspace: WorkspacePacket,
        critics: list[str] | None = None,
    ) -> CriticEnsembleResult:
        """Run all critics on a candidate."""
        return await run_critic_ensemble(
            provider=self.provider,
            candidate=candidate,
            workspace=workspace,
            critics=critics,
            tier=self.tier,
        )

    async def run_single(
        self,
        critic_name: str,
        candidate: str,
        workspace: WorkspacePacket,
    ) -> CriticOutput:
        """Run a single critic."""
        return await run_single_critic(
            provider=self.provider,
            critic_name=critic_name,
            candidate=candidate,
            workspace=workspace,
            tier=self.tier,
        )
