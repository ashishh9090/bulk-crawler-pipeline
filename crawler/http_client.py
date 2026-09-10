"""Asynchronous HTTP client with connection pooling, rate limiting, and Playwright fallback."""

import asyncio
import time
from typing import Any, Dict, Optional
import aiohttp
from crawler.config import settings
from crawler.logging import logger
from crawler.rate_limiter import rate_limiter
from crawler.retry import NonRetryableHttpError, RetryableHttpError, retry_with_backoff


class HttpClient:
    """Manages connection pooling, concurrency limits, and resilient fetching."""

    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None
        self._semaphore = asyncio.Semaphore(settings.concurrency_limit)
        self._playwright = None
        self._browser = None
        self._browser_lock = asyncio.Lock()

    async def get_session(self) -> aiohttp.ClientSession:
        """Lazily creates and returns the pooled aiohttp session."""
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(
                limit=settings.concurrency_limit * 2,
                limit_per_host=settings.per_domain_concurrency,
                ttl_dns_cache=300,
                enable_cleanup_closed=True,
                keepalive_timeout=30,
            )
            timeout = aiohttp.ClientTimeout(
                total=settings.request_timeout_seconds,
                connect=10.0,
                sock_read=25.0,
            )
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
            self._session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                headers=headers,
            )
        return self._session

    async def fetch(
        self,
        url: str,
        method: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        data: Any = None,
        json_data: Any = None,
    ) -> str:
        """Fetches URL content using connection pooling, rate limiting, and exponential retries."""
        async def _do_fetch() -> str:
            session = await self.get_session()
            async with self._semaphore:
                await rate_limiter.acquire(url)
                start_time = time.monotonic()
                try:
                    req_headers = dict(headers or {})
                    if "sec.gov" in url:
                        req_headers["User-Agent"] = "ResearchDataCollector admin@academic-crawler.org"

                    async with session.request(
                        method=method,
                        url=url,
                        headers=req_headers if req_headers else None,
                        params=params,
                        data=data,
                        json=json_data,
                    ) as response:
                        latency_ms = round((time.monotonic() - start_time) * 1000, 2)
                        status = response.status

                        # Check for rate limits and server errors
                        if status == 429:
                            retry_after_hdr = response.headers.get("Retry-After")
                            retry_after = float(retry_after_hdr) if retry_after_hdr and retry_after_hdr.isdigit() else 5.0
                            rate_limiter.record_retry_after(url, retry_after)
                            raise RetryableHttpError(status, "Rate limited", retry_after=retry_after)

                        if 500 <= status <= 599:
                            raise RetryableHttpError(status, f"Server error: {status}")

                        if 400 <= status <= 499:
                            raise NonRetryableHttpError(status, f"Client error: {status}")

                        content = await response.text(errors="replace")
                        logger.debug(
                            "HTTP %s %s [%d] in %sms",
                            method,
                            url,
                            status,
                            latency_ms,
                            extra={"url": url, "status_code": status, "latency_ms": latency_ms},
                        )
                        return content
                finally:
                    rate_limiter.release(url)

        return await retry_with_backoff(_do_fetch, url=url)

    async def fetch_rendered(self, url: str, wait_selector: Optional[str] = None) -> str:
        """Renders page via Playwright when JavaScript execution is strictly required."""
        from playwright.async_api import async_playwright

        async with self._browser_lock:
            if self._playwright is None:
                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(headless=True)

        async with self._semaphore:
            await rate_limiter.acquire(url)
            try:
                page = await self._browser.new_page()
                try:
                    await page.goto(url, timeout=int(settings.request_timeout_seconds * 1000), wait_until="domcontentloaded")
                    if wait_selector:
                        await page.wait_for_selector(wait_selector, timeout=10000)
                    content = await page.content()
                    return content
                finally:
                    await page.close()
            finally:
                rate_limiter.release(url)

    async def close(self) -> None:
        """Closes all underlying sessions, pools, and browser instances."""
        if self._session and not self._session.closed:
            await self._session.close()
            # Allow underlying SSL transports to close cleanly
            await asyncio.sleep(0.25)
        async with self._browser_lock:
            if self._browser:
                await self._browser.close()
                self._browser = None
            if self._playwright:
                await self._playwright.stop()
                self._playwright = None


http_client = HttpClient()
