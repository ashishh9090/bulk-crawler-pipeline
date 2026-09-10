"""Domain-aware asynchronous rate limiter respecting concurrency limits and Retry-After."""

import asyncio
import time
from typing import Dict
from urllib.parse import urlparse
from crawler.config import settings
from crawler.logging import logger


class DomainRateLimiter:
    """Manages polite request spacing and per-domain concurrency bounds."""

    def __init__(
        self,
        default_delay_seconds: float = 0.2,
        per_domain_concurrency: int = 5,
    ):
        self._default_delay = default_delay_seconds
        self._per_domain_concurrency = per_domain_concurrency
        self._last_request_times: Dict[str, float] = {}
        self._domain_locks: Dict[str, asyncio.Lock] = {}
        self._domain_semaphores: Dict[str, asyncio.Semaphore] = {}
        self._retry_after_until: Dict[str, float] = {}
        self._global_lock = asyncio.Lock()

    async def _get_domain_primitives(self, domain: str) -> tuple[asyncio.Lock, asyncio.Semaphore]:
        async with self._global_lock:
            if domain not in self._domain_locks:
                self._domain_locks[domain] = asyncio.Lock()
            if domain not in self._domain_semaphores:
                self._domain_semaphores[domain] = asyncio.Semaphore(self._per_domain_concurrency)
            return self._domain_locks[domain], self._domain_semaphores[domain]

    def extract_domain(self, url: str) -> str:
        """Extracts netloc/domain from URL."""
        return urlparse(url).netloc.lower() or "default"

    def record_retry_after(self, url: str, retry_after_seconds: float) -> None:
        """Enforces a temporary pause on a domain following a 429 Retry-After response."""
        domain = self.extract_domain(url)
        wait_until = time.monotonic() + max(1.0, retry_after_seconds)
        self._retry_after_until[domain] = max(self._retry_after_until.get(domain, 0.0), wait_until)
        logger.warning(
            "Enforced Retry-After for domain %s for %.1fs",
            domain,
            retry_after_seconds,
            extra={"domain": domain, "url": url},
        )

    async def acquire(self, url: str) -> None:
        """Waits until a request is permitted to proceed for the given URL's domain."""
        domain = self.extract_domain(url)
        lock, sem = await self._get_domain_primitives(domain)

        # Acquire per-domain concurrency slot
        await sem.acquire()

        try:
            async with lock:
                # Check if currently blocked by Retry-After
                now = time.monotonic()
                blocked_until = self._retry_after_until.get(domain, 0.0)
                if blocked_until > now:
                    pause_duration = blocked_until - now
                    logger.info("Honoring Retry-After pause of %.2fs for %s", pause_duration, domain)
                    await asyncio.sleep(pause_duration)
                    now = time.monotonic()

                # Enforce polite delay between consecutive requests
                last_time = self._last_request_times.get(domain, 0.0)
                elapsed = now - last_time
                if elapsed < self._default_delay:
                    wait_time = self._default_delay - elapsed
                    await asyncio.sleep(wait_time)

                self._last_request_times[domain] = time.monotonic()
        except Exception:
            sem.release()
            raise

    def release(self, url: str) -> None:
        """Releases the concurrency slot for the domain."""
        domain = self.extract_domain(url)
        if domain in self._domain_semaphores:
            self._domain_semaphores[domain].release()


rate_limiter = DomainRateLimiter(
    default_delay_seconds=settings.rate_limit_delay_seconds,
    per_domain_concurrency=settings.per_domain_concurrency,
)
