"""Tests for v3 memory module."""

import pytest
import tempfile
from pathlib import Path
from datetime import datetime, timedelta

from rilai.memory.episodic import EpisodicStore
from rilai.memory.user_model import UserModel
from rilai.memory.embeddings import _simple_embedding, cosine_similarity
from rilai.contracts.memory import EpisodicEvent, UserFact
from rilai.contracts.memory import Goal as MemoryGoal  # Use memory.Goal directly


class TestEmbeddings:
    def test_simple_embedding_returns_vector(self):
        embedding = _simple_embedding("Hello world")
        assert len(embedding) == 128
        assert all(isinstance(x, float) for x in embedding)

    def test_simple_embedding_normalized(self):
        embedding = _simple_embedding("Test sentence with multiple words")
        magnitude = sum(x * x for x in embedding) ** 0.5
        # Should be approximately 1.0 (normalized)
        assert 0.99 < magnitude < 1.01

    def test_cosine_similarity_identical(self):
        embedding = _simple_embedding("Same text")
        similarity = cosine_similarity(embedding, embedding)
        assert similarity > 0.99

    def test_cosine_similarity_different(self):
        emb1 = _simple_embedding("The quick brown fox")
        emb2 = _simple_embedding("completely different words here")
        similarity = cosine_similarity(emb1, emb2)
        # Should be less similar than identical
        assert similarity < 0.9


