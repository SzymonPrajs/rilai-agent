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

    def test_explicit_opposition(self):
        graph = ArgumentGraph()
        claim1 = Claim(
            id="c1",
            text="Proceed with plan",
            type=ClaimType.RECOMMENDATION,
            source_agent="planning.short_term",
            urgency=2,
            confidence=2,
        )
        claim2 = Claim(
            id="c2",
            text="Wait for more info",
            type=ClaimType.RECOMMENDATION,
            source_agent="inhibition.censor",
            urgency=2,
            confidence=2,
            opposes=["c1"],
        )
        graph.add_claim(claim1)
        graph.add_claim(claim2)

        assert "c2" in graph.get_opposers("c1")

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

    def test_empty_graph_full_consensus(self):
        graph = ArgumentGraph()
        consensus = graph.compute_consensus()
        assert consensus.overall_score == 1.0

    def test_top_claims_sorted_by_salience(self):
        graph = ArgumentGraph()
        # Low salience claim
        graph.add_claim(Claim(
            id="low",
            text="Low priority",
            type=ClaimType.OBSERVATION,
            source_agent="agent.a",
            urgency=1,
            confidence=1,
        ))
        # High salience claim
        graph.add_claim(Claim(
            id="high",
            text="High priority",
            type=ClaimType.OBSERVATION,
            source_agent="agent.b",
            urgency=3,
            confidence=3,
        ))

        top = graph.get_top_claims(2)
        assert top[0].id == "high"
        assert top[1].id == "low"

    def test_claims_for_council_organized_by_type(self):
        graph = ArgumentGraph()
        graph.add_claim(Claim(
            id="obs",
            text="Observation",
            type=ClaimType.OBSERVATION,
            source_agent="agent.a",
            urgency=2,
            confidence=2,
        ))
        graph.add_claim(Claim(
            id="rec",
            text="Recommendation",
            type=ClaimType.RECOMMENDATION,
            source_agent="agent.b",
            urgency=2,
            confidence=2,
        ))
        graph.add_claim(Claim(
            id="con",
            text="Concern",
            type=ClaimType.CONCERN,
            source_agent="agent.c",
            urgency=2,
            confidence=2,
        ))

        council_claims = graph.get_claims_for_council()
        assert len(council_claims["observations"]) == 1
        assert len(council_claims["recommendations"]) == 1
        assert len(council_claims["concerns"]) == 1

    def test_to_prompt_context(self):
        graph = ArgumentGraph()
        graph.add_claim(Claim(
            id="c1",
            text="User seems stressed",
            type=ClaimType.OBSERVATION,
            source_agent="emotion.stress",
            urgency=2,
            confidence=2,
        ))

        context = graph.to_prompt_context()
        assert "OBSERVATIONS" in context
        assert "User seems stressed" in context

    def test_opposition_strength_calculation(self):
        graph = ArgumentGraph()
        claim1 = Claim(
            id="c1",
            text="Do X",
            type=ClaimType.RECOMMENDATION,
            source_agent="agent.a",
            urgency=2,
            confidence=2,
        )
        claim2 = Claim(
            id="c2",
            text="Don't do X",
            type=ClaimType.RECOMMENDATION,
            source_agent="agent.b",
            urgency=2,
            confidence=3,
            opposes=["c1"],
        )
        graph.add_claim(claim1)
        graph.add_claim(claim2)

        # c1 is opposed by c2
        opposition = graph.get_opposition_strength("c1")
        assert opposition > 0.0
        assert opposition <= 1.0

    def test_support_strength_calculation(self):
        graph = ArgumentGraph()
        claim1 = Claim(
            id="c1",
            text="Main claim",
            type=ClaimType.OBSERVATION,
            source_agent="agent.a",
            urgency=2,
            confidence=2,
        )
        claim2 = Claim(
            id="c2",
            text="Supporting evidence",
            type=ClaimType.OBSERVATION,
            source_agent="agent.b",
            urgency=2,
            confidence=3,
            supports=["c1"],
        )
        graph.add_claim(claim1)
        graph.add_claim(claim2)

        support = graph.get_support_strength("c1")
        assert support > 0.0
        assert support <= 1.0


