"""
Focused Generators Module

Pass-2 generators that produce response candidates conditioned on the workspace.
Each generator specializes in a specific interaction goal.
"""

from rilai.generators.runner import (
    GeneratorRunner,
    GeneratorCandidate,
    run_generators,
)

__all__ = [
    "GeneratorRunner",
    "GeneratorCandidate",
    "run_generators",
]
