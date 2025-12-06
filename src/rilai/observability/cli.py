"""CLI query commands for observability.

Provides commands to query logs, stats, and traces from the command line.
"""

import json
from datetime import datetime

from rilai.observability.store import get_store


def format_timestamp(ts: datetime | str) -> str:
    """Format a timestamp for display."""
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts)
    return ts.strftime("%Y-%m-%d %H:%M:%S")


def query_agent_calls(
    agent_id: str | None = None,
    limit: int = 20,
    output_format: str = "table",
) -> str:
    """Query recent agent calls.

    Args:
        agent_id: Filter by specific agent (optional)
        limit: Maximum number of results
        output_format: 'table' or 'json'

    Returns:
        Formatted output string
    """
    store = get_store()
    calls = store.get_recent_agent_calls(agent_id=agent_id, limit=limit)

    if not calls:
        return "No agent calls found."

    if output_format == "json":
        return json.dumps(calls, indent=2, default=str)

    # Table format
    lines = [
        "Agent Calls",
        "=" * 80,
        f"{'Agent ID':<30} {'U':>3} {'C':>3} {'Time':>8} {'Created':<20}",
        "-" * 80,
    ]

    for call in calls:
        lines.append(
            f"{call['agent_id']:<30} "
            f"{call['urgency']:>3} "
            f"{call['confidence']:>3} "
            f"{call['time_ms']:>6}ms "
            f"{call['created_at'][:19]}"
        )

    return "\n".join(lines)


def query_stats(hours: int = 24, output_format: str = "table") -> str:
    """Query aggregate statistics.

    Args:
        hours: Time window in hours
        output_format: 'table' or 'json'

    Returns:
        Formatted output string
    """
    store = get_store()
    stats = store.get_stats(hours)
    agent_stats = store.get_agent_stats(limit=10)

    if output_format == "json":
        return json.dumps({"stats": stats, "agent_stats": agent_stats}, indent=2)

    # Table format
    lines = [
        f"Statistics (Last {hours} hours)",
        "=" * 50,
        "",
        "Overview:",
        f"  Turns:            {stats.get('turns', 0):>10}",
        f"  Agent calls:      {stats.get('agent_calls', 0):>10}",
        f"  Model calls:      {stats.get('model_calls', 0):>10}",
        f"  Prompt tokens:    {stats.get('prompt_tokens', 0):>10,}",
        f"  Completion tokens:{stats.get('completion_tokens', 0):>10,}",
        f"  Avg turn time:    {stats.get('avg_turn_time_ms', 0):>10.0f}ms",
        "",
        "Top Agents by Calls:",
        "-" * 50,
    ]

    for stat in agent_stats:
        lines.append(
            f"  {stat['agent_id']:<25} "
            f"{stat['call_count']:>5} calls  "
            f"avg U={stat['avg_urgency']:.1f}"
        )

    return "\n".join(lines)


def query_sessions(limit: int = 10, output_format: str = "table") -> str:
    """Query recent sessions.

    Args:
        limit: Maximum number of results
        output_format: 'table' or 'json'

    Returns:
        Formatted output string
    """
    store = get_store()
    if not store.db:
        return "Database not enabled."

    sessions = store.db.get_sessions(limit=limit)

    if not sessions:
        return "No sessions found."

    if output_format == "json":
        return json.dumps(
            [
                {
                    "id": s.id,
                    "started_at": s.started_at.isoformat() if s.started_at else None,
                    "ended_at": s.ended_at.isoformat() if s.ended_at else None,
                }
                for s in sessions
            ],
            indent=2,
        )

    # Table format
    lines = [
        "Recent Sessions",
        "=" * 80,
        f"{'ID':<40} {'Started':<20} {'Ended':<20}",
        "-" * 80,
    ]

    for session in sessions:
        started = format_timestamp(session.started_at) if session.started_at else "N/A"
        ended = format_timestamp(session.ended_at) if session.ended_at else "Active"
        lines.append(f"{session.id:<40} {started:<20} {ended:<20}")

    return "\n".join(lines)


def query_model_calls(limit: int = 20, output_format: str = "table") -> str:
    """Query recent model calls.

    Args:
        limit: Maximum number of results
        output_format: 'table' or 'json'

    Returns:
        Formatted output string
    """
    store = get_store()
    if not store.db:
        return "Database not enabled."

    calls = store.db.get_model_calls(limit=limit)

    if not calls:
        return "No model calls found."

    if output_format == "json":
        return json.dumps(
            [
                {
                    "model": c.model,
                    "latency_ms": c.latency_ms,
                    "prompt_tokens": c.prompt_tokens,
                    "completion_tokens": c.completion_tokens,
                    "reasoning_tokens": c.reasoning_tokens,
                    "created_at": c.created_at.isoformat() if c.created_at else None,
                }
                for c in calls
            ],
            indent=2,
        )

    # Table format
    lines = [
        "Model Calls",
        "=" * 100,
        f"{'Model':<35} {'Latency':>8} {'Prompt':>8} {'Compl':>8} {'Reason':>8}",
        "-" * 100,
    ]

    for call in calls:
        reasoning = call.reasoning_tokens or 0
        lines.append(
            f"{call.model:<35} "
            f"{call.latency_ms:>6}ms "
            f"{call.prompt_tokens:>8} "
            f"{call.completion_tokens:>8} "
            f"{reasoning:>8}"
        )

    return "\n".join(lines)


def run_query(query_type: str, **kwargs) -> str:
    """Run a query by type.

    Args:
        query_type: One of 'agent-calls', 'stats', 'sessions', 'model-calls'
        **kwargs: Additional arguments passed to the query function

    Returns:
        Formatted output string
    """
    queries = {
        "agent-calls": query_agent_calls,
        "stats": query_stats,
        "sessions": query_sessions,
        "model-calls": query_model_calls,
    }

    if query_type not in queries:
        return f"Unknown query type: {query_type}. Available: {', '.join(queries.keys())}"

    return queries[query_type](**kwargs)
