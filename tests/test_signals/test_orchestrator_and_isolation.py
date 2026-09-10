"""Integration tests verifying orchestrator isolation, concurrency locks, and run summaries."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker
from crawler.signals.config import SignalSettings, SourceConfig
from crawler.signals.orchestrator import SignalOrchestrator
from crawler.signals.storage import SignalStorage

SAMPLE_RSS_SUCCESS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
    <channel>
        <title>Good Source</title>
        <item>
            <title>Fresh AI Breakthrough Article</title>
            <link>https://goodsource.com/article-1</link>
            <pubDate>Thu, 10 Sep 2026 11:30:00 +0000</pubDate>
            <description>Exciting progress in agent architectures.</description>
        </item>
    </channel>
</rss>
"""


@pytest.mark.asyncio
async def test_source_failure_isolation(test_db_engine):
    session_factory = async_sessionmaker(test_db_engine, expire_on_commit=False)
    storage = SignalStorage()

    s1_failing = SourceConfig(
        id="failing_source",
        name="Failing Source",
        type="news",
        base_url="https://failing.com",
        listing_urls=["https://failing.com/feed.xml"],
        rate_limit_delay=0.0,
    )

    s2_healthy = SourceConfig(
        id="healthy_source",
        name="Healthy Source",
        type="news",
        base_url="https://goodsource.com",
        listing_urls=["https://goodsource.com/feed.xml"],
        rate_limit_delay=0.0,
    )

    mock_client = MagicMock()

    async def mock_fetch(url, *args, **kwargs):
        if "failing.com" in url:
            raise ConnectionError("Host connection refused")
        return SAMPLE_RSS_SUCCESS

    mock_client.fetch = AsyncMock(side_effect=mock_fetch)
    mock_client.get_session = AsyncMock()

    mock_robots = MagicMock()
    mock_robots.can_fetch = AsyncMock(return_value=True)

    orchestrator = SignalOrchestrator(
        settings=SignalSettings(freshness_window_hours=24),
        sources=[s1_failing, s2_healthy],
        storage=storage,
        http_client=mock_client,
        engine=test_db_engine,
        session_factory=session_factory,
        robots_checker=mock_robots,
    )

    ref_time = datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc)
    results = await orchestrator.run_sources(reference_time=ref_time)

    # Both sources were processed
    assert "failing_source" in results
    assert "healthy_source" in results

    # 1. Failing source is recorded as FAILED and has errors
    s1_res = results["failing_source"]
    assert s1_res.status in ("FAILED", "PARTIAL")
    assert s1_res.error_count > 0

    # 2. Healthy source SUCCEEDED despite the other source crashing!
    s2_res = results["healthy_source"]
    assert s2_res.status == "SUCCESS"
    assert s2_res.accepted_count == 1
    assert s2_res.rejected_count == 0

    # 3. Verify watermark behavior
    async with session_factory() as session:
        # Failing source watermark was NOT advanced
        failing_state = await storage.get_crawl_state(session, "failing_source")
        assert failing_state is not None
        assert failing_state.last_successful_crawl_at is None

        # Healthy source watermark WAS advanced to ref_time
        healthy_state = await storage.get_crawl_state(session, "healthy_source")
        assert healthy_state is not None
        assert healthy_state.last_successful_crawl_at == ref_time


@pytest.mark.asyncio
async def test_overlapping_run_lock(test_db_engine):
    session_factory = async_sessionmaker(test_db_engine, expire_on_commit=False)
    storage = SignalStorage()

    source = SourceConfig(
        id="locked_source",
        name="Locked Source",
        type="news",
        base_url="https://goodsource.com",
        listing_urls=["https://goodsource.com/feed.xml"],
        rate_limit_delay=0.0,
    )

    mock_client = MagicMock()
    mock_client.fetch = AsyncMock(return_value=SAMPLE_RSS_SUCCESS)
    mock_client.get_session = AsyncMock()

    mock_robots = MagicMock()
    mock_robots.can_fetch = AsyncMock(return_value=True)

    orchestrator = SignalOrchestrator(
        settings=SignalSettings(),
        sources=[source],
        storage=storage,
        http_client=mock_client,
        engine=test_db_engine,
        session_factory=session_factory,
        robots_checker=mock_robots,
    )

    # Acquire lock externally to simulate an active concurrent run
    lock = await orchestrator._get_source_lock("locked_source")
    await lock.acquire()

    try:
        summary = await orchestrator.ingest_source(source)
        assert summary.status == "SKIPPED_LOCKED"
    finally:
        lock.release()
