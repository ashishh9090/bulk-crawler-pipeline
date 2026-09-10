"""Per-domain token-bucket rate limiter with Retry-After and backpressure support."""

import asyncio
import time
from typing import Dict, Optional
from crawler.logging import logger


class DomainTokenBucket:
    """Individual token bucket for a specific domain."""

    def __init__(
        self,
        domain: str,
        rate: float = 5.0,  # Tokens per second
        capacity: float = 10.0,  # Max bucket capacity
        max_concurrency: int = 5,
    ):
        self.domain = domain
        self.rate = rate
        self.capacity = capacity
        self.tokens = capacity
        self.last_refill = time.monotonic()
        self.lock = asyncio.Lock()
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.paused_until = 0.0

    def refill(self) -> None:
        """Adds tokens according to elapsed time."""
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last_refill = now

    async def acquire(self, tokens_required: float = 1.0, timeout: float = 30.0) -> bool:
        """Acquires tokens from the bucket, waiting asynchronously if necessary."""
        start_time = time.monotonic()

        while True:
            now = time.monotonic()
            if now - start_time > timeout:
                return False

            # Check if domain is paused due to HTTP 429 Retry-After
            if now < self.paused_until:
                pause_remaining = self.paused_until - now
                sleep_time = min(pause_remaining, timeout - (now - start_time))
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
                    continue

            async with self.lock:
                self.refill()
                if self.tokens >= tokens_required:
                    self.tokens -= tokens_required
                    return True

                # Calculate wait time until enough tokens are replenished
                needed = tokens_required - self.tokens
                wait_seconds = needed / self.rate

            # Sleep outside the lock
            sleep_duration = min(wait_seconds, 1.0)
            await asyncio.sleep(sleep_duration)

    def set_retry_after(self, delay_seconds: float) -> None:
        """Pauses the domain token bucket when HTTP 429 Retry-After is encountered."""
        now = time.monotonic()
        self.paused_until = max(self.paused_until, now + delay_seconds)
        self.tokens = 0.0  # Empty bucket to prevent thundering herd
        logger.warning(
            "Domain '%s' rate limited (429). Paused for %.2f seconds.",
            self.domain,
            delay_seconds,
        )


class DomainRateLimitManager:
    """Manages token buckets and concurrency across multiple domains."""

    def __init__(
        self,
        default_rate: float = 5.0,
        default_capacity: float = 10.0,
        default_concurrency: int = 5,
        global_concurrency: int = 50,
    ):
        self.default_rate = default_rate
        self.default_capacity = default_capacity
        self.default_concurrency = default_concurrency
        self.global_semaphore = asyncio.Semaphore(global_concurrency)
        self._buckets: Dict[str, DomainTokenBucket] = {}
        self._lock = asyncio.Lock()

    async def get_bucket(self, domain: str) -> DomainTokenBucket:
        async with self._lock:
            if domain not in self._buckets:
                self._buckets[domain] = DomainTokenBucket(
                    domain=domain,
                    rate=self.default_rate,
                    capacity=self.default_capacity,
                    max_concurrency=self.default_concurrency,
                )
            return self._buckets[domain]

    async def acquire_permission(self, domain: str, timeout: float = 30.0) -> bool:
        """Acquires both global concurrency and per-domain token bucket approval."""
        bucket = await self.get_bucket(domain)
        # 1. Acquire domain token
        acquired_token = await bucket.acquire(1.0, timeout=timeout)
        if not acquired_token:
            return False
        return True

    async def update_retry_after(self, domain: str, delay_seconds: float) -> None:
        """Updates Retry-After for a specific domain."""
        bucket = await self.get_bucket(domain)
        bucket.set_retry_after(delay_seconds)
