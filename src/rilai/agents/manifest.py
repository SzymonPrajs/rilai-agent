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
        return "# Agent\n\nYou are an agent. Analyze and respond.\n"
    return prompt_path.read_text()


def discover_agents(prompts_dir: Path | str) -> list[tuple[AgentManifest, str]]:
    """Discover all agents from prompts directory.

    Args:
        prompts_dir: Directory containing agents/ subdirectory or the agents/ dir itself

    Returns:
        List of (manifest, prompt_text) tuples
    """
    agents = []
    prompts_dir = Path(prompts_dir)

    # Check if this is the agents dir or parent of it
    if prompts_dir.name == "agents":
        agents_dir = prompts_dir
    else:
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
