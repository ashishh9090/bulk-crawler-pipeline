"""Signal Ingestion Orchestrator for Phase II."""

import asyncio
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from crawler.http_client import HttpClient, http_client as default_http_client
from crawler.logging import logger
from crawler.models.db import create_engine_and_session, init_database
from crawler.signals.adapters import get_signal_adapter
from crawler.signals.config import (
    SignalSettings,
    SourceConfig,
    load_sources_config,
    signal_settings as default_settings,
)
from crawler.signals.freshness_gate import FreshnessGate
from crawler.signals.models import FreshnessDecision, RunSummary
from crawler.signals.robots import RobotsChecker
from crawler.signals.storage import SignalStorage, signal_storage as default_storage
from crawler.signals.url_canonicalizer import compute_url_hash


class SignalOrchestrator:
    """Coordinates high-fidelity ingestion across configured AI news and job sources."""

    def __init__(
        self,
        settings: Optional[SignalSettings] = None,
        sources: Optional[List[SourceConfig]] = None,
        storage: Optional[SignalStorage] = None,
        http_client: Optional[HttpClient] = None,
        engine: Optional[AsyncEngine] = None,
        session_factory: Optional[async_sessionmaker[AsyncSession]] = None,
        robots_checker: Optional[RobotsChecker] = None,
    ):
        self.settings = settings or default_settings
        self.sources = sources or load_sources_config()
        self.storage = storage or default_storage
        self.http_client = http_client or default_http_client
        self.robots_checker = robots_checker or RobotsChecker()

        if engine and session_factory:
            self.engine = engine
            self.session_factory = session_factory
        else:
            self.engine, self.session_factory = create_engine_and_session()

        # In-memory run locks per source to prevent overlapping runs
        self._source_locks: Dict[str, asyncio.Lock] = {}
        self._lock_guard = asyncio.Lock()

    async def _get_source_lock(self, source_id: str) -> asyncio.Lock:
        async with self._lock_guard:
            if source_id not in self._source_locks:
                self._source_locks[source_id] = asyncio.Lock()
            return self._source_locks[source_id]

    async def ingest_source(
        self,
        source: SourceConfig,
        limit: int = 50,
        reference_time: Optional[datetime] = None,
    ) -> RunSummary:
        """Runs the ingestion pipeline for a single source with strict fault isolation."""
        source_lock = await self._get_source_lock(source.id)
        if source_lock.locked():
            logger.warning(
                "Source %s is already running. Skipping to prevent overlapping execution.",
                source.id,
                extra={"source_id": source.id, "status": "SKIPPED_LOCKED"},
            )
            now_iso = datetime.now(timezone.utc).isoformat()
            return RunSummary(
                source_id=source.id,
                run_id=f"skipped_{source.id}_{int(time.time())}",
                status="SKIPPED_LOCKED",
                started_at=now_iso,
                completed_at=now_iso,
                errors=["Source execution skipped due to active lock."],
            )

        async with source_lock:
            start_wall = time.monotonic()
            run_id = f"run_{source.id}_{int(time.time())}_{uuid.uuid4().hex[:6]}"
            ref_time = reference_time or datetime.now(timezone.utc)
            if ref_time.tzinfo is None:
                ref_time = ref_time.replace(tzinfo=timezone.utc)

            started_at_str = ref_time.isoformat()

            summary = RunSummary(
                source_id=source.id,
                run_id=run_id,
                status="RUNNING",
                started_at=started_at_str,
                completed_at=started_at_str,
            )

            logger.info(
                "Starting signal ingestion for source: %s [%s] (run: %s, limit: %d)",
                source.name,
                source.type,
                run_id,
                limit,
                extra={"source_id": source.id, "run_id": run_id, "type": source.type},
            )

            adapter = get_signal_adapter(source)
            freshness_gate = FreshnessGate(
                reference_time=ref_time,
                freshness_window_hours=self.settings.freshness_window_hours,
                clock_skew_minutes=self.settings.clock_skew_tolerance_minutes,
            )

            session = await self.http_client.get_session()
            observed_hashes: Set[str] = set()
            boundary_item_id: Optional[str] = None
            first_candidate_recorded = False

            try:
                # 1. Record attempt in storage
                async with self.session_factory() as db_session:
                    await self.storage.record_attempt(db_session, source.id, ref_time)
                    crawl_state = await self.storage.get_crawl_state(db_session, source.id)

                # 2. Discover candidates
                candidates = []
                try:
                    async for candidate in adapter.discover_candidates(session, self.http_client, limit=limit):
                        candidates.append(candidate)
                except Exception as disc_err:
                    summary.error_count += 1
                    summary.errors.append(f"Discovery error: {str(disc_err)}")
                    logger.error("Error discovering candidates for %s: %s", source.id, disc_err)

                summary.candidates_discovered = len(candidates)

                # 3. Process each candidate
                for cand in candidates:
                    # Check robots.txt if enabled
                    if self.settings.honor_robots_txt:
                        can_fetch = await self.robots_checker.can_fetch(
                            cand.raw_url, self.settings.user_agent, session
                        )
                        if not can_fetch:
                            summary.rejected_count += 1
                            reason_key = "robots_txt_disallowed"
                            summary.rejection_breakdown[reason_key] = summary.rejection_breakdown.get(reason_key, 0) + 1
                            logger.debug("Skipping %s due to robots.txt", cand.raw_url)
                            continue

                    # Rate limit polite delay
                    if source.rate_limit_delay > 0:
                        await asyncio.sleep(source.rate_limit_delay)

                    try:
                        summary.candidates_fetched += 1
                        record, evaluation = await adapter.extract_record(
                            candidate=cand,
                            session=session,
                            client=self.http_client,
                            freshness_gate=freshness_gate,
                            crawl_state=crawl_state,
                        )

                        # Record first item as boundary marker
                        if not first_candidate_recorded and record is not None:
                            boundary_item_id = record.canonicalUrl
                            first_candidate_recorded = True

                        if record is not None and evaluation.decision in (
                            FreshnessDecision.ACCEPTED_VERIFIED,
                            FreshnessDecision.ACCEPTED_INFERRED,
                        ):
                            # Save to database
                            async with self.session_factory() as db_session:
                                if source.type == "news":
                                    saved = await self.storage.save_news_record(db_session, record)
                                else:
                                    saved = await self.storage.save_job_record(db_session, record)

                            if saved:
                                summary.accepted_count += 1
                                observed_hashes.add(compute_url_hash(record.canonicalUrl))
                                observed_hashes.add(record.contentHash)

                            logger.info(
                                "Item ACCEPTED: [%s] '%s' (decision=%s, method=%s, conf=%.2f)",
                                source.id,
                                record.title[:60],
                                evaluation.decision.value,
                                record.dateExtractionMethod,
                                record.publishedAtConfidence,
                                extra={
                                    "source_id": source.id,
                                    "run_id": run_id,
                                    "url": record.canonicalUrl,
                                    "decision": evaluation.decision.value,
                                    "method": record.dateExtractionMethod,
                                    "confidence": record.publishedAtConfidence,
                                },
                            )
                        else:
                            summary.rejected_count += 1
                            reason_key = evaluation.decision.value
                            summary.rejection_breakdown[reason_key] = summary.rejection_breakdown.get(reason_key, 0) + 1
                            logger.info(
                                "Item REJECTED: [%s] '%s' (decision=%s, reason=%s)",
                                source.id,
                                (cand.title or cand.raw_url)[:60],
                                evaluation.decision.value,
                                evaluation.reason,
                                extra={
                                    "source_id": source.id,
                                    "run_id": run_id,
                                    "url": cand.raw_url,
                                    "decision": evaluation.decision.value,
                                    "reason": evaluation.reason,
                                },
                            )

                    except Exception as item_err:
                        summary.error_count += 1
                        summary.errors.append(f"Error processing {cand.raw_url}: {str(item_err)}")
                        logger.warning("Failed processing candidate %s: %s", cand.raw_url, item_err)

                # Determine final status
                if summary.error_count == 0:
                    summary.status = "SUCCESS"
                elif summary.candidates_fetched > 0 and summary.accepted_count > 0:
                    summary.status = "PARTIAL"
                else:
                    summary.status = "FAILED"

                # Advance watermark ONLY on clean SUCCESS
                if summary.status == "SUCCESS":
                    async with self.session_factory() as db_session:
                        await self.storage.advance_successful_watermark(
                            session=db_session,
                            source_id=source.id,
                            success_time=ref_time,
                            observed_url_hashes=observed_hashes,
                            boundary_item_id=boundary_item_id,
                            ingested_count=summary.accepted_count,
                        )
                    logger.info("Advanced successful watermark for %s to %s", source.id, ref_time.isoformat())
                else:
                    logger.warning(
                        "Crawl for %s finished with status %s. Watermark was NOT advanced.",
                        source.id,
                        summary.status,
                    )

            except Exception as unhandled:
                summary.status = "FAILED"
                summary.error_count += 1
                summary.errors.append(f"Fatal source run failure: {str(unhandled)}")
                logger.error("Fatal failure in source run for %s: %s", source.id, unhandled)

            finally:
                completed_at = datetime.now(timezone.utc)
                summary.completed_at = completed_at.isoformat()
                summary.latency_ms = round((time.monotonic() - start_wall) * 1000, 2)

                # Persist run history
                try:
                    async with self.session_factory() as db_session:
                        await self.storage.save_run_history(db_session, summary)
                except Exception as hist_err:
                    logger.error("Failed saving run history: %s", hist_err)

                logger.info(
                    "Source %s run complete in %sms: status=%s, discovered=%d, fetched=%d, accepted=%d, rejected=%d, errors=%d",
                    source.id,
                    summary.latency_ms,
                    summary.status,
                    summary.candidates_discovered,
                    summary.candidates_fetched,
                    summary.accepted_count,
                    summary.rejected_count,
                    summary.error_count,
                    extra={
                        "source_id": source.id,
                        "run_id": run_id,
                        "status": summary.status,
                        "latency_ms": summary.latency_ms,
                        "accepted": summary.accepted_count,
                        "rejected": summary.rejected_count,
                    },
                )

            return summary

    async def run_sources(
        self,
        source_ids: Optional[List[str]] = None,
        source_type: Optional[str] = None,
        limit_per_source: int = 50,
        reference_time: Optional[datetime] = None,
    ) -> Dict[str, RunSummary]:
        """Runs multiple sources with concurrency and per-source failure isolation."""
        await init_database(self.engine)

        target_sources = self.sources
        if source_ids:
            target_sources = [s for s in target_sources if s.id in source_ids]
        if source_type:
            target_sources = [s for s in target_sources if s.type == source_type]

        if not target_sources:
            logger.warning("No matching sources found to run.")
            return {}

        logger.info(
            "Launching signal ingestion for %d sources: %s",
            len(target_sources),
            [s.id for s in target_sources],
        )

        ref_time = reference_time or datetime.now(timezone.utc)
        results: Dict[str, RunSummary] = {}

        # Run sources concurrently, isolating errors
        async def _run_safe(source: SourceConfig) -> RunSummary:
            try:
                return await self.ingest_source(source, limit=limit_per_source, reference_time=ref_time)
            except Exception as exc:
                logger.error("Unhandled top-level error running source %s: %s", source.id, exc)
                now_str = datetime.now(timezone.utc).isoformat()
                return RunSummary(
                    source_id=source.id,
                    run_id=f"failed_{source.id}_{int(time.time())}",
                    status="FAILED",
                    started_at=now_str,
                    completed_at=now_str,
                    error_count=1,
                    errors=[str(exc)],
                )

        tasks = [_run_safe(source) for source in target_sources]
        summaries = await asyncio.gather(*tasks, return_exceptions=False)

        for summary in summaries:
            results[summary.source_id] = summary

        return results

    async def close(self) -> None:
        """Releases underlying network and database pool resources."""
        await self.http_client.close()
        await self.engine.dispose()
