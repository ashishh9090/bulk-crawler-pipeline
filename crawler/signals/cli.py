"""CLI entry point for Phase II high-fidelity signal ingestion."""

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from crawler.logging import logger, setup_logging
from crawler.signals.config import load_sources_config, signal_settings
from crawler.signals.orchestrator import SignalOrchestrator


def parse_args():
    parser = argparse.ArgumentParser(
        description="Phase II: High-Fidelity Signal Ingestion Pipeline"
    )
    parser.add_argument(
        "--sources",
        type=str,
        default="all",
        help="Comma-separated source IDs to ingest, or 'all' (default: all)",
    )
    parser.add_argument(
        "--type",
        choices=["all", "news", "job"],
        default="all",
        help="Filter sources by type: news, job, or all (default: all)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Candidate discovery limit per source (default: 20)",
    )
    parser.add_argument(
        "--freshness-hours",
        type=int,
        default=24,
        help="Freshness window in hours (default: 24)",
    )
    parser.add_argument(
        "--log-format",
        choices=["json", "console"],
        default="console",
        help="Log format: json or console (default: console)",
    )
    return parser.parse_args()


async def run_pipeline(args):
    setup_logging(log_format=args.log_format)

    all_sources = load_sources_config()
    source_ids = None
    if args.sources != "all":
        source_ids = [s.strip() for s in args.sources.split(",") if s.strip()]

    source_type = None if args.type == "all" else args.type

    signal_settings.freshness_window_hours = args.freshness_hours
    orchestrator = SignalOrchestrator(settings=signal_settings, sources=all_sources)

    logger.info("Starting Phase II Ingestion Pipeline...")
    ref_time = datetime.now(timezone.utc)

    try:
        results = await orchestrator.run_sources(
            source_ids=source_ids,
            source_type=source_type,
            limit_per_source=args.limit,
            reference_time=ref_time,
        )

        print("\n" + "=" * 80)
        print(f"SIGNAL INGESTION RUN SUMMARY (Ref UTC: {ref_time.isoformat()})")
        print("=" * 80)
        print(f"{'Source ID':<25} {'Status':<10} {'Discovered':<12} {'Fetched':<10} {'Accepted':<10} {'Rejected':<10} {'Latency (ms)'}")
        print("-" * 80)

        total_accepted = 0
        total_rejected = 0
        total_errors = 0

        for sid, summary in results.items():
            print(
                f"{sid:<25} {summary.status:<10} {summary.candidates_discovered:<12} "
                f"{summary.candidates_fetched:<10} {summary.accepted_count:<10} "
                f"{summary.rejected_count:<10} {summary.latency_ms}"
            )
            total_accepted += summary.accepted_count
            total_rejected += summary.rejected_count
            total_errors += summary.error_count

        print("-" * 80)
        print(f"TOTALS: Accepted={total_accepted} | Rejected={total_rejected} | Errors={total_errors}")
        print("=" * 80 + "\n")

    finally:
        await orchestrator.close()


def main():
    args = parse_args()
    try:
        asyncio.run(run_pipeline(args))
    except (KeyboardInterrupt, SystemExit):
        logger.warning("Pipeline interrupted by user.")


if __name__ == "__main__":
    main()
