"""Command-line interface for Rilai v2."""

import argparse
import sys
from pathlib import Path


def cmd_run(args: argparse.Namespace) -> int:
    """Launch the TUI."""
    from rilai.tui.app import RilaiApp

    app = RilaiApp()
    app.run()
    return 0


def cmd_shell(args: argparse.Namespace) -> int:
    """Launch interactive REPL (no TUI)."""
    import asyncio

    from rilai.core.engine import Engine

    async def repl() -> None:
        engine = Engine()
        await engine.start()

        print("Rilai v2 Shell - Type 'exit' to quit")
        print("-" * 40)

        try:
            while True:
                try:
                    user_input = input("\n> ").strip()
                except EOFError:
                    break

                if user_input.lower() in ("exit", "quit"):
                    break

                if not user_input:
                    continue

                result = await engine.process_message(user_input)
                if result.response:
                    print(f"\nRilai: {result.response}")

        finally:
            await engine.stop()

    asyncio.run(repl())
    return 0


def cmd_clear(args: argparse.Namespace) -> int:
    """Clear data."""
    from rilai.config import get_config

    config = get_config()
    data_dir = Path(config.DATA_DIR)

    target = args.target

    if target == "current":
        current_dir = data_dir / "current"
        if current_dir.exists():
            import shutil

            shutil.rmtree(current_dir)
            current_dir.mkdir(parents=True)
            print("Cleared current session")
        else:
            print("No current session to clear")

    elif target == "sessions":
        sessions_dir = data_dir / "sessions"
        current_dir = data_dir / "current"
        for dir_path in [sessions_dir, current_dir]:
            if dir_path.exists():
                import shutil

                shutil.rmtree(dir_path)
                dir_path.mkdir(parents=True)
        print("Cleared all session JSON files")

    elif target == "all":
        confirm = input("This will delete ALL data including the database. Continue? [y/N] ")
        if confirm.lower() == "y":
            if data_dir.exists():
                import shutil

                shutil.rmtree(data_dir)
                data_dir.mkdir(parents=True)
                (data_dir / "current").mkdir()
                (data_dir / "sessions").mkdir()
            print("Cleared all data")
        else:
            print("Cancelled")

    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Show system status."""
    from rilai.config import get_config

    config = get_config()

    print("Rilai v2 Status")
    print("=" * 40)

    # Config status
    errors = config.validate()
    if errors:
        print("\nConfiguration errors:")
        for error in errors:
            print(f"  - {error}")
    else:
        print("\nConfiguration: OK")

    # Models (all treated as thinking models)
    print("\nModels:")
    for tier, model in config.MODELS.items():
        print(f"  {tier}: {model}")

    # Agencies
    print(f"\nAgencies: {config.ENABLED_AGENCIES}")

    # Daemon
    print(f"\nDaemon tick: {config.DAEMON_TICK_INTERVAL}s")
    print(f"Urgency threshold: {config.DAEMON_URGENCY_THRESHOLD}")

    # Deliberation
    print(f"\nDeliberation rounds: {config.DELIBERATION_MAX_ROUNDS}")
    print(f"Consensus threshold: {config.DELIBERATION_CONSENSUS_THRESHOLD}")

    return 0


def cmd_query(args: argparse.Namespace) -> int:
    """Query logs."""
    query_type = args.type

    if query_type == "agent-calls":
        print("Recent agent calls:")
        # TODO: Implement database query
        print("  (not yet implemented)")

    elif query_type == "stats":
        print("Statistics:")
        # TODO: Implement statistics
        print("  (not yet implemented)")

    return 0


def cmd_export(args: argparse.Namespace) -> int:
    """Export data."""
    format_type = args.format

    if format_type == "json":
        print("Exporting to JSON...")
        # TODO: Implement export
        print("  (not yet implemented)")

    return 0


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        prog="rilai",
        description="Rilai v2 - Cognitive architecture for AI companionship",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s 2.0.0",
    )

    subparsers = parser.add_subparsers(dest="command")

    # rilai run (default)
    run_parser = subparsers.add_parser("run", help="Launch TUI (default)")
    run_parser.set_defaults(func=cmd_run)

    # rilai shell
    shell_parser = subparsers.add_parser("shell", help="Interactive REPL (no TUI)")
    shell_parser.set_defaults(func=cmd_shell)

    # rilai clear
    clear_parser = subparsers.add_parser("clear", help="Clear data")
    clear_parser.add_argument(
        "target",
        choices=["current", "sessions", "all"],
        help="What to clear",
    )
    clear_parser.set_defaults(func=cmd_clear)

    # rilai status
    status_parser = subparsers.add_parser("status", help="Show system status")
    status_parser.set_defaults(func=cmd_status)

    # rilai query
    query_parser = subparsers.add_parser("query", help="Query logs")
    query_parser.add_argument(
        "type",
        choices=["agent-calls", "stats"],
        help="Query type",
    )
    query_parser.set_defaults(func=cmd_query)

    # rilai export
    export_parser = subparsers.add_parser("export", help="Export data")
    export_parser.add_argument(
        "format",
        choices=["json"],
        default="json",
        nargs="?",
        help="Export format",
    )
    export_parser.set_defaults(func=cmd_export)

    args = parser.parse_args()

    # Default to run if no command
    if args.command is None:
        args.func = cmd_run

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
