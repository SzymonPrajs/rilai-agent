"""
Sensor Ensemble Module

Tiny LLM-based sensors for detecting features in user messages.
Each sensor outputs a probability and evidence spans.
"""

from rilai.sensors.schema import (
    SensorOutput,
    EvidenceSpan,
    SensorEnsembleResult,
    SENSOR_NAMES,
    aggregate_sensor_outputs,
)
from rilai.sensors.runner import SensorRunner, run_sensor_ensemble

__all__ = [
    "SensorOutput",
    "EvidenceSpan",
    "SensorEnsembleResult",
    "SENSOR_NAMES",
    "aggregate_sensor_outputs",
    "SensorRunner",
    "run_sensor_ensemble",
]
