"""Unit and integration tests for storage, deduplication, and watermarking."""

import json
from datetime import datetime, timezone
import pytest
from sqlalchemy import func, select
from crawler.models.db import JobRecordModel, NewsRecordModel, SourceCrawlStateModel
from crawler.signals.models import JobRecord, NewsRecord, RunSummary
from crawler.signals.storage import SignalStorage


@pytest.mark.asyncio
async def test_save_news_record_and_deduplication(test_session):
    storage = SignalStorage()
    now_iso = datetime.now(timezone.utc).isoformat()

    rec1 = NewsRecord(
        id="rec_news_1",
        sourceId="techcrunch_ai",
        canonicalUrl="https://techcrunch.com/2026/09/10/article-one",
        title="Article One",
        fullText="Full text of article one.",
        publishedAt=now_iso,
        firstSeenAt=now_iso,
        ingestedAt=now_iso,
        dateExtractionMethod="json_ld",
        publishedAtConfidence=0.98,
        freshnessDecision="accepted_verified",
        freshnessReason="Fresh",
        contentHash="content_hash_news_1",
    )

    # 1. First save -> should succeed
    saved1 = await storage.save_news_record(test_session, rec1)
    assert saved1 is True

    # Check row count
    count = (await test_session.execute(select(func.count(NewsRecordModel.id)))).scalar()
    assert count == 1

    # 2. Duplicate rerun with same canonical URL -> idempotent update, no duplicate rows
    rec1_updated = NewsRecord(
        id="rec_news_1_updated",
        sourceId="techcrunch_ai",
        canonicalUrl="https://techcrunch.com/2026/09/10/article-one",
        title="Article One (Updated Headline)",
        fullText="Updated body text.",
        publishedAt=now_iso,
        firstSeenAt=now_iso,
        ingestedAt=now_iso,
        dateExtractionMethod="json_ld",
        publishedAtConfidence=0.98,
        freshnessDecision="accepted_verified",
        freshnessReason="Updated",
        contentHash="content_hash_news_1_updated",
    )
    saved2 = await storage.save_news_record(test_session, rec1_updated)
    assert saved2 is True

    count2 = (await test_session.execute(select(func.count(NewsRecordModel.id)))).scalar()
    assert count2 == 1  # No duplicate row created!

    # Verify field update
    model = (await test_session.execute(
        select(NewsRecordModel).where(NewsRecordModel.canonical_url == rec1.canonicalUrl)
    )).scalar_one()
    assert model.title == "Article One (Updated Headline)"


@pytest.mark.asyncio
async def test_save_job_record(test_session):
    storage = SignalStorage()
    now_iso = datetime.now(timezone.utc).isoformat()

    job1 = JobRecord(
        id="rec_job_1",
        sourceId="ai_jobs_net",
        canonicalUrl="https://ai-jobs.net/job/200",
        title="AI Engineer",
        company="Anthropic",
        location="San Francisco, CA",
        salary="$200,000 - $260,000",
        descriptionFullText="Job description for AI engineer.",
        publishedAt=now_iso,
        firstSeenAt=now_iso,
        ingestedAt=now_iso,
        dateExtractionMethod="feed_pubdate",
        publishedAtConfidence=0.95,
        freshnessDecision="accepted_verified",
        freshnessReason="Fresh",
        contentHash="content_hash_job_1",
    )

    saved = await storage.save_job_record(test_session, job1)
    assert saved is True

    count = (await test_session.execute(select(func.count(JobRecordModel.id)))).scalar()
    assert count == 1


@pytest.mark.asyncio
async def test_watermark_advance_on_success_only(test_session):
    storage = SignalStorage()
    source_id = "test_source_wm"
    attempt_time = datetime(2026, 9, 10, 10, 0, 0, tzinfo=timezone.utc)

    # 1. Attempt recorded
    await storage.record_attempt(test_session, source_id, attempt_time)
    state = await storage.get_crawl_state(test_session, source_id)
    assert state is not None
    assert state.last_attempted_crawl_at == attempt_time
    assert state.last_successful_crawl_at is None  # Must NOT be advanced yet

    # 2. Advance watermark upon successful completion
    success_time = datetime(2026, 9, 10, 10, 5, 0, tzinfo=timezone.utc)
    observed = {"url_hash_1", "url_hash_2"}
    await storage.advance_successful_watermark(
        test_session,
        source_id=source_id,
        success_time=success_time,
        observed_url_hashes=observed,
        boundary_item_id="https://example.com/item1",
        ingested_count=2,
    )

    state2 = await storage.get_crawl_state(test_session, source_id)
    assert state2.last_successful_crawl_at == success_time
    assert state2.total_ingested == 2
    assert state2.last_boundary_item_id == "https://example.com/item1"
    snapshot = json.loads(state2.observed_urls_snapshot)
    assert "url_hash_1" in snapshot
