"""Exponential backoff retry engine with jitter and status-code aware routing."""

import asyncio
import random
from typing import Any, Callable, Coroutine, Optional, Set, TypeVar
import aiohttp
from crawler.config import settings
from crawler.logging import logger

T = TypeVar("T")

# HTTP status codes that indicate transient issues worth retrying
RETRIABLE_STATUS_CODES: Set[int] = {429, 500, 502, 503, 504}


class RetryableHttpError(Exception):
    """Raised when an HTTP response status qualifies for a retry."""
    def __init__(self, status: int, message: str, retry_after: Optional[float] = None):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.retry_after = retry_after


class NonRetryableHttpError(Exception):
    """Raised when an HTTP response status is terminal (e.g. 404, 400, 403)."""
    def __init__(self, status: int, message: str):
        super().__init__(f"Terminal HTTP {status}: {message}")
        self.status = status


async def retry_with_backoff(
    func: Callable[..., Coroutine[Any, Any, T]],
    *args: Any,
    max_retries: int | None = None,
    base_factor: float | None = None,
    url: str = "",
    **kwargs: Any,
) -> T:
    """Executes an async function with exponential backoff and jitter upon transient failures."""
    retries = max_retries if max_retries is not None else settings.max_retries
    factor = base_factor if base_factor is not None else settings.backoff_factor

    attempt = 0
    while True:
        try:
            return await func(*args, **kwargs)
        except NonRetryableHttpError as terminal_err:
            logger.warning(
                "Terminal error encountered, not retrying: %s",
                terminal_err,
                extra={"url": url, "status_code": terminal_err.status},
            )
            raise
        except (
            RetryableHttpError,
            aiohttp.ClientError,
            asyncio.TimeoutError,
            ConnectionResetError,
        ) as exc:
            attempt += 1
            if attempt > retries:
                logger.error(
                    "Exceeded max retries (%d) for %s: %s",
                    retries,
                    url,
                    exc,
                    extra={"url": url, "attempts": attempt},
                )
                raise

            # Calculate sleep delay: Exponential backoff + full jitter
            delay = factor ** attempt
            if isinstance(exc, RetryableHttpError) and exc.retry_after:
                delay = max(delay, exc.retry_after)

            # Full jitter: random uniform between 50% and 150% of computed delay
            jittered_delay = random.uniform(0.5 * delay, 1.5 * delay)

            logger.warning(
                "Transient failure on %s (attempt %d/%d): %s. Backing off for %.2fs",
                url or "task",
                attempt,
                retries,
                exc,
                jittered_delay,
                extra={"url": url, "attempt": attempt, "backoff_seconds": jittered_delay},
            )
            await asyncio.sleep(jittered_delay)
