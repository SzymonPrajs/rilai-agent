"""Working memory - in-context memory for current processing.

Working memory holds information relevant to the current turn,
including conversation context, active goals, and recent assessments.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class WorkingMemoryItem:
    """An item in working memory."""

    content: str
    source: str  # e.g., "user", "agent:emotion.stress", "council"
    relevance: float  # 0.0 to 1.0, decays over time
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ActiveGoal:
    """An active goal being tracked."""

    goal_id: str
    description: str
    priority: int  # 0-3, where 3 is highest
    source: str  # Which agent/system created this
    progress: float  # 0.0 to 1.0
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)


class WorkingMemory:
    """In-context working memory for current processing.

    Working memory is ephemeral - it only persists for the current
    processing turn and is rebuilt for each new turn.

    Contents:
    - Conversation history (recent messages)
    - Active goals (from planning agents)
    - Recent assessments (from current turn)
    - Scratch items (temporary notes)
    """

    def __init__(self, max_items: int = 100, max_goals: int = 10):
        """Initialize working memory.

        Args:
            max_items: Maximum number of items to hold
            max_goals: Maximum number of active goals
        """
        self.max_items = max_items
        self.max_goals = max_goals

        self._items: list[WorkingMemoryItem] = []
        self._goals: dict[str, ActiveGoal] = {}
        self._scratch: dict[str, Any] = {}

    def add_item(
        self,
        content: str,
        source: str,
        relevance: float = 1.0,
        metadata: dict[str, Any] | None = None,
    ) -> WorkingMemoryItem:
        """Add an item to working memory.

        Args:
            content: The content to remember
            source: Where this came from
            relevance: Initial relevance score
            metadata: Optional metadata

        Returns:
            The created item
        """
        item = WorkingMemoryItem(
            content=content,
            source=source,
            relevance=relevance,
            metadata=metadata or {},
        )
        self._items.append(item)

        # Prune if over limit
        if len(self._items) > self.max_items:
            self._prune_items()

        return item

    def get_items(
        self,
        source_filter: str | None = None,
        min_relevance: float = 0.0,
        limit: int | None = None,
    ) -> list[WorkingMemoryItem]:
        """Get items from working memory.

        Args:
            source_filter: Filter by source prefix (e.g., "agent:")
            min_relevance: Minimum relevance threshold
            limit: Maximum items to return

        Returns:
            List of matching items, sorted by relevance
        """
        items = self._items

        if source_filter:
            items = [i for i in items if i.source.startswith(source_filter)]

        items = [i for i in items if i.relevance >= min_relevance]
        items = sorted(items, key=lambda x: x.relevance, reverse=True)

        if limit:
            items = items[:limit]

        return items

    def add_goal(
        self,
        goal_id: str,
        description: str,
        priority: int = 1,
        source: str = "unknown",
    ) -> ActiveGoal:
        """Add or update an active goal.

        Args:
            goal_id: Unique identifier for the goal
            description: What the goal is
            priority: 0-3 priority level
            source: Which agent/system created this

        Returns:
            The created/updated goal
        """
        if goal_id in self._goals:
            goal = self._goals[goal_id]
            goal.description = description
            goal.priority = priority
            goal.updated_at = datetime.now()
        else:
            goal = ActiveGoal(
                goal_id=goal_id,
                description=description,
                priority=priority,
                source=source,
                progress=0.0,
            )
            self._goals[goal_id] = goal

        # Prune if over limit
        if len(self._goals) > self.max_goals:
            self._prune_goals()

        return goal

    def get_goals(
        self,
        min_priority: int = 0,
        source_filter: str | None = None,
    ) -> list[ActiveGoal]:
        """Get active goals.

        Args:
            min_priority: Minimum priority level
            source_filter: Filter by source

        Returns:
            List of matching goals, sorted by priority
        """
        goals = list(self._goals.values())

        if source_filter:
            goals = [g for g in goals if g.source == source_filter]

        goals = [g for g in goals if g.priority >= min_priority]
        return sorted(goals, key=lambda x: x.priority, reverse=True)

    def update_goal_progress(self, goal_id: str, progress: float) -> bool:
        """Update progress on a goal.

        Args:
            goal_id: The goal to update
            progress: New progress value (0.0 to 1.0)

        Returns:
            True if goal was found and updated
        """
        if goal_id not in self._goals:
            return False

        self._goals[goal_id].progress = min(1.0, max(0.0, progress))
        self._goals[goal_id].updated_at = datetime.now()
        return True

    def complete_goal(self, goal_id: str) -> bool:
        """Mark a goal as complete and remove it.

        Args:
            goal_id: The goal to complete

        Returns:
            True if goal was found and removed
        """
        if goal_id in self._goals:
            del self._goals[goal_id]
            return True
        return False

    def set_scratch(self, key: str, value: Any) -> None:
        """Set a scratch value.

        Scratch is for temporary values needed during processing.

        Args:
            key: The key to set
            value: The value to store
        """
        self._scratch[key] = value

    def get_scratch(self, key: str, default: Any = None) -> Any:
        """Get a scratch value.

        Args:
            key: The key to get
            default: Default if not found

        Returns:
            The stored value or default
        """
        return self._scratch.get(key, default)

    def clear_scratch(self) -> None:
        """Clear all scratch values."""
        self._scratch.clear()

    def clear(self) -> None:
        """Clear all working memory."""
        self._items.clear()
        self._goals.clear()
        self._scratch.clear()

    def decay_relevance(self, factor: float = 0.9) -> None:
        """Decay relevance of all items.

        Called between turns to age out old information.

        Args:
            factor: Multiplier for relevance (0-1)
        """
        for item in self._items:
            item.relevance *= factor

    def _prune_items(self) -> None:
        """Remove lowest relevance items to stay under limit."""
        if len(self._items) <= self.max_items:
            return

        # Sort by relevance and keep top items
        self._items = sorted(
            self._items, key=lambda x: x.relevance, reverse=True
        )[: self.max_items]

    def _prune_goals(self) -> None:
        """Remove lowest priority goals to stay under limit."""
        if len(self._goals) <= self.max_goals:
            return

        # Sort by priority and keep top goals
        sorted_goals = sorted(
            self._goals.values(), key=lambda x: x.priority, reverse=True
        )
        self._goals = {g.goal_id: g for g in sorted_goals[: self.max_goals]}

    def to_context_dict(self) -> dict[str, Any]:
        """Export working memory as a context dict for agents.

        Returns:
            Dict suitable for building agent context
        """
        return {
            "items": [
                {
                    "content": i.content,
                    "source": i.source,
                    "relevance": i.relevance,
                }
                for i in self.get_items(limit=20)
            ],
            "goals": [
                {
                    "goal_id": g.goal_id,
                    "description": g.description,
                    "priority": g.priority,
                    "progress": g.progress,
                }
                for g in self.get_goals()
            ],
            "scratch": dict(self._scratch),
        }
