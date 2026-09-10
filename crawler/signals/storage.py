"""Persistence, watermarking, and deduplication for Phase II signals."""

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Union
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from crawler.logging import logger
from crawler.models.db import (
    JobRecordModel,
    NewsRecordModel,
    SourceCrawlStateModel,
    SourceRunHistoryModel,
)
from crawler.signals.models import JobRecord, NewsRecord, RunSummary
from crawler.signals.url_canonicalizer import compute_url_hash


class SignalStorage:
    """Manages database persistence, deduplication, and watermarking for signals."""

    def __init__(self, max_memory_entries: int = 500_000):
        self._max_memory_entries = max_memory_entries
        self._seen_content_hashes: Set[str] = set()
        self._seen_url_keys: Set[str] = set()  # "source_id:url_hash"

    def _make_url_key(self, source_id: str, url_hash: str) -> str:
        return f"{source_id}:{url_hash}"

    async def get_crawl_state(self, session: AsyncSession, source_id: str) -> Optional[SourceCrawlStateModel]:
        """Loads persistent crawl state for a source."""
        stmt = select(SourceCrawlStateModel).where(SourceCrawlStateModel.source_id == source_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def record_attempt(self, session: AsyncSession, source_id: str, attempt_time: datetime) -> None:
        """Records crawl attempt watermark without advancing successful crawl timestamp."""
        state = await self.get_crawl_state(session, source_id)
        if state is None:
            state = SourceCrawlStateModel(
                source_id=source_id,
                last_attempted_crawl_at=attempt_time,
                updated_at=datetime.now(timezone.utc),
            )
            session.add(state)
        else:
            state.last_attempted_crawl_at = attempt_time
            state.updated_at = datetime.now(timezone.utc)
        await session.commit()

    async def advance_successful_watermark(
        self,
        session: AsyncSession,
        source_id: str,
        success_time: datetime,
        observed_url_hashes: Set[str],
        boundary_item_id: Optional[str] = None,
        ingested_count: int = 0,
    ) -> None:
        """Advances successful watermark only upon complete, error-free ingestion run."""
        state = await self.get_crawl_state(session, source_id)
        # Cap snapshot size to recent 5000 hashes
        snapshot_list = list(observed_url_hashes)[-5000:]
        snapshot_json = json.dumps(snapshot_list)

        if state is None:
            state = SourceCrawlStateModel(
                source_id=source_id,
                last_successful_crawl_at=success_time,
                last_attempted_crawl_at=success_time,
                last_boundary_item_id=boundary_item_id,
                observed_urls_snapshot=snapshot_json,
                total_ingested=ingested_count,
                updated_at=datetime.now(timezone.utc),
            )
            session.add(state)
        else:
            state.last_successful_crawl_at = success_time
            state.last_attempted_crawl_at = success_time
            state.last_boundary_item_id = boundary_item_id
            state.observed_urls_snapshot = snapshot_json
            state.total_ingested = (state.total_ingested or 0) + ingested_count
            state.updated_at = datetime.now(timezone.utc)

        await session.commit()

    async def save_news_record(self, session: AsyncSession, record: NewsRecord) -> bool:
        """Saves or idempotently updates a news record. Returns True if inserted/updated."""
        url_hash = compute_url_hash(record.canonicalUrl)
        url_key = self._make_url_key(record.sourceId, url_hash)

        # Primary check: (source_id, canonical_url_hash)
        stmt = select(NewsRecordModel).where(
            NewsRecordModel.source_id == record.sourceId,
            NewsRecordModel.canonical_url_hash == url_hash,
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()

        pub_dt = None
        if record.publishedAt:
            try:
                pub_dt = datetime.fromisoformat(record.publishedAt)
            except Exception:
                pass

        first_seen_dt = datetime.fromisoformat(record.firstSeenAt)
        ingested_dt = datetime.fromisoformat(record.ingestedAt)

        if existing:
            # Idempotent update: update fields if content changed, don't duplicate
            existing.title = record.title
            existing.author = record.author
            existing.full_text = record.fullText
            existing.summary = record.summary
            existing.published_at = pub_dt
            existing.date_extraction_method = record.dateExtractionMethod
            existing.published_at_confidence = record.publishedAtConfidence
            existing.freshness_decision = record.freshnessDecision
            existing.freshness_reason = record.freshnessReason
            existing.content_hash = record.contentHash
            existing.raw_metadata = json.dumps(record.rawMetadata)
            await session.commit()
            self._seen_url_keys.add(url_key)
            self._seen_content_hashes.add(record.contentHash)
            return True

        # Secondary check: content_hash uniqueness
        stmt_hash = select(NewsRecordModel.id).where(NewsRecordModel.content_hash == record.contentHash)
        if (await session.execute(stmt_hash)).scalar_one_or_none():
            return False

        db_model = NewsRecordModel(
            id=record.id,
            source_id=record.sourceId,
            canonical_url=record.canonicalUrl,
            canonical_url_hash=url_hash,
            title=record.title,
            author=record.author,
            full_text=record.fullText,
            summary=record.summary,
            published_at=pub_dt,
            first_seen_at=first_seen_dt,
            ingested_at=ingested_dt,
            date_extraction_method=record.dateExtractionMethod,
            published_at_confidence=record.publishedAtConfidence,
            freshness_decision=record.freshnessDecision,
            freshness_reason=record.freshnessReason,
            content_hash=record.contentHash,
            raw_metadata=json.dumps(record.rawMetadata),
        )

        try:
            session.add(db_model)
            await session.commit()
            self._seen_url_keys.add(url_key)
            self._seen_content_hashes.add(record.contentHash)
            return True
        except IntegrityError:
            await session.rollback()
            return False

    async def save_job_record(self, session: AsyncSession, record: JobRecord) -> bool:
        """Saves or idempotently updates a job record. Returns True if inserted/updated."""
        url_hash = compute_url_hash(record.canonicalUrl)
        url_key = self._make_url_key(record.sourceId, url_hash)

        stmt = select(JobRecordModel).where(
            JobRecordModel.source_id == record.sourceId,
            JobRecordModel.canonical_url_hash == url_hash,
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()

        pub_dt = None
        if record.publishedAt:
            try:
                pub_dt = datetime.fromisoformat(record.publishedAt)
            except Exception:
                pass

        first_seen_dt = datetime.fromisoformat(record.firstSeenAt)
        ingested_dt = datetime.fromisoformat(record.ingestedAt)

        if existing:
            existing.title = record.title
            existing.company = record.company
            existing.location = record.location
            existing.employment_type = record.employmentType
            existing.salary = record.salary
            existing.description_full_text = record.descriptionFullText
            existing.published_at = pub_dt
            existing.date_extraction_method = record.dateExtractionMethod
            existing.published_at_confidence = record.publishedAtConfidence
            existing.freshness_decision = record.freshnessDecision
            existing.freshness_reason = record.freshnessReason
            existing.content_hash = record.contentHash
            existing.raw_metadata = json.dumps(record.rawMetadata)
            await session.commit()
            self._seen_url_keys.add(url_key)
            self._seen_content_hashes.add(record.contentHash)
            return True

        stmt_hash = select(JobRecordModel.id).where(JobRecordModel.content_hash == record.contentHash)
        if (await session.execute(stmt_hash)).scalar_one_or_none():
            return False

        db_model = JobRecordModel(
            id=record.id,
            source_id=record.sourceId,
            canonical_url=record.canonicalUrl,
            canonical_url_hash=url_hash,
            title=record.title,
            company=record.company,
            location=record.location,
            employment_type=record.employmentType,
            salary=record.salary,
            description_full_text=record.descriptionFullText,
            published_at=pub_dt,
            first_seen_at=first_seen_dt,
            ingested_at=ingested_dt,
            date_extraction_method=record.dateExtractionMethod,
            published_at_confidence=record.publishedAtConfidence,
            freshness_decision=record.freshnessDecision,
            freshness_reason=record.freshnessReason,
            content_hash=record.contentHash,
            raw_metadata=json.dumps(record.rawMetadata),
        )

        try:
            session.add(db_model)
            await session.commit()
            self._seen_url_keys.add(url_key)
            self._seen_content_hashes.add(record.contentHash)
            return True
        except IntegrityError:
            await session.rollback()
            return False

    async def save_run_history(self, session: AsyncSession, summary: RunSummary) -> None:
        """Persists run execution summary and metrics."""
        history = SourceRunHistoryModel(
            run_id=summary.run_id,
            source_id=summary.source_id,
            status=summary.status,
            started_at=datetime.fromisoformat(summary.started_at),
            completed_at=datetime.fromisoformat(summary.completed_at),
            candidates_discovered=summary.candidates_discovered,
            candidates_fetched=summary.candidates_fetched,
            accepted_count=summary.accepted_count,
            rejected_count=summary.rejected_count,
            error_count=summary.error_count,
            summary_json=json.dumps(summary.model_dump(), default=str),
        )
        session.add(history)
        await session.commit()


signal_storage = SignalStorage()
