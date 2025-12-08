# Document 06: Deliberation

**Purpose:** Implement claim-based deliberation with argument graphs
**Execution:** One Claude Code session
**Dependencies:** 01-contracts, 02-event-store, 03-runtime-core, 04-workspace, 05-agents

---

## Overview

Deliberation replaces v2's multi-round agent hearing system with a structured claim-based approach. Agents emit atomic claims which are organized into an argument graph with support/oppose relationships.

---

## Files to Create

```
src/rilai/runtime/
├── deliberation.py      # Deliberator class
└── argument_graph.py    # Claim graph with supports/opposes
```

---

## File: `src/rilai/runtime/deliberation.py`

```python
"""Claim-based deliberation system."""

import asyncio
from typing import AsyncIterator, Callable

from rilai.contracts.events import EngineEvent, EventKind
from rilai.contracts.agent import AgentOutput, Claim, ClaimType
from rilai.runtime.argument_graph import ArgumentGraph, ConsensusResult


class Deliberator:
    """Manages claim-based deliberation rounds."""

    MAX_ROUNDS = 3
    CONSENSUS_THRESHOLD = 0.9
    MIN_CONSENSUS_FOR_EARLY_EXIT = 0.7

    def __init__(
        self,
        emit_fn: Callable[[EventKind, dict], EngineEvent],
    ):
        self.emit_fn = emit_fn
        self.graph = ArgumentGraph()
        self._round = 0

    async def deliberate(
        self,
        initial_outputs: list[AgentOutput],
        workspace: "Workspace",
        request_followup_fn: Callable[[list[str], "Workspace"], AsyncIterator[AgentOutput]] | None = None,
    ) -> ConsensusResult:
        """Run deliberation rounds until consensus or max rounds.

        Args:
            initial_outputs: Agent outputs from first wave
            workspace: Current workspace state
            request_followup_fn: Optional function to request focused follow-ups

        Returns:
            ConsensusResult with final claims and scores
        """
        # Round 0: Process initial outputs
        self._round = 0
        self.emit_fn(
            EventKind.DELIB_ROUND_STARTED,
            {"round": 0, "claim_count": 0},
        )

        for output in initial_outputs:
            self._process_output(output)

        consensus = self.graph.compute_consensus()
        self.emit_fn(
            EventKind.DELIB_ROUND_COMPLETED,
            {
                "round": 0,
                "claim_count": len(self.graph.claims),
                "consensus_score": consensus.overall_score,
            },
        )

        # Check for early exit
        if consensus.overall_score >= self.CONSENSUS_THRESHOLD:
            self.emit_fn(
                EventKind.CONSENSUS_UPDATED,
                {"score": consensus.overall_score, "reason": "high_consensus"},
            )
            return consensus

        # Rounds 1-N: Request focused follow-ups if needed
        while self._round < self.MAX_ROUNDS - 1:
            self._round += 1

            # Check if follow-ups are needed
            contested_claims = self._get_contested_claims()
            if not contested_claims or not request_followup_fn:
                break

            self.emit_fn(
                EventKind.DELIB_ROUND_STARTED,
                {
                    "round": self._round,
                    "contested_count": len(contested_claims),
                },
            )

            # Request focused follow-ups from relevant agents
            agent_ids = self._select_agents_for_followup(contested_claims)
            async for output in request_followup_fn(agent_ids, workspace):
                self._process_output(output)

            consensus = self.graph.compute_consensus()
            self.emit_fn(
                EventKind.DELIB_ROUND_COMPLETED,
                {
                    "round": self._round,
                    "claim_count": len(self.graph.claims),
                    "consensus_score": consensus.overall_score,
                },
            )

            # Check for convergence
            if consensus.overall_score >= self.MIN_CONSENSUS_FOR_EARLY_EXIT:
                break

        # Final consensus
        final_consensus = self.graph.compute_consensus()
        self.emit_fn(
            EventKind.CONSENSUS_UPDATED,
            {
                "score": final_consensus.overall_score,
                "rounds": self._round + 1,
                "claim_count": len(self.graph.claims),
            },
        )

        return final_consensus

    def _process_output(self, output: AgentOutput) -> None:
        """Add claims from agent output to graph."""
        for claim in output.claims:
            self.graph.add_claim(claim)

    def _get_contested_claims(self) -> list[Claim]:
        """Get claims with strong opposition."""
        contested = []
        for claim_id, claim in self.graph.claims.items():
            opposition_strength = self.graph.get_opposition_strength(claim_id)
            if opposition_strength > 0.5 and claim.urgency >= 2:
                contested.append(claim)
        return contested

    def _select_agents_for_followup(self, contested_claims: list[Claim]) -> list[str]:
        """Select agents to request follow-ups from.

        Selects agents that:
        1. Authored contested claims
        2. Authored opposing claims
        """
        agent_ids = set()
        for claim in contested_claims:
            agent_ids.add(claim.source_agent)
            # Add agents who oppose this claim
            for opposer_id in self.graph.get_opposers(claim.id):
                opposing_claim = self.graph.claims.get(opposer_id)
                if opposing_claim:
                    agent_ids.add(opposing_claim.source_agent)
        return list(agent_ids)

    def get_top_claims(self, n: int = 10) -> list[Claim]:
        """Get top N claims by salience."""
        return self.graph.get_top_claims(n)

    def get_claims_by_type(self, claim_type: ClaimType) -> list[Claim]:
        """Get all claims of a specific type."""
        return [c for c in self.graph.claims.values() if c.type == claim_type]
```

