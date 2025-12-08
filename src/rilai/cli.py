"""Command-line interface for Rilai v2 - Ambient Listening Mode."""

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def cmd_synthetic(args: argparse.Namespace) -> int:
    """Run a synthetic scenario from JSONL file."""
    from rilai.adapters.protocol import PlaybackMode
    from rilai.adapters.synthetic import ChunkingConfig, SyntheticTextAdapter
    from rilai.brain.episode_builder import EpisodeBuilder, EpisodeBuilderConfig
    from rilai.core.events import event_bus
    from rilai.episodes.processor import EpisodeProcessor

    scenario_path = Path(args.scenario)
    if not scenario_path.exists():
        print(f"Error: Scenario file not found: {scenario_path}")
        return 1

    # Parse mode
    mode = PlaybackMode.FAST_FORWARD if args.mode == "fast" else PlaybackMode.REALTIME_SIM

    # Parse chunking config
    chunking = ChunkingConfig(
        chunk_max_chars=args.chunk_max_chars,
        merge_window_sec=args.merge_window_sec,
        enable_chunking=not args.no_chunking,
        enable_merging=not args.no_merging,
    )

    async def run_scenario() -> None:
        # Initialize components
        adapter = SyntheticTextAdapter(
            scenario_path=scenario_path,
            mode=mode,
            chunking=chunking,
            speed_multiplier=args.speed,
        )

        episode_builder = EpisodeBuilder(
            config=EpisodeBuilderConfig(
                silence_gap_ms=args.gap_threshold_ms,
            ),
            on_episode=lambda ep: print(
                f"[Episode] {ep.episode_id}: {ep.turn_count} turns, "
                f"{ep.word_count} words, {ep.boundary_type}"
            ),
        )

        episode_processor = EpisodeProcessor()

        # Start event bus
        await event_bus.start()

        # Start adapter
        await adapter.start()
        print(f"\n{adapter.get_timeline_summary()}\n")
        print("-" * 60)

        # Process utterances
        utterance_count = 0
        episode_count = 0

        try:
            async for utterance in adapter.stream():
                utterance_count += 1

                if args.verbose:
                    print(
                        f"[{utterance.ts_start.strftime('%H:%M:%S')}] "
                        f"{utterance.speaker_id}: {utterance.text[:80]}"
                        f"{'...' if len(utterance.text) > 80 else ''}"
                    )

                # Build episodes
                episode = await episode_builder.process(utterance)

                if episode:
                    episode_count += 1

                    # Extract evidence
                    evidence = episode_processor.extract_evidence(episode)
                    commitments = episode_processor.extract_commitments(episode)
                    decisions = episode_processor.extract_decisions(episode)

                    if args.verbose and (evidence or commitments or decisions):
                        print(f"  -> Evidence: {len(evidence)}, Commitments: {len(commitments)}, Decisions: {len(decisions)}")

            # Flush final episode
            final_episode = await episode_builder.flush()
            if final_episode:
                episode_count += 1

        except KeyboardInterrupt:
            print("\nInterrupted")

        finally:
            await adapter.stop()
            await event_bus.stop()

        # Print summary
        print("-" * 60)
        print(f"\nSummary:")
        print(f"  Utterances processed: {utterance_count}")
        print(f"  Episodes built: {episode_count}")
        print(f"  Adapter stats: {adapter.stats}")
        print(f"  Builder stats: {episode_builder.get_stats()}")

    asyncio.run(run_scenario())
    return 0


def cmd_listen(args: argparse.Namespace) -> int:
    """Run with real audio input (mic + STT)."""
    print("Audio listening mode not yet implemented.")
    print("Use 'rilai synthetic <scenario.jsonl>' for testing.")
    return 1


def cmd_ask(args: argparse.Namespace) -> int:
    """Send an interactive query to the system."""
    from rilai.core.query import UserQueryEvent

    query = UserQueryEvent.create(
        text=args.query,
        context_window=args.context_window,
    )

    print(f"Query: {query.text}")
    print(f"Context window: {query.context_window}s")
    print("\nInteractive query processing not yet implemented.")
    print("This will trigger INTERACTIVE_ASSIST mode and surface relevant suggestions.")
    return 0


