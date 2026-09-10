"""Compliant Playwright async adapter with isolated contexts and resource blocking."""

import asyncio
import hashlib
import time
from typing import Any, Dict, Optional, Tuple
from playwright.async_api import Browser, BrowserContext, Page, async_playwright
from crawler.anti_bot.error_classifier import CrawlErrorCode, CrawlErrorRecord
from crawler.logging import logger

CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


class CompliantBrowserAdapter:
    """Manages isolated browser rendering with polite rate limits and asset blocking."""

    def __init__(
        self,
        executable_path: str = CHROME_PATH,
        headless: bool = True,
        request_timeout_ms: int = 20_000,
    ):
        self.executable_path = executable_path
        self.headless = headless
        self.request_timeout_ms = request_timeout_ms
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._cache: Dict[str, Tuple[str, float]] = {}  # url -> (html, timestamp)
        self._cache_ttl_seconds = 3600.0
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Initializes the shared Playwright browser instance lazily."""
        async with self._lock:
            if self._browser is None:
                self._playwright = await async_playwright().start()
                try:
                    self._browser = await self._playwright.chromium.launch(
                        executable_path=self.executable_path,
                        headless=self.headless,
                    )
                except Exception as e:
                    # Fallback to default chromium if custom path fails
                    logger.warning("Custom chrome launch failed (%s); falling back to default chromium", e)
                    self._browser = await self._playwright.chromium.launch(headless=self.headless)

    async def close(self) -> None:
        """Closes browser instance and playwright daemon."""
        async with self._lock:
            if self._browser:
                await self._browser.close()
                self._browser = None
            if self._playwright:
                await self._playwright.stop()
                self._playwright = None

    async def _setup_isolated_context(self) -> BrowserContext:
        """Creates an ephemeral, isolated browser context with resource blocking."""
        if self._browser is None:
            await self.initialize()

        context = await self._browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 (AI-Intelligence-Signal-Bot/2.0)",
            viewport={"width": 1280, "height": 800},
            ignore_https_errors=False,
        )

        # Abort requests for images, fonts, media, and stylesheets to optimize latency and bandwidth
        async def route_interceptor(route):
            req_type = route.request.resource_type
            if req_type in ("image", "media", "font", "stylesheet"):
                await route.abort()
            else:
                await route.continue_()

        await context.route("**/*", route_interceptor)
        return context

    async def render_url(
        self,
        url: str,
        wait_selector: Optional[str] = None,
        source_id: str = "unknown",
        use_cache: bool = True,
    ) -> Tuple[Optional[str], Optional[CrawlErrorRecord]]:
        """Renders page using isolated context and returns (html, error_record).
        
        If anti-bot or 403 challenge is detected, returns structured CrawlErrorRecord
        without crashing, preserving compliance and source isolation.
        """
        now = time.time()
        # 1. Check local cache
        if use_cache and url in self._cache:
            cached_html, cached_time = self._cache[url]
            if now - cached_time < self._cache_ttl_seconds:
                return cached_html, None

        context = await self._setup_isolated_context()
        page: Optional[Page] = None

        try:
            page = await context.new_page()
            response = await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=self.request_timeout_ms,
            )

            status = response.status if response else 200
            content = await page.content()
            content_lower = content.lower()

            # Anti-bot and WAF challenge detection (Cloudflare, PerimeterX, etc.)
            is_blocked = (
                status == 403
                or "cf-browser-verification" in content_lower
                or "just a moment..." in content_lower
                or "<title>attention required! | cloudflare</title>" in content_lower
            )

            if is_blocked:
                error = CrawlErrorRecord(
                    error_code=CrawlErrorCode.BLOCKED_ACCESS,
                    status_code=status,
                    url=url,
                    source_id=source_id,
                    message="Anti-bot protection or access restriction encountered. Preserving compliance; stopping crawl on this endpoint.",
                    is_transient=False,
                    evidence={
                        "title": await page.title(),
                        "status": status,
                        "url": url,
                        "snippet": content[:300],
                    },
                )
                logger.warning(
                    "Source '%s' blocked access at %s (HTTP %d). Recorded blocked_access record.",
                    source_id,
                    url,
                    status,
                )
                return None, error

            # Wait for content selector if provided
            if wait_selector:
                await page.wait_for_selector(wait_selector, timeout=5_000)
                content = await page.content()

            # Store in cache
            if use_cache:
                self._cache[url] = (content, now)

            return content, None

        except Exception as exc:
            err_msg = str(exc)
            logger.error("Browser rendering error for %s: %s", url, err_msg)
            error = CrawlErrorRecord(
                error_code=CrawlErrorCode.NETWORK_TIMEOUT if "timeout" in err_msg.lower() else CrawlErrorCode.UNKNOWN_ERROR,
                status_code=408 if "timeout" in err_msg.lower() else None,
                url=url,
                source_id=source_id,
                message=f"Browser rendering failed: {err_msg}",
                is_transient=True,
            )
            return None, error

        finally:
            if page:
                await page.close()
            await context.close()
