"""Unit tests verifying RSS, API, and HTML discovery and extraction adapters."""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
import pytest
from crawler.signals.adapters.api_adapter import APISignalAdapter
from crawler.signals.adapters.html_adapter import HTMLSignalAdapter
from crawler.signals.adapters.rss_adapter import RSSSignalAdapter
from crawler.signals.config import SourceConfig
from crawler.signals.freshness_gate import FreshnessGate
from crawler.signals.models import FreshnessDecision, JobRecord, NewsRecord

SAMPLE_RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
    <channel>
        <title>TechCrunch AI</title>
        <link>https://techcrunch.com</link>
        <item>
            <title>Anthropic launches new Claude 3.7 Sonnet</title>
            <link>https://techcrunch.com/2026/09/10/anthropic-claude-3-7/</link>
            <pubDate>Thu, 10 Sep 2026 10:00:00 +0000</pubDate>
            <dc:creator>Alex Wilhelm</dc:creator>
            <description>Anthropic has officially rolled out its next generation reasoning model.</description>
        </item>
    </channel>
</rss>
"""

SAMPLE_ATOM_XML = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
    <title>Hugging Face Blog</title>
    <entry>
        <title>SmolLM2: Big Performance in Small Footprints</title>
        <link href="https://huggingface.co/blog/smollm2"/>
        <published>2026-09-10T09:30:00Z</published>
        <author><name>Loubna Ben Allal</name></author>
        <summary>Releasing lightweight models optimized for on-device reasoning.</summary>
    </entry>
</feed>
"""

SAMPLE_API_JSON = json.dumps([
    {"legal": "RemoteOK terms"},
    {
        "id": "1001",
        "position": "Senior ML Infrastructure Engineer",
        "company": "ScaleAI",
        "location": "Remote, US",
        "salary_min": 180000,
        "salary_max": 240000,
        "description": "<p>We are scaling model evaluation datasets.</p>",
        "date": "2026-09-10T08:00:00Z",
        "url": "https://remoteok.com/remote-jobs/1001",
        "tags": ["python", "ai", "kubernetes"]
    }
])

SAMPLE_HTML_LISTING = """
<html>
<body>
    <div class="job-item">
        <a href="/jobs/huggingface/deep-learning-engineer" class="job-link">
            <h3 class="job-title">Deep Learning Engineer</h3>
            <span class="company">Hugging Face</span>
        </a>
    </div>
</body>
</html>
"""


@pytest.mark.asyncio
async def test_rss_adapter_discovery():
    config = SourceConfig(
        id="techcrunch_ai",
        name="TechCrunch AI",
        type="news",
        base_url="https://techcrunch.com",
        listing_urls=["https://techcrunch.com/feed/"],
    )
    adapter = RSSSignalAdapter(config)

    mock_client = MagicMock()
    mock_client.fetch = AsyncMock(return_value=SAMPLE_RSS_XML)
    mock_session = AsyncMock()

    candidates = []
    async for cand in adapter.discover_candidates(mock_session, mock_client, limit=5):
        candidates.append(cand)

    assert len(candidates) == 1
    assert candidates[0].title == "Anthropic launches new Claude 3.7 Sonnet"
    assert "anthropic-claude-3-7" in candidates[0].raw_url
    assert candidates[0].author_or_company == "Alex Wilhelm"


@pytest.mark.asyncio
async def test_atom_feed_discovery():
    config = SourceConfig(
        id="huggingface_blog",
        name="Hugging Face Blog",
        type="news",
        base_url="https://huggingface.co",
        listing_urls=["https://huggingface.co/blog/feed.xml"],
    )
    adapter = RSSSignalAdapter(config)

    mock_client = MagicMock()
    mock_client.fetch = AsyncMock(return_value=SAMPLE_ATOM_XML)
    mock_session = AsyncMock()

    candidates = []
    async for cand in adapter.discover_candidates(mock_session, mock_client, limit=5):
        candidates.append(cand)

    assert len(candidates) == 1
    assert "SmolLM2" in candidates[0].title
    assert candidates[0].author_or_company == "Loubna Ben Allal"


@pytest.mark.asyncio
async def test_api_adapter_discovery_and_extraction():
    config = SourceConfig(
        id="remoteok_ai",
        name="RemoteOK AI",
        type="job",
        base_url="https://remoteok.com",
        listing_urls=["https://remoteok.com/api?tag=ai"],
        adapter_type="api",
    )
    adapter = APISignalAdapter(config)

    mock_client = MagicMock()
    mock_client.fetch = AsyncMock(return_value=SAMPLE_API_JSON)
    mock_session = AsyncMock()

    candidates = []
    async for cand in adapter.discover_candidates(mock_session, mock_client, limit=5):
        candidates.append(cand)

    assert len(candidates) == 1
    assert candidates[0].title == "Senior ML Infrastructure Engineer"
    assert candidates[0].author_or_company == "ScaleAI"

    # Test extraction
    ref_time = datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc)
    freshness_gate = FreshnessGate(reference_time=ref_time, freshness_window_hours=24)

    record, evaluation = await adapter.extract_record(
        candidate=candidates[0],
        session=mock_session,
        client=mock_client,
        freshness_gate=freshness_gate,
    )

    assert evaluation.decision == FreshnessDecision.ACCEPTED_VERIFIED
    assert isinstance(record, JobRecord)
    assert record.title == "Senior ML Infrastructure Engineer"
    assert record.company == "ScaleAI"
    assert record.salary == "$180,000 - $240,000"
    assert "model evaluation datasets" in record.descriptionFullText


@pytest.mark.asyncio
async def test_html_adapter_discovery():
    config = SourceConfig(
        id="huggingface_jobs",
        name="Hugging Face Jobs",
        type="job",
        base_url="https://huggingface.co",
        listing_urls=["https://huggingface.co/jobs"],
        adapter_type="html_listing",
        selectors={
            "item_container": ".job-item",
            "link": "a.job-link",
            "listing_title": ".job-title",
            "listing_company": ".company",
        },
    )
    adapter = HTMLSignalAdapter(config)

    mock_client = MagicMock()
    mock_client.fetch = AsyncMock(return_value=SAMPLE_HTML_LISTING)
    mock_session = AsyncMock()

    candidates = []
    async for cand in adapter.discover_candidates(mock_session, mock_client, limit=5):
        candidates.append(cand)

    assert len(candidates) == 1
    assert candidates[0].title == "Deep Learning Engineer"
    assert candidates[0].author_or_company == "Hugging Face"
    assert candidates[0].raw_url == "https://huggingface.co/jobs/huggingface/deep-learning-engineer"
