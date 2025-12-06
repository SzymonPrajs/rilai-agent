"""Prompt loading utilities for agents."""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .protocol import PROMPTS_DIR


class PromptLoader:
    """Loads and renders agent prompts with Jinja2 templating."""

    def __init__(self, prompts_dir: Path | None = None):
        self.prompts_dir = prompts_dir or PROMPTS_DIR
        self._env: Environment | None = None

    @property
    def env(self) -> Environment:
        """Get or create the Jinja2 environment."""
        if self._env is None:
            self._env = Environment(
                loader=FileSystemLoader(str(self.prompts_dir)),
                autoescape=select_autoescape(enabled_extensions=()),
                trim_blocks=True,
                lstrip_blocks=True,
            )
        return self._env

    def load_prompt(
        self,
        agency_id: str,
        agent_name: str,
        **context: str,
    ) -> str:
        """Load and render an agent prompt.

        Args:
            agency_id: The agency ID (e.g., "emotion")
            agent_name: The agent name (e.g., "wellbeing")
            **context: Variables to pass to the template

        Returns:
            The rendered prompt string
        """
        template_path = f"{agency_id}/{agent_name}.md"

        # Try to load with includes
        try:
            template = self.env.get_template(template_path)
            return template.render(**context)
        except Exception:
            # Fall back to direct file read
            prompt_path = self.prompts_dir / template_path
            if prompt_path.exists():
                return prompt_path.read_text()
            return f"You are the {agent_name} agent for the {agency_id} agency."

    def load_shared(self, filename: str) -> str:
        """Load a shared prompt component.

        Args:
            filename: The filename in _shared/ (e.g., "role_contract.md")

        Returns:
            The prompt content
        """
        shared_path = self.prompts_dir / "_shared" / filename
        if shared_path.exists():
            return shared_path.read_text()
        return ""

    def list_agency_prompts(self, agency_id: str) -> list[str]:
        """List all prompt files for an agency.

        Returns:
            List of agent names with prompts
        """
        agency_dir = self.prompts_dir / agency_id
        if not agency_dir.exists():
            return []

        return [
            p.stem
            for p in agency_dir.glob("*.md")
            if not p.stem.startswith("_")
        ]


# Global prompt loader instance
prompt_loader = PromptLoader()
