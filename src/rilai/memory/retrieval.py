"""Memory retrieval for context injection."""

from typing import Callable, AsyncIterator, TYPE_CHECKING
from datetime import datetime, timedelta, timezone

from rilai.contracts.events import EngineEvent, EventKind
from rilai.contracts.memory import EpisodicEvent, UserFact

if TYPE_CHECKING:
    from rilai.memory.episodic import EpisodicStore
    from rilai.memory.user_model import UserModel
    from rilai.runtime.workspace import Workspace


class MemoryRetriever:
    """Retrieves relevant memories for context injection.

    Runs at Stage 2 to populate workspace context slots:
    - retrieved_episodes: Recent and relevant episodic events
    - user_facts: Known user preferences and facts
    - open_threads: Active goals and threads
    """

    MAX_EPISODES = 10
    MAX_FACTS = 20
    MAX_THREADS = 5
    RECENT_WINDOW_HOURS = 24

    def __init__(
        self,
        episodic_store: "EpisodicStore",
        user_model: "UserModel",
        emit_fn: Callable[[EventKind, dict], EngineEvent],
    ):
        self.episodic_store = episodic_store
        self.user_model = user_model
        self.emit_fn = emit_fn

    async def retrieve_context(
        self,
        user_message: str,
        workspace: "Workspace",
    ) -> AsyncIterator[EngineEvent]:
        """Retrieve and inject memory context into workspace.

        Args:
            user_message: Current user message
            workspace: Workspace to populate

        Yields:
            Events for each retrieval step
        """
        # 1. Retrieve recent episodes
        recent_cutoff = datetime.now(timezone.utc) - timedelta(hours=self.RECENT_WINDOW_HOURS)
        recent_episodes = await self.episodic_store.get_recent(
            since=recent_cutoff,
            limit=self.MAX_EPISODES // 2,
        )

        # 2. Retrieve semantically similar episodes
        similar_episodes = await self.episodic_store.search_similar(
            query=user_message,
            limit=self.MAX_EPISODES // 2,
            exclude_ids=[e.id for e in recent_episodes if e.id],
        )

        # Combine and dedupe
        all_episodes = recent_episodes + similar_episodes
        workspace.retrieved_episodes = [self._episode_to_dict(e) for e in all_episodes]

        yield self.emit_fn(
            EventKind.MEMORY_RETRIEVED,
            {
                "field": "retrieved_episodes",
                "count": len(all_episodes),
            },
        )

        # 3. Retrieve relevant user facts
        facts = await self.user_model.get_relevant_facts(
            context=user_message,
            limit=self.MAX_FACTS,
        )
        workspace.user_facts = [self._fact_to_dict(f) for f in facts]

        yield self.emit_fn(
            EventKind.MEMORY_RETRIEVED,
            {
                "field": "user_facts",
                "count": len(facts),
            },
        )

        # 4. Retrieve open threads/goals
        threads = await self.user_model.get_open_threads(limit=self.MAX_THREADS)
        workspace.open_threads = [
            {"id": t.id, "text": t.text, "progress": t.progress, "priority": t.priority}
            for t in threads
        ]

        yield self.emit_fn(
            EventKind.MEMORY_RETRIEVED,
            {
                "field": "open_threads",
                "count": len(threads),
            },
        )

    def _episode_to_dict(self, episode: EpisodicEvent) -> dict:
        """Convert episode to dict for workspace."""
        return {
            "id": episode.id,
            "timestamp": episode.timestamp.isoformat(),
            "summary": episode.summary,
            "emotions": episode.emotions,
            "topics": episode.topics,
            "importance": episode.importance,
        }

    def _fact_to_dict(self, fact: UserFact) -> dict:
        """Convert fact to dict for workspace."""
        return {
            "id": fact.id,
            "text": fact.text,
            "category": fact.category,
            "confidence": fact.confidence,
            "source": fact.source,
        }
