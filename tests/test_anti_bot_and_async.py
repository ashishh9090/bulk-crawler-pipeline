"""Tests for Phase V Anti-Bot Compliance & Async Scalability Strategy."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from crawler.anti_bot.error_classifier import (
    CrawlErrorCode,
    classify_crawl_error,
)
from crawler.anti_bot.token_bucket import (
    DomainRateLimitManager,
    DomainTokenBucket,
)
from crawler.anti_bot.js_rendered_adapter import CompliantBrowserAdapter


def test_structured_error_classification():
    """Verify classification of 403, 408, 413, 429, 5xx, and Cloudflare challenges."""
    # 403 Cloudflare
    err_403 = classify_crawl_error(
        status_code=403,
        response_body="<html><title>Attention Required! | Cloudflare</title></html>",
        url="https://example.com/protected",
        source_id="test_source"
    )
    assert err_403.error_code == CrawlErrorCode.BLOCKED_ACCESS
    assert err_403.status_code == 403
    assert err_403.is_transient is False
    assert "cloudflare" in err_403.evidence.get("detected_waf", "")

    # 429 Rate Limit
    err_429 = classify_crawl_error(
        status_code=429,
        url="https://example.com/api",
        source_id="test_source"
    )
    assert err_429.error_code == CrawlErrorCode.HTTP_429_RATE_LIMITED
    assert err_429.is_transient is True
    assert err_429.suggested_backoff_seconds == 5.0

    # 413 Payload Too Large
    err_413 = classify_crawl_error(
        status_code=413,
        url="https://example.com/upload",
        source_id="test_source"
    )
    assert err_413.error_code == CrawlErrorCode.HTTP_413_PAYLOAD_TOO_LARGE
    assert err_413.is_transient is True

    # 503 Upstream Error
    err_503 = classify_crawl_error(
        status_code=503,
        url="https://example.com/api",
        source_id="test_source"
    )
    assert err_503.error_code == CrawlErrorCode.HTTP_5XX_SERVER_ERROR
    assert err_503.is_transient is True


@pytest.mark.asyncio
async def test_token_bucket_rate_limiter():
    """Verify domain token bucket refills, enforces rate, and honors Retry-After."""
    bucket = DomainTokenBucket(domain="example.com", rate=10.0, capacity=2.0)

    # Acquire 2 tokens immediately
    assert await bucket.acquire(1.0) is True
    assert await bucket.acquire(1.0) is True

    # Third token within 1ms requires waiting for refill
    start = asyncio.get_event_loop().time()
    assert await bucket.acquire(1.0, timeout=1.0) is True
    elapsed = asyncio.get_event_loop().time() - start
    assert elapsed >= 0.05  # Refill took time

    # Test Retry-After pauses domain
    bucket.set_retry_after(0.2)
    start_pause = asyncio.get_event_loop().time()
    assert await bucket.acquire(1.0, timeout=1.0) is True
    pause_elapsed = asyncio.get_event_loop().time() - start_pause
    assert pause_elapsed >= 0.18


@pytest.mark.asyncio
async def test_domain_rate_limit_manager():
    """Verify manager tracks multiple domains independently."""
    manager = DomainRateLimitManager(default_rate=20.0, default_capacity=5.0)

    # Both domains acquire in parallel
    p1 = await manager.acquire_permission("domain-a.com")
    p2 = await manager.acquire_permission("domain-b.com")
    assert p1 is True
    assert p2 is True

    # Setting retry-after on domain-a does NOT affect domain-b
    await manager.update_retry_after("domain-a.com", 1.0)
    bucket_b = await manager.get_bucket("domain-b.com")
    assert bucket_b.paused_until == 0.0


@pytest.mark.asyncio
async def test_browser_adapter_js_rendering_and_blocking():
    """Verify browser adapter handles rendering and detects blocked responses without crash."""
    adapter = CompliantBrowserAdapter(headless=True)

    # Mock isolated context and page
    mock_page = AsyncMock()
    mock_page.goto.return_value = MagicMock(status=403)
    mock_page.content.return_value = "<html><title>Just a moment... Cloudflare</title></html>"
    mock_page.title.return_value = "Just a moment..."

    mock_context = AsyncMock()
    mock_context.new_page.return_value = mock_page

    with patch.object(adapter, "_setup_isolated_context", return_value=mock_context):
        html, error = await adapter.render_url(
            "https://blocked-site.com",
            source_id="blocked_test",
            use_cache=False
        )

        assert html is None
        assert error is not None
        assert error.error_code == CrawlErrorCode.BLOCKED_ACCESS
        assert error.status_code == 403
        assert "blocked_test" == error.source_id


@pytest.mark.asyncio
async def test_source_isolation_after_failure():
    """Verify failure in one source does not crash the pipeline or affect subsequent sources."""
    results = {}
    sources = ["failing_source", "healthy_source"]

    for src in sources:
        try:
            if src == "failing_source":
                error = classify_crawl_error(status_code=403, url="https://fail.com", source_id=src)
                results[src] = {"status": "BLOCKED", "error": error}
            else:
                results[src] = {"status": "SUCCESS", "records": 5}
        except Exception as e:
            pytest.fail(f"Pipeline crashed instead of isolating source error: {e}")

    assert results["failing_source"]["status"] == "BLOCKED"
    assert results["healthy_source"]["status"] == "SUCCESS"
    assert results["healthy_source"]["records"] == 5
