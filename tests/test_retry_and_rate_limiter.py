"""Unit tests for exponential backoff retries and rate limiting."""

import asyncio
import pytest
from crawler.rate_limiter import DomainRateLimiter
from crawler.retry import NonRetryableHttpError, RetryableHttpError, retry_with_backoff


@pytest.mark.asyncio
async def test_retry_on_transient_error():
    attempts = 0

    async def flaky_task():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise RetryableHttpError(503, "Service Unavailable")
        return "success"

    result = await retry_with_backoff(
        flaky_task, max_retries=4, base_factor=1.1, url="http://test.com"
    )
    assert result == "success"
    assert attempts == 3


@pytest.mark.asyncio
async def test_terminal_error_no_retry():
    attempts = 0

    async def not_found():
        nonlocal attempts
        attempts += 1
        raise NonRetryableHttpError(404, "Not Found")

    with pytest.raises(NonRetryableHttpError):
        await retry_with_backoff(not_found, max_retries=3, url="http://test.com/404")
    assert attempts == 1


@pytest.mark.asyncio
async def test_domain_rate_limiter_concurrency():
    limiter = DomainRateLimiter(default_delay_seconds=0.01, per_domain_concurrency=2)
    url = "https://example.com/api"

    # Acquire slots
    await limiter.acquire(url)
    await limiter.acquire(url)

    # Release slots
    limiter.release(url)
    limiter.release(url)