class TestDeliberator:
    @pytest.mark.asyncio
    async def test_single_round_high_consensus(self):
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

        result = await deliberator.deliberate(outputs, workspace=None)

        assert result.overall_score > 0.8
        assert any(e[0].value == "delib_round_started" for e in events)
        assert any(e[0].value == "consensus_updated" for e in events)

    @pytest.mark.asyncio
    async def test_contested_claims_no_early_exit(self):
        events = []

        def emit_fn(kind, payload):
            events.append((kind, payload))

        deliberator = Deliberator(emit_fn=emit_fn)

        outputs = [
            AgentOutput(
                agent_id="agent.a",
                observation="Should do X",
                salience=0.8,
                urgency=3,
                confidence=3,
                claims=[
                    Claim(
                        id="c1",
                        text="Should increase activity",
                        type=ClaimType.RECOMMENDATION,
                        source_agent="agent.a",
                        urgency=3,
                        confidence=3,
                    )
                ],
            ),
            AgentOutput(
                agent_id="agent.b",
                observation="Should not do X",
                salience=0.8,
                urgency=3,
                confidence=3,
                claims=[
                    Claim(
                        id="c2",
                        text="Should decrease activity",
                        type=ClaimType.RECOMMENDATION,
                        source_agent="agent.b",
                        urgency=3,
                        confidence=3,
                    )
                ],
            ),
        ]

        result = await deliberator.deliberate(outputs, workspace=None)

        # With contested claims, consensus should be lower
        assert result.overall_score < 0.9

    @pytest.mark.asyncio
    async def test_process_output_adds_claims(self):
        deliberator = Deliberator(emit_fn=lambda k, p: None)

        output = AgentOutput(
            agent_id="agent.1",
            observation="Test",
            salience=0.5,
            urgency=2,
            confidence=2,
            claims=[
                Claim(
                    id="c1",
                    text="Claim 1",
                    type=ClaimType.OBSERVATION,
                    source_agent="agent.1",
                    urgency=2,
                    confidence=2,
                ),
                Claim(
                    id="c2",
                    text="Claim 2",
                    type=ClaimType.OBSERVATION,
                    source_agent="agent.1",
                    urgency=2,
                    confidence=2,
                ),
            ],
        )

        deliberator._process_output(output)

        assert len(deliberator.graph.claims) == 2
        assert "c1" in deliberator.graph.claims
        assert "c2" in deliberator.graph.claims

    @pytest.mark.asyncio
    async def test_get_top_claims(self):
        deliberator = Deliberator(emit_fn=lambda k, p: None)

        outputs = [
            AgentOutput(
                agent_id="agent.1",
                observation="Test",
                salience=0.5,
                urgency=2,
                confidence=2,
                claims=[
                    Claim(
                        id="high",
                        text="High priority",
                        type=ClaimType.OBSERVATION,
                        source_agent="agent.1",
                        urgency=3,
                        confidence=3,
                    ),
                    Claim(
                        id="low",
                        text="Low priority",
                        type=ClaimType.OBSERVATION,
                        source_agent="agent.1",
                        urgency=1,
                        confidence=1,
                    ),
                ],
            ),
        ]

        await deliberator.deliberate(outputs, workspace=None)

        top = deliberator.get_top_claims(2)
        assert top[0].id == "high"

    @pytest.mark.asyncio
    async def test_get_claims_by_type(self):
        deliberator = Deliberator(emit_fn=lambda k, p: None)

        outputs = [
            AgentOutput(
                agent_id="agent.1",
                observation="Test",
                salience=0.5,
                urgency=2,
                confidence=2,
                claims=[
                    Claim(
                        id="obs",
                        text="Observation",
                        type=ClaimType.OBSERVATION,
                        source_agent="agent.1",
                        urgency=2,
                        confidence=2,
                    ),
                    Claim(
                        id="rec",
                        text="Recommendation",
                        type=ClaimType.RECOMMENDATION,
                        source_agent="agent.1",
                        urgency=2,
                        confidence=2,
                    ),
                ],
            ),
        ]

        await deliberator.deliberate(outputs, workspace=None)

        observations = deliberator.get_claims_by_type(ClaimType.OBSERVATION)
        recommendations = deliberator.get_claims_by_type(ClaimType.RECOMMENDATION)

        assert len(observations) == 1
        assert len(recommendations) == 1
        assert observations[0].id == "obs"
        assert recommendations[0].id == "rec"

    def test_select_agents_for_followup(self):
        deliberator = Deliberator(emit_fn=lambda k, p: None)

        # Add opposing claims manually
        claim1 = Claim(
            id="c1",
            text="Do X",
            type=ClaimType.RECOMMENDATION,
            source_agent="agent.a",
            urgency=3,
            confidence=3,
        )
        claim2 = Claim(
            id="c2",
            text="Don't do X",
            type=ClaimType.RECOMMENDATION,
            source_agent="agent.b",
            urgency=3,
            confidence=3,
            opposes=["c1"],
        )
        deliberator.graph.add_claim(claim1)
        deliberator.graph.add_claim(claim2)

        contested = [claim1]  # c1 is contested by c2
        agents = deliberator._select_agents_for_followup(contested)

        assert "agent.a" in agents
        assert "agent.b" in agents
