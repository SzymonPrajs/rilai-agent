"""Claim-based deliberation system."""

import asyncio
from typing import AsyncIterator, Callable, TYPE_CHECKING

from rilai.contracts.events import EngineEvent, EventKind
from rilai.contracts.agent import AgentOutput, Claim, ClaimType
from rilai.runtime.argument_graph import ArgumentGraph, ConsensusResult

if TYPE_CHECKING:
    from rilai.runtime.workspace import Workspace


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
