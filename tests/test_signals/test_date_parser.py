"""Unit tests for multi-tier publication date extraction and normalization."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import pytest
from crawler.signals.date_parser import DateParser


def test_json_ld_date_published():
    html = """
    <html>
    <head>
        <script type="application/ld+json">
        {
            "@context": "https://schema.org",
            "@type": "NewsArticle",
            "headline": "OpenAI Announces New Autonomous Agent Model",
            "datePublished": "2026-09-10T15:30:00+00:00",
            "dateModified": "2026-09-10T16:00:00+00:00"
        }
        </script>
    </head>
    <body><h1>Test</h1></body>
    </html>
    """
    res = DateParser.extract_date(html_text=html)
    assert res.datetime_utc is not None
    assert res.iso_utc == "2026-09-10T15:30:00+00:00"
    assert "json_ld" in res.method
    assert res.confidence >= 0.95
    assert not res.is_future


def test_json_ld_graph_date_published():
    html = """
    <html>
    <head>
        <script type="application/ld+json">
        {
            "@graph": [
                {"@type": "WebSite", "name": "Tech Site"},
                {"@type": "Article", "datePublished": "2026-09-09T18:00:00Z"}
            ]
        }
        </script>
    </head>
    </html>
    """
    res = DateParser.extract_date(html_text=html)
    assert res.datetime_utc is not None
    assert res.iso_utc == "2026-09-09T18:00:00+00:00"
    assert res.confidence >= 0.95


def test_open_graph_article_published_time():
    html = """
    <html>
    <head>
        <meta property="article:published_time" content="2026-09-10T12:00:00Z" />
    </head>
    </html>
    """
    res = DateParser.extract_date(html_text=html)
    assert res.datetime_utc is not None
    assert res.iso_utc == "2026-09-10T12:00:00+00:00"
    assert "article:published_time" in res.method
    assert res.confidence >= 0.88


def test_standard_meta_tags():
    html = """
    <html>
    <head>
        <meta name="pubdate" content="2026-09-10T10:15:00+00:00" />
    </head>
    </html>
    """
    res = DateParser.extract_date(html_text=html)
    assert res.datetime_utc is not None
    assert res.iso_utc == "2026-09-10T10:15:00+00:00"
    assert "pubdate" in res.method


def test_feed_raw_pubdate_rfc2822():
    feed_date = "Thu, 10 Sep 2026 14:00:00 +0000"
    res = DateParser.extract_date(feed_raw_date=feed_date)
    assert res.datetime_utc is not None
    assert res.iso_utc == "2026-09-10T14:00:00+00:00"
    assert "feed_pubdate" in res.method


def test_visible_time_datetime_tag():
    html = """
    <html>
    <body>
        <div class="byline">
            Published on <time datetime="2026-09-10T08:00:00Z">September 10, 2026</time>
        </div>
    </body>
    </html>
    """
    res = DateParser.extract_date(html_text=html)
    assert res.datetime_utc is not None
    assert res.iso_utc == "2026-09-10T08:00:00+00:00"
    assert "visible_time" in res.method


def test_relative_date_parsing_across_timezones():
    ref = datetime(2026, 9, 10, 18, 0, 0, tzinfo=timezone.utc)

    # 1. America/New_York (UTC-4 in daylight saving)
    # Ref time 18:00 UTC = 14:00 EDT
    # "2 hours ago" = 12:00 EDT = 16:00 UTC
    dt_ny = DateParser.parse_relative_date("2 hours ago", ref, tz_name="America/New_York")
    assert dt_ny is not None
    assert dt_ny == datetime(2026, 9, 10, 16, 0, 0, tzinfo=timezone.utc)

    # 2. "15 minutes ago"
    dt_15m = DateParser.parse_relative_date("15 minutes ago", ref, tz_name="UTC")
    assert dt_15m == datetime(2026, 9, 10, 17, 45, 0, tzinfo=timezone.utc)

    # 3. "yesterday"
    dt_yesterday = DateParser.parse_relative_date("yesterday", ref, tz_name="UTC")
    assert dt_yesterday == datetime(2026, 9, 9, 18, 0, 0, tzinfo=timezone.utc)

    # 4. "posted 1 day ago"
    dt_1d = DateParser.parse_relative_date("posted 1 day ago", ref, tz_name="UTC")
    assert dt_1d == datetime(2026, 9, 9, 18, 0, 0, tzinfo=timezone.utc)


def test_ambiguous_numeric_date_by_locale():
    # 09/10/2026: September 10 in en_US vs October 9 in en_GB
    dt_us = DateParser.parse_ambiguous_numeric("09/10/2026", locale="en_US")
    assert dt_us is not None
    assert dt_us.month == 9
    assert dt_us.day == 10

    dt_gb = DateParser.parse_ambiguous_numeric("09/10/2026", locale="en_GB")
    assert dt_gb is not None
    assert dt_gb.month == 10
    assert dt_gb.day == 9


def test_url_date_fallback():
    url = "https://example.com/2026/09/10/ai-agent-breakthrough"
    res = DateParser.extract_date(
        url=url,
        date_rules={"url_date_pattern": r"/(?P<year>\d{4})/(?P<month>\d{2})/(?P<day>\d{2})/"}
    )
    assert res.datetime_utc is not None
    assert res.iso_utc.startswith("2026-09-10")
    assert "url_date" in res.method


def test_future_date_detection():
    ref = datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc)
    # Date is 30 minutes in future (exceeding 15m tolerance)
    future_date = (ref + timedelta(minutes=30)).isoformat()
    res = DateParser.extract_date(
        feed_raw_date=future_date,
        reference_time=ref,
        clock_skew_minutes=15,
    )
    assert res.is_future is True

    # Date is 5 minutes in future (within 15m tolerance)
    tolerable_date = (ref + timedelta(minutes=5)).isoformat()
    res2 = DateParser.extract_date(
        feed_raw_date=tolerable_date,
        reference_time=ref,
        clock_skew_minutes=15,
    )
    assert res2.is_future is False
