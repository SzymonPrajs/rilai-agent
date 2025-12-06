"""Configuration loader for Rilai v2.

Loads config.py from the project root, falling back to defaults.
"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from . import defaults


class Config:
    """Configuration object with attribute access."""

    def __init__(self) -> None:
        # Start with defaults
        for key in defaults.CONFIG_KEYS:
            setattr(self, key, getattr(defaults, key))

        # Load user config if available
        self._load_user_config()

    def _load_user_config(self) -> None:
        """Load config.py from project root."""
        # Find config.py - look in current dir and parents
        config_path = self._find_config_file()

        if config_path is None:
            return

        # Load the module
        user_config = self._load_module_from_path(config_path)

        # Override defaults with user values
        for key in defaults.CONFIG_KEYS:
            if hasattr(user_config, key):
                setattr(self, key, getattr(user_config, key))

    def _find_config_file(self) -> Path | None:
        """Find config.py in current dir or parents."""
        # Start from current working directory
        current = Path.cwd()

        # Also check where the package is installed
        package_root = Path(__file__).parent.parent.parent.parent

        search_paths = [current, package_root]

        # Walk up from cwd
        while current != current.parent:
            search_paths.append(current)
            current = current.parent

        for path in search_paths:
            config_path = path / "config.py"
            if config_path.exists():
                return config_path

        return None

    def _load_module_from_path(self, path: Path) -> ModuleType:
        """Load a Python module from a file path."""
        spec = importlib.util.spec_from_file_location("user_config", path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Could not load config from {path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules["user_config"] = module
        spec.loader.exec_module(module)
        return module

    def get(self, key: str, default: Any = None) -> Any:
        """Get config value with optional default."""
        return getattr(self, key, default)

    def get_model(self, tier: str, thinking: bool = False) -> str:
        """Get model name for a tier.

        Args:
            tier: One of "small", "medium", "large"
            thinking: Whether to use thinking model variant

        Returns:
            Model identifier string
        """
        models = self.THINKING_MODELS if thinking else self.MODELS
        return models.get(tier, self.MODELS["small"])

    def get_reasoning_effort(self, context: str) -> str:
        """Get reasoning effort level for a context.

        Args:
            context: One of "agent_assess", "deliberation", "council_synthesis"

        Returns:
            Effort level string
        """
        return self.REASONING_EFFORT.get(context, "minimal")

    def validate(self) -> list[str]:
        """Validate configuration, return list of errors."""
        errors = []

        if not self.OPENROUTER_API_KEY:
            errors.append("OPENROUTER_API_KEY is not set")

        if not isinstance(self.MODELS, dict):
            errors.append("MODELS must be a dict")

        if not isinstance(self.THINKING_MODELS, dict):
            errors.append("THINKING_MODELS must be a dict")

        for tier in ["small", "medium", "large"]:
            if tier not in self.MODELS:
                errors.append(f"MODELS missing '{tier}' tier")

        return errors

    def __repr__(self) -> str:
        return f"<Config loaded={bool(self.OPENROUTER_API_KEY)}>"


# Global config instance
_config: Config | None = None


def get_config() -> Config:
    """Get the global configuration instance."""
    global _config
    if _config is None:
        _config = Config()
    return _config


def reload_config() -> Config:
    """Reload configuration from disk."""
    global _config
    _config = Config()
    return _config
