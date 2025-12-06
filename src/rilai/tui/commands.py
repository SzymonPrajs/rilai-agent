"""Slash command handlers for Rilai TUI.

All CLI commands accessible via `/` prefix in the TUI.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Any, Awaitable, Callable

if TYPE_CHECKING:
    from rilai.tui.app import RilaiApp

# Type alias for command handlers
CommandHandler = Callable[["RilaiApp", str], Awaitable[None]]

# Command registry
COMMANDS: dict[str, CommandHandler] = {}


def command(name: str):
    """Decorator to register a slash command."""

    def decorator(func: CommandHandler) -> CommandHandler:
        COMMANDS[name] = func
        return func

    return decorator


@command("help")
async def cmd_help(app: "RilaiApp", args: str) -> None:
    """Show available commands."""
    lines = [
        "**Available Commands**",
        "",
        "- `/help` - Show this help",
        "- `/clear` - Clear current session",
        "- `/clear all` - Clear all data",
        "- `/status` - Show system status",
        "- `/query agent-calls` - Show recent agent activity",
        "- `/query stats` - Show statistics",
        "- `/export json` - Export conversation as JSON",
        "- `/export md` - Export conversation as markdown",
        "- `/agencies` - Toggle agency panel",
        "- `/thinking` - Toggle thinking panel",
        "- `/daemon start|stop` - Control background daemon",
        "- `/config` - Show current configuration",
        "- `/quiet` - Toggle proactive messages",
    ]
    app.show_system_message("\n".join(lines))


@command("clear")
async def cmd_clear(app: "RilaiApp", args: str) -> None:
    """Clear session data."""
    from rilai.observability import get_store

    store = get_store()

    if args.strip() == "all":
        store.clear_all()
        app.show_system_message("All data cleared.")
    else:
        store.clear_current()
        app.show_system_message("Current session cleared.")

    app.clear_chat()


@command("status")
async def cmd_status(app: "RilaiApp", args: str) -> None:
    """Show system status."""
    from rilai.config import get_config
    from rilai.observability import get_store

    config = get_config()
    store = get_store()

    daemon_status = "Running" if app.daemon_running else "Stopped"
    session_id = store.session_id or "None"

    stats = store.get_stats(24)

    lines = [
        "**System Status**",
        "",
        f"- Daemon: {daemon_status}",
        f"- Session: `{session_id[:8]}...`" if session_id != "None" else "- Session: None",
        f"- Agencies: 10 configured",
        f"- Agents: 49 loaded",
        "",
        "**Last 24h Stats**",
        f"- Turns: {stats.get('turns', 0)}",
        f"- Agent calls: {stats.get('agent_calls', 0)}",
        f"- Avg turn time: {stats.get('avg_turn_time_ms', 0):.0f}ms",
    ]
    app.show_system_message("\n".join(lines))


@command("query")
async def cmd_query(app: "RilaiApp", args: str) -> None:
    """Query logs and stats."""
    from rilai.observability import get_store

    store = get_store()
    query_type = args.strip().lower()

    if query_type == "agent-calls":
        calls = store.get_recent_agent_calls(limit=10)
        if not calls:
            app.show_system_message("No recent agent calls.")
            return

        lines = ["**Recent Agent Calls**", ""]
        for call in calls[:10]:
            lines.append(
                f"- `{call['agent_id']}`: U={call['urgency']} C={call['confidence']} ({call['time_ms']}ms)"
            )
        app.show_system_message("\n".join(lines))

    elif query_type == "stats":
        stats = store.get_stats(24)
        agent_stats = store.get_agent_stats(limit=5)

        lines = [
            "**Statistics (Last 24h)**",
            "",
            f"- Turns: {stats.get('turns', 0)}",
            f"- Agent calls: {stats.get('agent_calls', 0)}",
            f"- Prompt tokens: {stats.get('prompt_tokens', 0):,}",
            f"- Completion tokens: {stats.get('completion_tokens', 0):,}",
            f"- Avg turn time: {stats.get('avg_turn_time_ms', 0):.0f}ms",
            "",
            "**Top Agents by Calls**",
        ]

        for stat in agent_stats:
            lines.append(
                f"- `{stat['agent_id']}`: {stat['call_count']} calls, avg U={stat['avg_urgency']:.1f}"
            )

        app.show_system_message("\n".join(lines))

    else:
        app.show_system_message(
            "Usage: `/query agent-calls` or `/query stats`"
        )


@command("export")
async def cmd_export(app: "RilaiApp", args: str) -> None:
    """Export conversation."""
    import json

    from rilai.observability import get_store

    store = get_store()
    export_type = args.strip().lower()

    if export_type == "json":
        data = store.export_json()
        # In a real app, would save to file
        app.show_system_message(f"```json\n{json.dumps(data, indent=2)[:1000]}...\n```")

    elif export_type in ("md", "markdown"):
        content = store.export_markdown()
        app.show_system_message(f"```markdown\n{content[:1000]}...\n```")

    else:
        app.show_system_message("Usage: `/export json` or `/export md`")


@command("agencies")
async def cmd_agencies(app: "RilaiApp", args: str) -> None:
    """Toggle agency panel visibility."""
    app.toggle_agencies()
    app.show_system_message("Agency panel toggled.")


@command("thinking")
async def cmd_thinking(app: "RilaiApp", args: str) -> None:
    """Toggle thinking panel visibility."""
    app.toggle_thinking()
    app.show_system_message("Thinking panel toggled.")


@command("daemon")
async def cmd_daemon(app: "RilaiApp", args: str) -> None:
    """Control background daemon."""
    action = args.strip().lower()

    if action == "start":
        await app.start_daemon()
        app.show_system_message("Daemon started.")
    elif action == "stop":
        await app.stop_daemon()
        app.show_system_message("Daemon stopped.")
    else:
        status = "running" if app.daemon_running else "stopped"
        app.show_system_message(
            f"Daemon is {status}. Use `/daemon start` or `/daemon stop`."
        )


@command("config")
async def cmd_config(app: "RilaiApp", args: str) -> None:
    """Show current configuration."""
    from rilai.config import get_config

    config = get_config()

    lines = [
        "**Current Configuration**",
        "",
        f"- Small model: `{config.SMALL_MODEL}`",
        f"- Medium model: `{config.MEDIUM_MODEL}`",
        f"- Large model: `{config.LARGE_MODEL}`",
        f"- Daemon interval: {config.DAEMON_TICK_INTERVAL}s",
        f"- Urgency threshold: {config.DAEMON_URGENCY_THRESHOLD}",
        f"- Agency timeout: {config.AGENCY_TIMEOUT_MS}ms",
        f"- Agent timeout: {config.AGENT_TIMEOUT_MS}ms",
    ]
    app.show_system_message("\n".join(lines))


@command("quiet")
async def cmd_quiet(app: "RilaiApp", args: str) -> None:
    """Toggle proactive messages."""
    app.toggle_quiet_mode()
    mode = "enabled" if app.quiet_mode else "disabled"
    app.show_system_message(f"Quiet mode {mode}. Proactive messages will be {'suppressed' if app.quiet_mode else 'shown'}.")


async def handle_command(app: "RilaiApp", text: str) -> bool:
    """Handle a slash command.

    Args:
        app: The RilaiApp instance
        text: The command text (including leading /)

    Returns:
        True if command was handled, False otherwise
    """
    if not text.startswith("/"):
        return False

    # Parse command and args
    parts = text[1:].split(maxsplit=1)
    cmd_name = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""

    if cmd_name in COMMANDS:
        await COMMANDS[cmd_name](app, args)
        return True
    else:
        app.show_system_message(f"Unknown command: `/{cmd_name}`. Use `/help` for available commands.")
        return True
