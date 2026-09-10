"""Production-grade asynchronous bulk crawler orchestrator."""

import argparse
import asyncio
import signal
import sys
import time
from typing import Dict, List, Optional
from sqlalchemy import func, select
from crawler.adapters import get_adapter, get_all_adapters
from crawler.adapters.base import BaseAdapter
from crawler.checkpoint import checkpoint_manager
from crawler.config import settings
from crawler.deduplication import deduplicator
from crawler.export.exporter import DataExporter
from crawler.http_client import http_client
from crawler.logging import logger, setup_logging
from crawler.models.db import RecordModel, create_engine_and_session, init_database
from crawler.models.schemas import RecordType
from crawler.queue import BoundedAsyncQueue, CrawlTask


class CrawlerPipeline:
    """Coordinates URL discovery, worker queue, deduplication, storage, and shutdown."""

    def __init__(
        self,
        concurrency: int | None = None,
        target_limit: int | None = None,
        selected_type: str = "all",
    ):
        self.concurrency = concurrency or settings.concurrency_limit
        self.target_limit = target_limit if target_limit is not None else settings.target_records_per_type
        self.selected_type = selected_type.lower()
        self.queue = BoundedAsyncQueue(maxsize=10000)
        self.stop_event = asyncio.Event()
        self.engine, self.session_factory = create_engine_and_session()
        self.exporter = DataExporter()

        # Metrics
        self.total_processed = 0
        self.total_saved = 0
        self.total_duplicates = 0
        self.total_errors = 0

    def _setup_signal_handlers(self) -> None:
        """Attaches OS signal handlers for graceful shutdown."""
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(self.shutdown(s)))
            except NotImplementedError:
                # Windows fallback
                pass

    async def shutdown(self, sig: Optional[signal.Signals] = None) -> None:
        """Gracefully halts workers and flushes state."""
        if self.stop_event.is_set():
            return
        logger.warning(
            "Shutdown signal %s received. Draining workers gracefully...",
            sig.name if sig else "INTERNAL",
        )
        self.stop_event.set()

    def _resolve_adapters(self) -> List[BaseAdapter]:
        """Resolves active adapters based on selected_type."""
        all_adapters = get_all_adapters()
        if self.selected_type == "all":
            return list(all_adapters.values())

        type_mapping = {
            "paper": "arxiv_papers",
            "research_paper": "arxiv_papers",
            "startup": "startups",
            "startups": "startups",
            "product": "products",
            "products": "products",
        }
        key = type_mapping.get(self.selected_type, self.selected_type)
        return [get_adapter(key)]

    async def producer(self, adapter: BaseAdapter) -> None:
        """Discovers target URLs and enqueues work tasks."""
        logger.info(
            "Producer started for %s (target limit: %d)",
            adapter.name,
            self.target_limit,
        )
        count = 0
        async with self.session_factory() as session:
            try:
                async for task in adapter.discover(session, limit=self.target_limit):
                    if self.stop_event.is_set():
                        break
                    await self.queue.put(task)
                    count += 1
            except Exception as exc:
                logger.error("Error in producer for %s: %s", adapter.name, exc)

        logger.info("Producer finished for %s. Enqueued %d tasks.", adapter.name, count)

    async def worker(self, worker_id: int) -> None:
        """Consumer worker processing queue items through fetch, parse, validate, and deduplicate."""
        adapters = get_all_adapters()

        while not self.stop_event.is_set():
            try:
                task = await asyncio.wait_for(self.queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                if self.stop_event.is_set() or self.queue.empty():
                    break
                continue

            if task is None:
                self.queue.task_done()
                break

            adapter = adapters.get(task.adapter_name)
            if not adapter:
                logger.error("Unknown adapter: %s", task.adapter_name)
                self.queue.task_done()
                continue

            try:
                # 1. Fetch response
                response_text = await http_client.fetch(task.url)

                # 2. Parse and Validate
                items_saved = 0
                async with self.session_factory() as session:
                    async for record, raw_dict in adapter.parse(response_text, task):
                        # 3. Deduplicate and Save to DB
                        saved = await deduplicator.check_and_save_record(
                            session, record, raw_dict
                        )
                        if saved:
                            items_saved += 1
                            self.total_saved += 1
                        else:
                            self.total_duplicates += 1

                    # 4. Checkpoint pagination state if applicable
                    if "offset" in task.metadata:
                        await checkpoint_manager.update_checkpoint(
                            session=session,
                            adapter_name=adapter.name,
                            offset_val=task.metadata["offset"] + task.metadata.get("batch_count", 0),
                            increment_collected=items_saved,
                        )

                self.total_processed += 1
                if self.total_saved % 50 == 0 and self.total_saved > 0:
                    logger.info(
                        "Progress: Saved %d unique records | Duplicates: %d | Queue: %d",
                        self.total_saved,
                        self.total_duplicates,
                        self.queue.qsize(),
                    )

            except Exception as exc:
                self.total_errors += 1
                logger.warning(
                    "Worker %d error on %s: %s",
                    worker_id,
                    task.url,
                    exc,
                    extra={"worker_id": worker_id, "url": task.url},
                )
            finally:
                self.queue.task_done()

    async def run(self, export_format: str = "json") -> Dict[str, int]:
        """Runs the producer-consumer crawling pipeline to completion."""
        start_time = time.time()
        self._setup_signal_handlers()

        # Initialize storage schema
        await init_database(self.engine)
        active_adapters = self._resolve_adapters()

        logger.info(
            "Launching pipeline with %d workers for targets: %s (limit: %d)",
            self.concurrency,
            [a.name for a in active_adapters],
            self.target_limit,
        )

        # Spawn producers
        producers = [asyncio.create_task(self.producer(adp)) for adp in active_adapters]

        # Spawn workers
        workers = [
            asyncio.create_task(self.worker(wid))
            for wid in range(1, self.concurrency + 1)
        ]

        # Wait for all producers to finish discovery
        await asyncio.gather(*producers, return_exceptions=True)

        # Wait for queue to drain or stop event
        while not self.queue.empty() and not self.stop_event.is_set():
            await asyncio.sleep(0.5)

        # Stop workers
        self.stop_event.set()
        for _ in range(self.concurrency):
            await self.queue.put(None)

        await asyncio.gather(*workers, return_exceptions=True)

        # Close network resources
        await http_client.close()

        elapsed = round(time.time() - start_time, 2)
        logger.info(
            "Pipeline finished in %ss. Total Saved: %d | Duplicates: %d | Errors: %d",
            elapsed,
            self.total_saved,
            self.total_duplicates,
            self.total_errors,
        )

        # Perform Export
        async with self.session_factory() as session:
            exported_paths = await self.exporter.export_records(session, export_format=export_format)
            for key, path in exported_paths.items():
                logger.info("Export file available: %s -> %s", key, path)

            # Query database totals
            counts = {}
            for rtype in RecordType:
                stmt = select(func.count(RecordModel.id)).where(RecordModel.record_type == rtype.value)
                cnt = (await session.execute(stmt)).scalar() or 0
                counts[rtype.value] = cnt
                logger.info("Database totals: %s = %d", rtype.value, cnt)

        await self.engine.dispose()
        return counts


def main() -> None:
    """CLI entry point for bulk crawler execution."""
    parser = argparse.ArgumentParser(
        description="High-Concurrency Bulk Data Acquisition Pipeline (Phase I)"
    )
    parser.add_argument(
        "--type",
        choices=["all", "paper", "startup", "product"],
        default="all",
        help="Target data entity type to crawl (default: all)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=settings.target_records_per_type,
        help="Target number of records to collect per adapter (default: 1000)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=settings.concurrency_limit,
        help=f"Number of concurrent async workers (default: {settings.concurrency_limit})",
    )
    parser.add_argument(
        "--export",
        choices=["json", "csv", "jsonl", "all"],
        default="all",
        help="Export format for acquired data (default: all)",
    )
    parser.add_argument(
        "--log-format",
        choices=["json", "console"],
        default=settings.log_format,
        help="Log output format (default: json)",
    )

    args = parser.parse_args()
    setup_logging(log_format=args.log_format)

    pipeline = CrawlerPipeline(
        concurrency=args.workers,
        target_limit=args.limit,
        selected_type=args.type,
    )

    try:
        asyncio.run(pipeline.run(export_format=args.export))
    except (KeyboardInterrupt, SystemExit):
        logger.warning("Execution interrupted by user.")


if __name__ == "__main__":
    main()
