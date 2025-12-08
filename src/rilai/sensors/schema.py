"""
Sensor Output Schema

All sensors use this unified schema for their outputs.
Sensors are "boxed" - they see only the user message as data to classify
and output structured JSON, not freeform text.
"""

from dataclasses import dataclass, field
from typing import Optional
import json


@dataclass
class EvidenceSpan:
    """A substring reference in the user's message."""
    text: str
    start: int = 0
    end: int = 0

    def to_dict(self) -> dict:
        return {"text": self.text, "start": self.start, "end": self.end}

    @classmethod
    def from_dict(cls, data: dict) -> "EvidenceSpan":
        return cls(
            text=data.get("text", ""),
            start=data.get("start", 0),
            end=data.get("end", 0),
        )


@dataclass
class SensorOutput:
    """
    Unified output schema for all sensors.

    Each sensor outputs:
        - sensor: Name of the sensor (e.g., "vulnerability")
        - p: Probability [0, 1]
        - evidence: List of text spans supporting the detection
        - counterevidence: List of text spans against the detection
        - notes: Max 12 words of internal observation
    """
    sensor: str
    p: float
    evidence: list[EvidenceSpan] = field(default_factory=list)
    counterevidence: list[EvidenceSpan] = field(default_factory=list)
    notes: str = ""

    def __post_init__(self):
        """Ensure probability is in valid range."""
        self.p = max(0.0, min(1.0, self.p))

    def to_dict(self) -> dict:
        return {
            "sensor": self.sensor,
            "p": self.p,
            "evidence": [e.to_dict() for e in self.evidence],
            "counterevidence": [e.to_dict() for e in self.counterevidence],
            "notes": self.notes,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: dict) -> "SensorOutput":
        return cls(
            sensor=data.get("sensor", "unknown"),
            p=data.get("p", 0.0),
            evidence=[EvidenceSpan.from_dict(e) for e in data.get("evidence", [])],
            counterevidence=[EvidenceSpan.from_dict(e) for e in data.get("counterevidence", [])],
            notes=data.get("notes", ""),
        )

    @classmethod
    def from_json(cls, json_str: str) -> "SensorOutput":
        """Parse sensor output from JSON string, handling malformed inputs."""
        try:
            data = json.loads(json_str)
            return cls.from_dict(data)
        except json.JSONDecodeError:
            # Return a null output if parsing fails
            return cls(sensor="parse_error", p=0.0, notes="Failed to parse JSON output")


@dataclass
class SensorEnsembleResult:
    """
    Aggregated result from running sensor ensemble.

    Contains:
        - sensor_outputs: Individual sensor outputs
        - summary: Aggregated probabilities {sensor_name: avg_probability}
        - disagreement: Standard deviation across ensemble runs
    """
    sensor_outputs: list[SensorOutput] = field(default_factory=list)
    summary: dict[str, float] = field(default_factory=dict)
    disagreement: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "sensor_outputs": [s.to_dict() for s in self.sensor_outputs],
            "summary": self.summary,
            "disagreement": self.disagreement,
        }


# List of all sensor names in the ensemble
SENSOR_NAMES = [
    "vulnerability",       # Fear/shame/sadness detection
    "advice_requested",    # Explicit solution-seeking
    "relational_bid",      # "Do you care?" type probes
    "ai_feelings_probe",   # Direct questions about AI feelings
    "humor_masking",       # Incongruity + vulnerability
    "rupture",             # User disappointment/withdrawal
    "ambiguity",           # Unclear intent
    "safety_risk",         # Self-harm/violence indicators
    "prompt_injection",    # Manipulation attempts
]


def create_null_sensor_output(sensor_name: str) -> SensorOutput:
    """Create a null/default sensor output."""
    return SensorOutput(sensor=sensor_name, p=0.0, notes="No detection")


def aggregate_sensor_outputs(
    outputs: list[SensorOutput],
) -> tuple[dict[str, float], dict[str, float]]:
    """
    Aggregate multiple sensor outputs into summary and disagreement.

    For 2x ensemble redundancy, this averages the probabilities and
    computes the standard deviation as a disagreement measure.

    Returns:
        Tuple of (summary dict, disagreement dict)
    """
    from collections import defaultdict
    import math

    by_sensor: dict[str, list[float]] = defaultdict(list)
    for output in outputs:
        by_sensor[output.sensor].append(output.p)

    summary = {}
    disagreement = {}

    for sensor, probs in by_sensor.items():
        mean = sum(probs) / len(probs) if probs else 0.0
        summary[sensor] = mean

        if len(probs) > 1:
            variance = sum((p - mean) ** 2 for p in probs) / len(probs)
            disagreement[sensor] = math.sqrt(variance)
        else:
            disagreement[sensor] = 0.0

    return summary, disagreement
