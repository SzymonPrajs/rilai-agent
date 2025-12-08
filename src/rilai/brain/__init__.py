"""Brain module - daemon scheduler, modulators, and ambient processing."""

# Light imports (no circular dependencies)
from .episode_builder import EpisodeBuilder, EpisodeBuilderConfig
from .daydream import DaydreamProcessor, DaydreamConfig, Suggestion
from .surfacer import Surfacer, SurfacerConfig, SurfaceResult, FORBIDDEN_PHRASES


def __getattr__(name: str):
    """Lazy import for heavy modules with circular dependencies."""
    if name in ("BrainDaemon", "Scheduler"):
        from .scheduler import BrainDaemon, Scheduler
        return {"BrainDaemon": BrainDaemon, "Scheduler": Scheduler}[name]
    if name in (
        "AgentActivationState",
        "ARCHETYPE_WEIGHTS",
        "GlobalModulators",
        "MODULATOR_MAP",
        "get_archetype_weight",
    ):
        from .modulators import (
            ARCHETYPE_WEIGHTS,
            MODULATOR_MAP,
            AgentActivationState,
            GlobalModulators,
            get_archetype_weight,
        )
        return {
            "AgentActivationState": AgentActivationState,
            "ARCHETYPE_WEIGHTS": ARCHETYPE_WEIGHTS,
            "GlobalModulators": GlobalModulators,
            "MODULATOR_MAP": MODULATOR_MAP,
            "get_archetype_weight": get_archetype_weight,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Episode building (light)
    "EpisodeBuilder",
    "EpisodeBuilderConfig",
    # Daydream (light)
    "DaydreamProcessor",
    "DaydreamConfig",
    "Suggestion",
    # Surfacer (light)
    "Surfacer",
    "SurfacerConfig",
    "SurfaceResult",
    "FORBIDDEN_PHRASES",
    # Heavy (lazy loaded)
    "AgentActivationState",
    "ARCHETYPE_WEIGHTS",
    "BrainDaemon",
    "GlobalModulators",
    "MODULATOR_MAP",
    "Scheduler",
    "get_archetype_weight",
]
