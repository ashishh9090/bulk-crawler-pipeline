"""Phase V Anti-Bot and Async Scale Strategy module."""

from crawler.anti_bot.error_classifier import (
    CrawlErrorCode,
    CrawlErrorRecord,
    classify_crawl_error,
)
from crawler.anti_bot.token_bucket import (
    DomainRateLimitManager,
    DomainTokenBucket,
)
from crawler.anti_bot.js_rendered_adapter import CompliantBrowserAdapter

__all__ = [
    "CrawlErrorCode",
    "CrawlErrorRecord",
    "classify_crawl_error",
    "DomainRateLimitManager",
    "DomainTokenBucket",
    "CompliantBrowserAdapter",
]
