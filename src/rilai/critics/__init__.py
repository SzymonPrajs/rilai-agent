"""
Critics Module

Tiny LLM-based critics for validating response candidates.
Each critic outputs pass/fail with reasons.
"""

from rilai.critics.schema import CriticOutput, CriticEnsembleResult
from rilai.critics.runner import CriticRunner

__all__ = ["CriticOutput", "CriticEnsembleResult", "CriticRunner"]
