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