def cmd_golden_run(args: argparse.Namespace) -> int:
    """Run a scenario and save outputs for golden testing."""
    from rilai.adapters.protocol import PlaybackMode
    from rilai.adapters.synthetic import ChunkingConfig, SyntheticTextAdapter
    from rilai.brain.episode_builder import EpisodeBuilder, EpisodeBuilderConfig
    from rilai.core.events import event_bus
    from rilai.episodes.processor import EpisodeProcessor

    scenario_path = Path(args.scenario)
    output_dir = Path(args.output)

    if not scenario_path.exists():
        print(f"Error: Scenario file not found: {scenario_path}")
        return 1

    output_dir.mkdir(parents=True, exist_ok=True)

    async def run_and_record() -> None:
        # Initialize components
        adapter = SyntheticTextAdapter(
            scenario_path=scenario_path,
            mode=PlaybackMode.FAST_FORWARD,
            chunking=ChunkingConfig(),
        )

        episode_builder = EpisodeBuilder(
            config=EpisodeBuilderConfig(),
        )

        episode_processor = EpisodeProcessor()

        # Output files
        utterances_file = output_dir / "utterances.jsonl"
        episodes_file = output_dir / "episodes.jsonl"
        evidence_file = output_dir / "evidence_shards.jsonl"
        metadata_file = output_dir / "metadata.json"

        await event_bus.start()
        await adapter.start()

        all_utterances = []
        all_episodes = []
        all_evidence = []

        try:
            async for utterance in adapter.stream():
                all_utterances.append(utterance.to_dict())

                episode = await episode_builder.process(utterance)
                if episode:
                    all_episodes.append(episode.to_dict())

                    evidence = episode_processor.extract_evidence(episode)
                    for shard in evidence:
                        all_evidence.append({
                            "episode_id": episode.episode_id,
                            "type": shard.type,
                            "quote": shard.quote,
                            "confidence": shard.confidence,
                        })

            # Flush final episode
            final_episode = await episode_builder.flush()
            if final_episode:
                all_episodes.append(final_episode.to_dict())

        finally:
            await adapter.stop()
            await event_bus.stop()

        # Write outputs
        with open(utterances_file, "w") as f:
            for item in all_utterances:
                f.write(json.dumps(item) + "\n")

        with open(episodes_file, "w") as f:
            for item in all_episodes:
                f.write(json.dumps(item) + "\n")

        with open(evidence_file, "w") as f:
            for item in all_evidence:
                f.write(json.dumps(item) + "\n")

        metadata = {
            "scenario": str(scenario_path),
            "timestamp": datetime.now().isoformat(),
            "utterance_count": len(all_utterances),
            "episode_count": len(all_episodes),
            "evidence_count": len(all_evidence),
        }
        with open(metadata_file, "w") as f:
            json.dump(metadata, f, indent=2)

        print(f"Golden outputs saved to: {output_dir}")
        print(f"  utterances.jsonl: {len(all_utterances)} items")
        print(f"  episodes.jsonl: {len(all_episodes)} items")
        print(f"  evidence_shards.jsonl: {len(all_evidence)} items")

    asyncio.run(run_and_record())
    return 0


def cmd_golden_compare(args: argparse.Namespace) -> int:
    """Compare run output against golden baseline."""
    run_dir = Path(args.run_dir)
    golden_dir = Path(args.golden_dir)

    if not run_dir.exists():
        print(f"Error: Run directory not found: {run_dir}")
        return 1

    if not golden_dir.exists():
        print(f"Error: Golden directory not found: {golden_dir}")
        return 1

    files_to_compare = ["episodes.jsonl", "evidence_shards.jsonl"]
    all_passed = True

    for filename in files_to_compare:
        run_file = run_dir / filename
        golden_file = golden_dir / filename

        if not run_file.exists():
            print(f"MISSING: {filename} not in run output")
            all_passed = False
            continue

        if not golden_file.exists():
            print(f"MISSING: {filename} not in golden baseline")
            all_passed = False
            continue

        # Load and compare
        with open(run_file) as f:
            run_lines = [json.loads(line) for line in f if line.strip()]

        with open(golden_file) as f:
            golden_lines = [json.loads(line) for line in f if line.strip()]

        if len(run_lines) != len(golden_lines):
            print(f"DIFF: {filename} - count mismatch (run: {len(run_lines)}, golden: {len(golden_lines)})")
            all_passed = False
        else:
            print(f"OK: {filename} - {len(run_lines)} items match")

    return 0 if all_passed else 1


