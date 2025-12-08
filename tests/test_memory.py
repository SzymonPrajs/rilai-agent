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