---

## File: `src/rilai/runtime/argument_graph.py`

```python
"""Argument graph for claim relationships."""

from dataclasses import dataclass, field
from typing import Dict, Set

from rilai.contracts.agent import Claim, ClaimType


@dataclass
class ConsensusResult:
    """Result of consensus computation."""

    overall_score: float  # 0.0-1.0
    type_scores: dict[ClaimType, float] = field(default_factory=dict)
    top_claims: list[Claim] = field(default_factory=list)
    contested_claims: list[Claim] = field(default_factory=list)
    resolved_claims: list[Claim] = field(default_factory=list)


class ArgumentGraph:
    """Graph of claims with support/oppose relationships.

    Nodes are claims, edges are support/oppose relationships.
    Used to compute consensus and identify contested positions.
    """

    def __init__(self):
        self.claims: Dict[str, Claim] = {}
        self.supports: Dict[str, Set[str]] = {}  # claim_id -> set of supporting claim_ids
        self.opposes: Dict[str, Set[str]] = {}   # claim_id -> set of opposing claim_ids

    def add_claim(self, claim: Claim) -> None:
        """Add a claim to the graph."""
        self.claims[claim.id] = claim

        # Initialize edge sets
        if claim.id not in self.supports:
            self.supports[claim.id] = set()
        if claim.id not in self.opposes:
            self.opposes[claim.id] = set()

        # Process explicit supports
        for supported_id in claim.supports:
            if supported_id in self.claims:
                self.supports[supported_id].add(claim.id)

        # Process explicit opposes
        for opposed_id in claim.opposes:
            if opposed_id in self.claims:
                self.opposes[opposed_id].add(claim.id)

        # Auto-detect opposition based on text similarity
        self._detect_implicit_opposition(claim)

    def _detect_implicit_opposition(self, new_claim: Claim) -> None:
        """Detect implicit opposition between claims.

        Two claims implicitly oppose if:
        1. Same type (both recommendations, both concerns)
        2. Contradictory language detected
        """
        contradiction_markers = [
            ("should", "should not"),
            ("can", "cannot"),
            ("do", "don't"),
            ("increase", "decrease"),
            ("more", "less"),
            ("high", "low"),
        ]

        new_text_lower = new_claim.text.lower()

        for claim_id, existing in self.claims.items():
            if claim_id == new_claim.id:
                continue
            if existing.type != new_claim.type:
                continue

            existing_lower = existing.text.lower()

            # Check for contradictory markers
            for pos, neg in contradiction_markers:
                if (pos in new_text_lower and neg in existing_lower) or \
                   (neg in new_text_lower and pos in existing_lower):
                    self.opposes[claim_id].add(new_claim.id)
                    self.opposes[new_claim.id].add(claim_id)
                    break

    def get_opposition_strength(self, claim_id: str) -> float:
        """Calculate how strongly a claim is opposed.

        Returns:
            Float 0.0-1.0 indicating opposition strength
        """
        if claim_id not in self.claims:
            return 0.0

        claim = self.claims[claim_id]
        opposers = self.opposes.get(claim_id, set())

        if not opposers:
            return 0.0

        # Calculate weighted opposition
        opposition_weight = 0.0
        for opposer_id in opposers:
            opposer = self.claims.get(opposer_id)
            if opposer:
                # Weight by opposer's confidence
                opposition_weight += opposer.confidence / 3.0

        # Normalize by claim's own confidence
        claim_strength = claim.confidence / 3.0
        if claim_strength == 0:
            return min(1.0, opposition_weight)

        return min(1.0, opposition_weight / (claim_strength + opposition_weight))

    def get_support_strength(self, claim_id: str) -> float:
        """Calculate how strongly a claim is supported."""
        if claim_id not in self.claims:
            return 0.0

        supporters = self.supports.get(claim_id, set())

        if not supporters:
            return 0.0

        support_weight = 0.0
        for supporter_id in supporters:
            supporter = self.claims.get(supporter_id)
            if supporter:
                support_weight += supporter.confidence / 3.0

        return min(1.0, support_weight)

    def get_opposers(self, claim_id: str) -> Set[str]:
        """Get IDs of claims that oppose this claim."""
        return self.opposes.get(claim_id, set())

    def get_supporters(self, claim_id: str) -> Set[str]:
        """Get IDs of claims that support this claim."""
        return self.supports.get(claim_id, set())

    def compute_consensus(self) -> ConsensusResult:
        """Compute overall consensus across all claims.

        Consensus is high when:
        - Few contested claims
        - High-urgency claims have support
        - Low opposition overall
        """
        if not self.claims:
            return ConsensusResult(overall_score=1.0)

        # Calculate per-type scores
        type_scores: dict[ClaimType, float] = {}
        type_claims: dict[ClaimType, list[Claim]] = {}

        for claim in self.claims.values():
            if claim.type not in type_claims:
                type_claims[claim.type] = []
            type_claims[claim.type].append(claim)

        for claim_type, claims in type_claims.items():
            if not claims:
                type_scores[claim_type] = 1.0
                continue

            # Score = 1 - average opposition
            total_opposition = sum(
                self.get_opposition_strength(c.id) for c in claims
            )
            type_scores[claim_type] = 1.0 - (total_opposition / len(claims))

        # Overall score is weighted average
        # Weight recommendations and concerns higher
        weights = {
            ClaimType.RECOMMENDATION: 2.0,
            ClaimType.CONCERN: 2.0,
            ClaimType.OBSERVATION: 1.0,
            ClaimType.QUESTION: 0.5,
        }

        weighted_sum = 0.0
        total_weight = 0.0
        for claim_type, score in type_scores.items():
            w = weights.get(claim_type, 1.0)
            weighted_sum += score * w
            total_weight += w

        overall = weighted_sum / total_weight if total_weight > 0 else 1.0

        # Categorize claims
        top_claims = self.get_top_claims(10)
        contested = [
            c for c in self.claims.values()
            if self.get_opposition_strength(c.id) > 0.5
        ]
        resolved = [
            c for c in self.claims.values()
            if self.get_support_strength(c.id) > 0.5 and
               self.get_opposition_strength(c.id) < 0.2
        ]

        return ConsensusResult(
            overall_score=overall,
            type_scores=type_scores,
            top_claims=top_claims,
            contested_claims=contested,
            resolved_claims=resolved,
        )

    def get_top_claims(self, n: int = 10) -> list[Claim]:
        """Get top N claims by salience.

        Salience = (urgency × confidence) - opposition + support
        """
        scored_claims = []
        for claim_id, claim in self.claims.items():
            base_salience = (claim.urgency * claim.confidence) / 9.0
            opposition = self.get_opposition_strength(claim_id)
            support = self.get_support_strength(claim_id)
            final_score = base_salience * (1 - opposition) * (1 + support)
            scored_claims.append((final_score, claim))

        scored_claims.sort(key=lambda x: x[0], reverse=True)
        return [claim for _, claim in scored_claims[:n]]

    def get_claims_for_council(self) -> dict[str, list[Claim]]:
        """Get claims organized for council consumption.

        Returns:
            Dict with keys: observations, recommendations, concerns, questions
        """
        result: dict[str, list[Claim]] = {
            "observations": [],
            "recommendations": [],
            "concerns": [],
            "questions": [],
        }

        top_claims = self.get_top_claims(20)

        for claim in top_claims:
            key = claim.type.value + "s"  # observation -> observations
            if key in result:
                result[key].append(claim)

        return result

    def to_prompt_context(self) -> str:
        """Format graph for inclusion in prompts."""
        claims_for_council = self.get_claims_for_council()
        lines = []

        for category, claims in claims_for_council.items():
            if claims:
                lines.append(f"\n{category.upper()}:")
                for claim in claims[:5]:  # Limit per category
                    opposition = self.get_opposition_strength(claim.id)
                    support = self.get_support_strength(claim.id)
                    status = ""
                    if opposition > 0.3:
                        status = " [contested]"
                    elif support > 0.3:
                        status = " [supported]"
                    lines.append(f"  - {claim.text}{status}")

        return "\n".join(lines)
```