class TestEpisodicStore:
    @pytest.fixture
    def store(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            yield EpisodicStore(Path(f.name))

    @pytest.mark.asyncio
    async def test_store_and_retrieve(self, store):
        event = EpisodicEvent(
            timestamp=datetime.now(),
            summary="User shared about work stress",
            emotions=["stressed", "overwhelmed"],
            importance=0.8,
        )

        event_id = await store.store(event)
        assert event_id

        recent = await store.get_recent(
            since=datetime.now() - timedelta(hours=1),
            limit=10,
        )
        assert len(recent) == 1
        assert recent[0].summary == "User shared about work stress"

    @pytest.mark.asyncio
    async def test_store_multiple_events(self, store):
        for i in range(5):
            event = EpisodicEvent(
                timestamp=datetime.now(),
                summary=f"Event {i}",
                importance=0.5 + i * 0.1,
            )
            await store.store(event)

        recent = await store.get_recent(
            since=datetime.now() - timedelta(hours=1),
            limit=10,
        )
        assert len(recent) == 5

    @pytest.mark.asyncio
    async def test_keyword_search(self, store):
        event1 = EpisodicEvent(
            timestamp=datetime.now(),
            summary="Discussed project deadline today",
            importance=0.7,
        )
        event2 = EpisodicEvent(
            timestamp=datetime.now(),
            summary="Talked about weekend plans",
            importance=0.5,
        )

        await store.store(event1)
        await store.store(event2)

        # Use a keyword that matches the summary
        results = await store.search_similar("project deadline", limit=5)
        assert len(results) >= 1
        assert "deadline" in results[0].summary.lower()

    @pytest.mark.asyncio
    async def test_exclude_ids_in_search(self, store):
        event1 = EpisodicEvent(
            id="evt1",
            timestamp=datetime.now(),
            summary="First deadline event",
            importance=0.8,
        )
        event2 = EpisodicEvent(
            id="evt2",
            timestamp=datetime.now(),
            summary="Second deadline event",
            importance=0.7,
        )

        await store.store(event1)
        await store.store(event2)

        results = await store.search_similar(
            "deadline", limit=5, exclude_ids=["evt1"]
        )
        assert all(r.id != "evt1" for r in results)


class TestUserModel:
    @pytest.fixture
    def model(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            yield UserModel(Path(f.name))

    @pytest.mark.asyncio
    async def test_add_and_get_fact(self, model):
        fact = UserFact(
            text="User prefers morning meetings",
            category="preference",
            confidence=0.8,
        )

        await model.add_fact(fact)

        facts = await model.get_facts_by_category("preference")
        assert len(facts) == 1
        assert "morning meetings" in facts[0].text

    @pytest.mark.asyncio
    async def test_fact_deduplication(self, model):
        # Facts need > 60% word overlap to be deduplicated
        # "User likes coffee" (3 words) vs "User really likes coffee" (4 words)
        # Overlap = 3 words, Union = 4 words, 3/4 = 75% > 60%
        fact1 = UserFact(
            text="User likes coffee",
            category="preference",
            confidence=0.6,
        )
        fact2 = UserFact(
            text="User really likes coffee",
            category="preference",
            confidence=0.7,
        )

        await model.add_fact(fact1)
        await model.add_fact(fact2)

        facts = await model.get_facts_by_category("preference")
        assert len(facts) == 1
        # Confidence should have increased (original 0.6 + 0.1 = 0.7)
        assert facts[0].confidence >= 0.7

    @pytest.mark.asyncio
    async def test_fact_different_categories(self, model):
        fact1 = UserFact(
            text="Likes coffee",
            category="preference",
            confidence=0.7,
        )
        fact2 = UserFact(
            text="Likes coffee",
            category="boundary",
            confidence=0.7,
        )

        await model.add_fact(fact1)
        await model.add_fact(fact2)

        prefs = await model.get_facts_by_category("preference")
        bounds = await model.get_facts_by_category("boundary")
        assert len(prefs) == 1
        assert len(bounds) == 1

    @pytest.mark.asyncio
    async def test_get_relevant_facts(self, model):
        await model.add_fact(UserFact(
            text="User prefers quiet environments",
            category="preference",
            confidence=0.8,
        ))
        await model.add_fact(UserFact(
            text="User has deadline this week",
            category="background",
            confidence=0.7,
        ))

        facts = await model.get_relevant_facts("quiet workspace", limit=10)
        # Should find the quiet environment preference
        assert any("quiet" in f.text.lower() for f in facts)

    @pytest.mark.asyncio
    async def test_goal_management(self, model):
        goal = MemoryGoal(
            text="Complete project report",
            priority=2,
        )

        goal_id = await model.add_goal(goal)

        threads = await model.get_open_threads()
        assert len(threads) == 1

        await model.update_goal_progress(goal_id, 0.5, "Halfway done")

        threads = await model.get_open_threads()
        assert threads[0].progress == 0.5

        await model.complete_goal(goal_id)

        threads = await model.get_open_threads()
        assert len(threads) == 0

    @pytest.mark.asyncio
    async def test_multiple_goals_sorted_by_priority(self, model):
        await model.add_goal(MemoryGoal(text="Low priority", priority=1))
        await model.add_goal(MemoryGoal(text="High priority", priority=3))
        await model.add_goal(MemoryGoal(text="Medium priority", priority=2))

        threads = await model.get_open_threads()
        assert threads[0].text == "High priority"
        assert threads[1].text == "Medium priority"
        assert threads[2].text == "Low priority"


# ─────────────────────────────────────────────────────────────────────────────
# Consolidation Tests
# ─────────────────────────────────────────────────────────────────────────────

from rilai.memory.consolidation import (
    ConsolidationStore,
    MemoryConsolidator,
    MemoryCandidate,
    MemoryLink,
    ConsolidationScheduler,
)


class TestConsolidationStore:
    @pytest.fixture
    def store(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            yield ConsolidationStore(Path(f.name))

    def test_store_memory(self, store):
        candidate = MemoryCandidate(
            content="User mentioned feeling stressed",
            source="agent:emotion",
            significance=0.7,
            metadata={"urgency": 2, "confidence": 3},
        )

        memory_id = store.store_memory(candidate)
        assert memory_id == candidate.id

    def test_record_and_get_access(self, store):
        candidate = MemoryCandidate(
            id="mem1",
            content="Test memory",
            source="test",
            significance=0.5,
        )
        store.store_memory(candidate)

        # Record accesses
        store.record_access("mem1", "retrieval", "test context")
        store.record_access("mem1", "retrieval")
        store.record_access("mem1", "retrieval")

        count = store.get_access_count("mem1")
        assert count == 3

    def test_get_access_since(self, store):
        candidate = MemoryCandidate(
            id="mem2",
            content="Test memory",
            source="test",
            significance=0.5,
        )
        store.store_memory(candidate)

        store.record_access("mem2")
        store.record_access("mem2")

        # Access count since future (should exclude past accesses)
        future = datetime.now() + timedelta(hours=1)
        count = store.get_access_count("mem2", since=future)
        assert count == 0

        # Total count without since filter should work
        total_count = store.get_access_count("mem2")
        assert total_count == 2

    def test_create_and_get_links(self, store):
        # Store two memories
        store.store_memory(MemoryCandidate(id="m1", content="Memory 1", source="test", significance=0.5))
        store.store_memory(MemoryCandidate(id="m2", content="Memory 2", source="test", significance=0.5))

        # Create link
        link = MemoryLink(from_id="m1", to_id="m2", relationship="supports", strength=0.8)
        store.create_link(link)

        # Get links
        links = store.get_links("m1")
        assert len(links) == 1
        assert links[0].relationship == "supports"
        assert links[0].strength == 0.8

        # Links should be bidirectional in retrieval
        links = store.get_links("m2")
        assert len(links) == 1

    def test_get_old_memories(self, store):
        # Store old and new memories
        old_candidate = MemoryCandidate(
            id="old",
            content="Old memory",
            source="test",
            significance=0.5,
            created_at=datetime.now() - timedelta(days=10),
        )
        new_candidate = MemoryCandidate(
            id="new",
            content="New memory",
            source="test",
            significance=0.5,
            created_at=datetime.now(),
        )

        store.store_memory(old_candidate)
        store.store_memory(new_candidate)

        # Get memories older than 5 days
        cutoff = datetime.now() - timedelta(days=5)
        old_memories = store.get_old_memories(cutoff)

        assert len(old_memories) == 1
        assert old_memories[0]["id"] == "old"

    def test_mark_compressed(self, store):
        # Store memories to compress
        store.store_memory(MemoryCandidate(id="c1", content="Content 1", source="test", significance=0.5))
        store.store_memory(MemoryCandidate(id="c2", content="Content 2", source="test", significance=0.5))

        # Mark as compressed
        store.mark_compressed(["c1", "c2"], "summary1")

        # Old memories should now exclude compressed ones
        cutoff = datetime.now() + timedelta(days=1)
        old = store.get_old_memories(cutoff)
        assert len(old) == 0  # Both are marked as compressed


class TestMemoryConsolidator:
    @pytest.fixture
    def consolidator(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            yield MemoryConsolidator(Path(f.name), significance_threshold=0.6)

    def test_add_candidate(self, consolidator):
        candidate = MemoryCandidate(
            content="Test memory",
            source="test",
            significance=0.7,
        )
        consolidator.add_candidate(candidate)
        assert len(consolidator._pending_candidates) == 1

    def test_add_candidates_from_assessments(self, consolidator):
        assessments = [
            {"output": "High urgency observation", "urgency": 3, "confidence": 2, "agent_id": "emotion"},
            {"output": "Low urgency observation", "urgency": 1, "confidence": 1, "agent_id": "planning"},
        ]
        consolidator.add_candidates_from_assessments(assessments)
        # Only high significance candidates should be added (pre-filtered at 0.3)
        assert len(consolidator._pending_candidates) >= 1

    @pytest.mark.asyncio
    async def test_run_consolidation_promotes_significant(self, consolidator):
        # Add a high-significance candidate
        high_sig = MemoryCandidate(
            content="Very important memory",
            source="agent:emotion",
            significance=0.8,
        )
        consolidator.add_candidate(high_sig)

        # Add a low-significance candidate
        low_sig = MemoryCandidate(
            content="Unimportant memory",
            source="agent:planning",
            significance=0.3,
        )
        consolidator.add_candidate(low_sig)

        result = await consolidator.run_consolidation()

        assert result.items_reviewed == 2
        assert result.items_promoted == 1  # Only high significance promoted
        assert result.errors == []

    @pytest.mark.asyncio
    async def test_consolidation_clears_pending(self, consolidator):
        consolidator.add_candidate(MemoryCandidate(
            content="Test",
            source="test",
            significance=0.7,
        ))

        await consolidator.run_consolidation()

        # Pending candidates should be cleared
        assert len(consolidator._pending_candidates) == 0

    def test_compute_access_score(self, consolidator):
        # Store a memory and record accesses
        candidate = MemoryCandidate(
            id="score_test",
            content="Test memory",
            source="test",
            significance=0.7,
        )
        consolidator.store.store_memory(candidate)

        # No accesses = 0 score
        score = consolidator.compute_access_score("score_test")
        assert score == 0.0

        # Add some accesses
        for _ in range(5):
            consolidator.record_access("score_test")

        score = consolidator.compute_access_score("score_test")
        assert score > 0.0

    def test_link_memories(self, consolidator):
        # Store two memories
        consolidator.store.store_memory(MemoryCandidate(
            id="link1",
            content="First memory",
            source="test",
            significance=0.5,
        ))
        consolidator.store.store_memory(MemoryCandidate(
            id="link2",
            content="Second memory",
            source="test",
            significance=0.5,
        ))

        # Create link
        consolidator.link_memories("link1", "link2", "supports", strength=0.9)

        # Verify link
        links = consolidator.get_linked_memories("link1")
        assert len(links) == 1
        assert links[0].relationship == "supports"
        assert links[0].strength == 0.9

    def test_significance_computation(self, consolidator):
        # High urgency, high confidence
        high = {"urgency": 3, "confidence": 3, "output": "Medium length output here"}
        high_sig = consolidator._compute_significance(high)

        # Low urgency, low confidence
        low = {"urgency": 1, "confidence": 1, "output": "Short"}
        low_sig = consolidator._compute_significance(low)

        assert high_sig > low_sig


class TestConsolidationScheduler:
    @pytest.fixture
    def scheduler(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            consolidator = MemoryConsolidator(Path(f.name))
            yield ConsolidationScheduler(consolidator, interval_minutes=1)

    @pytest.mark.asyncio
    async def test_start_stop(self, scheduler):
        await scheduler.start()
        assert scheduler.is_running

        await scheduler.stop()
        assert not scheduler.is_running

    @pytest.mark.asyncio
    async def test_maybe_consolidate_respects_interval(self, scheduler):
        await scheduler.start()

        # First run should work
        result = await scheduler.maybe_consolidate()
        assert result is not None

        # Second run immediately should be skipped (interval not passed)
        result = await scheduler.maybe_consolidate()
        assert result is None

    @pytest.mark.asyncio
    async def test_force_consolidate_ignores_interval(self, scheduler):
        await scheduler.start()

        # First run
        await scheduler.force_consolidate()

        # Force should work immediately again
        result = await scheduler.force_consolidate()
        assert result is not None

    @pytest.mark.asyncio
    async def test_stats_tracking(self, scheduler):
        await scheduler.start()

        # Add a significant candidate to be promoted
        scheduler.consolidator.add_candidate(MemoryCandidate(
            content="Significant memory",
            source="test",
            significance=0.8,
        ))

        await scheduler.force_consolidate()

        stats = scheduler.get_stats()
        assert stats["total_runs"] == 1
        assert stats["total_promoted"] == 1
        assert stats["is_running"] is True

    @pytest.mark.asyncio
    async def test_not_running_returns_none(self, scheduler):
        # Don't start the scheduler
        result = await scheduler.maybe_consolidate()
        assert result is None