def cmd_golden_update(args: argparse.Namespace) -> int:
    """Update golden baseline from run output."""
    import shutil

    run_dir = Path(args.run_dir)
    golden_dir = Path(args.golden_dir)

    if not run_dir.exists():
        print(f"Error: Run directory not found: {run_dir}")
        return 1

    golden_dir.mkdir(parents=True, exist_ok=True)

    files_to_copy = ["utterances.jsonl", "episodes.jsonl", "evidence_shards.jsonl", "metadata.json"]

    for filename in files_to_copy:
        src = run_dir / filename
        if src.exists():
            shutil.copy(src, golden_dir / filename)
            print(f"Updated: {filename}")

    print(f"\nGolden baseline updated at: {golden_dir}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Show system status."""
    from rilai.config import get_config

    config = get_config()

    print("Rilai v2 Status - Ambient Listening Mode")
    print("=" * 50)

    # Config status
    errors = config.validate()
    if errors:
        print("\nConfiguration errors:")
        for error in errors:
            print(f"  - {error}")
    else:
        print("\nConfiguration: OK")

    # Models
    print("\nModels:")
    for tier, model in config.MODELS.items():
        print(f"  {tier}: {model}")

    # Ambient settings
    print("\nAmbient Mode:")
    print(f"  Enabled: {getattr(config, 'AMBIENT_ENABLED', False)}")
    print(f"  Daydream timeout: {getattr(config, 'AMBIENT_DAYDREAM_TIMEOUT_S', 60)}s")
    print(f"  Stakes threshold: {getattr(config, 'AMBIENT_STAKES_THRESHOLD', 0.7)}")

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

    elif target == "all":
        confirm = input("This will delete ALL data. Continue? [y/N] ")
        if confirm.lower() == "y":
            if data_dir.exists():
                import shutil
                shutil.rmtree(data_dir)
                data_dir.mkdir(parents=True)
            print("Cleared all data")
        else:
            print("Cancelled")

    return 0


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        prog="rilai",
        description="Rilai v2 - Ambient Cognitive Co-Processor",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s 2.0.0",
    )

    subparsers = parser.add_subparsers(dest="command")

    # rilai synthetic <scenario.jsonl>
    synthetic_parser = subparsers.add_parser(
        "synthetic",
        help="Run synthetic scenario from JSONL file",
    )
    synthetic_parser.add_argument(
        "scenario",
        help="Path to JSONL scenario file",
    )
    synthetic_parser.add_argument(
        "--mode",
        choices=["fast", "realtime"],
        default="fast",
        help="Playback mode (default: fast)",
    )
    synthetic_parser.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="Speed multiplier for realtime mode (default: 1.0)",
    )
    synthetic_parser.add_argument(
        "--chunk-max-chars",
        type=int,
        default=120,
        dest="chunk_max_chars",
        help="Max chars per chunk for STT simulation (default: 120)",
    )
    synthetic_parser.add_argument(
        "--merge-window-sec",
        type=float,
        default=3.0,
        dest="merge_window_sec",
        help="Merge window for same-speaker utterances (default: 3.0)",
    )
    synthetic_parser.add_argument(
        "--gap-threshold-ms",
        type=int,
        default=30000,
        dest="gap_threshold_ms",
        help="Silence gap to trigger episode boundary (default: 30000)",
    )
    synthetic_parser.add_argument(
        "--no-chunking",
        action="store_true",
        help="Disable STT chunking simulation",
    )
    synthetic_parser.add_argument(
        "--no-merging",
        action="store_true",
        help="Disable same-speaker merging",
    )
    synthetic_parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output (show each utterance)",
    )
    synthetic_parser.set_defaults(func=cmd_synthetic)

    # rilai listen
    listen_parser = subparsers.add_parser(
        "listen",
        help="Run with real audio input (mic + STT)",
    )
    listen_parser.set_defaults(func=cmd_listen)

    # rilai ask "<query>"
    ask_parser = subparsers.add_parser(
        "ask",
        help="Send interactive query to the system",
    )
    ask_parser.add_argument(
        "query",
        help="The query text",
    )
    ask_parser.add_argument(
        "--context-window",
        type=int,
        default=3600,
        dest="context_window",
        help="Seconds of ambient context to include (default: 3600)",
    )
    ask_parser.set_defaults(func=cmd_ask)

    # rilai golden run
    golden_run_parser = subparsers.add_parser(
        "golden-run",
        help="Run scenario and save outputs for golden testing",
    )
    golden_run_parser.add_argument(
        "scenario",
        help="Path to JSONL scenario file",
    )
    golden_run_parser.add_argument(
        "--output",
        default="runs/latest",
        help="Output directory (default: runs/latest)",
    )
    golden_run_parser.set_defaults(func=cmd_golden_run)

    # rilai golden compare
    golden_compare_parser = subparsers.add_parser(
        "golden-compare",
        help="Compare run output against golden baseline",
    )
    golden_compare_parser.add_argument(
        "run_dir",
        help="Path to run output directory",
    )
    golden_compare_parser.add_argument(
        "golden_dir",
        help="Path to golden baseline directory",
    )
    golden_compare_parser.set_defaults(func=cmd_golden_compare)

    # rilai golden update
    golden_update_parser = subparsers.add_parser(
        "golden-update",
        help="Update golden baseline from run output",
    )
    golden_update_parser.add_argument(
        "run_dir",
        help="Path to run output directory",
    )
    golden_update_parser.add_argument(
        "golden_dir",
        help="Path to golden baseline directory",
    )
    golden_update_parser.set_defaults(func=cmd_golden_update)

    # rilai status
    status_parser = subparsers.add_parser("status", help="Show system status")
    status_parser.set_defaults(func=cmd_status)

    # rilai clear
    clear_parser = subparsers.add_parser("clear", help="Clear data")
    clear_parser.add_argument(
        "target",
        choices=["current", "all"],
        help="What to clear",
    )
    clear_parser.set_defaults(func=cmd_clear)

    args = parser.parse_args()

    # Show help if no command
    if args.command is None:
        parser.print_help()
        return 0

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