---

## Integration with TurnRunner

Add deliberation stage to `src/rilai/runtime/turn_runner.py`:

```python
async def _run_deliberation(self) -> AsyncIterator[EngineEvent]:
    """Stage 5: Claim-based deliberation."""
    from rilai.runtime.deliberation import Deliberator

    deliberator = Deliberator(emit_fn=self._emit)

    # Get agent outputs from workspace
    agent_outputs = self.workspace.get_agent_outputs()

    # Run deliberation
    consensus = await deliberator.deliberate(
        initial_outputs=agent_outputs,
        workspace=self.workspace,
        request_followup_fn=self._request_agent_followups,
    )

    # Update workspace with results
    self.workspace.consensus_level = consensus.overall_score
    self.workspace.active_claims = deliberator.get_top_claims(15)

    # Emit final state
    yield self._emit(
        EventKind.WORKSPACE_PATCHED,
        {
            "consensus_level": consensus.overall_score,
            "claim_count": len(deliberator.graph.claims),
        },
    )

async def _request_agent_followups(
    self,
    agent_ids: list[str],
    workspace: "Workspace",
) -> AsyncIterator[AgentOutput]:
    """Request focused follow-ups from specific agents."""
    from rilai.agents.executor import execute_agents

    outputs = await execute_agents(
        agent_ids=agent_ids,
        workspace=workspace,
        emit_fn=self._emit,
        timeout_ms=3000,  # Shorter timeout for follow-ups
    )

    for output in outputs:
        yield output
```

---

## v2 Files to DELETE

```
src/rilai/council/deliberation.py
src/rilai/council/collector.py
```

---

## Tests

```python
"""Tests for deliberation module."""

import pytest
from rilai.contracts.agent import Claim, ClaimType, AgentOutput
from rilai.runtime.argument_graph import ArgumentGraph, ConsensusResult
from rilai.runtime.deliberation import Deliberator


class TestArgumentGraph:
    def test_add_claim(self):
        graph = ArgumentGraph()
        claim = Claim(
            id="c1",
            text="User is stressed",
            type=ClaimType.OBSERVATION,
            source_agent="emotion.stress",
            urgency=2,
            confidence=2,
        )
        graph.add_claim(claim)
        assert "c1" in graph.claims

    def test_explicit_support(self):
        graph = ArgumentGraph()
        claim1 = Claim(
            id="c1",
            text="User is stressed",
            type=ClaimType.OBSERVATION,
            source_agent="emotion.stress",
            urgency=2,
            confidence=2,
        )
        claim2 = Claim(
            id="c2",
            text="Noticed elevated language",
            type=ClaimType.OBSERVATION,
            source_agent="monitoring.trigger",
            urgency=1,
            confidence=2,
            supports=["c1"],
        )
        graph.add_claim(claim1)
        graph.add_claim(claim2)

        assert "c2" in graph.get_supporters("c1")

    def test_opposition_detection(self):
        graph = ArgumentGraph()
        claim1 = Claim(
            id="c1",
            text="Should increase engagement",
            type=ClaimType.RECOMMENDATION,
            source_agent="social.empathy",
            urgency=2,
            confidence=2,
        )
        claim2 = Claim(
            id="c2",
            text="Should decrease engagement",
            type=ClaimType.RECOMMENDATION,
            source_agent="inhibition.censor",
            urgency=2,
            confidence=2,
        )
        graph.add_claim(claim1)
        graph.add_claim(claim2)

        assert "c2" in graph.get_opposers("c1")
        assert "c1" in graph.get_opposers("c2")

    def test_consensus_high_when_no_opposition(self):
        graph = ArgumentGraph()
        for i in range(3):
            graph.add_claim(Claim(
                id=f"c{i}",
                text=f"Observation {i}",
                type=ClaimType.OBSERVATION,
                source_agent=f"agent.{i}",
                urgency=1,
                confidence=2,
            ))

        consensus = graph.compute_consensus()
        assert consensus.overall_score > 0.9

    def test_consensus_low_when_contested(self):
        graph = ArgumentGraph()
        claim1 = Claim(
            id="c1",
            text="Should do X",
            type=ClaimType.RECOMMENDATION,
            source_agent="agent.a",
            urgency=3,
            confidence=3,
        )
        claim2 = Claim(
            id="c2",
            text="Should not do X",
            type=ClaimType.RECOMMENDATION,
            source_agent="agent.b",
            urgency=3,
            confidence=3,
            opposes=["c1"],
        )
        graph.add_claim(claim1)
        graph.add_claim(claim2)

        consensus = graph.compute_consensus()
        assert consensus.overall_score < 0.7


class TestDeliberator:
    def test_single_round_high_consensus(self):
        events = []

        def emit_fn(kind, payload):
            events.append((kind, payload))

        deliberator = Deliberator(emit_fn=emit_fn)

        outputs = [
            AgentOutput(
                agent_id="agent.1",
                observation="All good",
                salience=0.5,
                urgency=1,
                confidence=2,
                claims=[
                    Claim(
                        id="c1",
                        text="Neutral state",
                        type=ClaimType.OBSERVATION,
                        source_agent="agent.1",
                        urgency=1,
                        confidence=2,
                    )
                ],
            ),
        ]

        import asyncio
        result = asyncio.run(deliberator.deliberate(outputs, workspace=None))

        assert result.overall_score > 0.8
        assert any(e[0].value == "delib_round_started" for e in events)
        assert any(e[0].value == "consensus_updated" for e in events)
```

---

## Next Document

Proceed to `07-council-voice.md` after deliberation is implemented.
