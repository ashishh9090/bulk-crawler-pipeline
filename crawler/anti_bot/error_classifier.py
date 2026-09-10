"""Structured error classification for HTTP and crawler failure scenarios."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict, Field


class CrawlErrorCode(str, Enum):
    HTTP_403_FORBIDDEN = "HTTP_403_FORBIDDEN"           # Blocked access / WAF / Cloudflare
    HTTP_408_TIMEOUT = "HTTP_408_TIMEOUT"               # Request timeout
    HTTP_413_PAYLOAD_TOO_LARGE = "HTTP_413_PAYLOAD_TOO_LARGE"  # Entity too large
    HTTP_429_RATE_LIMITED = "HTTP_429_RATE_LIMITED"     # Rate limited
    HTTP_5XX_SERVER_ERROR = "HTTP_5XX_SERVER_ERROR"     # Upstream server error
    NETWORK_TIMEOUT = "NETWORK_TIMEOUT"                 # Client-side connect/read timeout
    PARSING_FAILURE = "PARSING_FAILURE"                 # Malformed HTML / JSON syntax error
    ROBOTS_TXT_DISALLOWED = "ROBOTS_TXT_DISALLOWED"     # Forbidden by robots.txt policy
    BLOCKED_ACCESS = "BLOCKED_ACCESS"                   # Bot challenge / CAPTCHA encountered
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


class CrawlErrorRecord(BaseModel):
    """Structured error record capturing root-cause classification and audit trail."""
    model_config = ConfigDict(extra="ignore")

    error_code: CrawlErrorCode
    status_code: Optional[int] = None
    url: str
    source_id: str
    message: str
    is_transient: bool
    suggested_backoff_seconds: Optional[float] = None
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    evidence: Dict[str, Any] = Field(default_factory=dict)


def classify_crawl_error(
    status_code: Optional[int],
    exception: Optional[Exception] = None,
    response_body: Optional[str] = None,
    url: str = "",
    source_id: str = "",
) -> CrawlErrorRecord:
    """Deterministically classifies any error, HTTP status code, or network exception."""
    message = str(exception) if exception else (f"HTTP {status_code}" if status_code else "Unknown error")
    body_lower = (response_body or "").lower()

    # 1. Cloudflare / WAF / Bot-challenge detection
    if status_code == 403 or "cloudflare" in body_lower or "just a moment..." in body_lower or "cf-browser-verification" in body_lower:
        return CrawlErrorRecord(
            error_code=CrawlErrorCode.BLOCKED_ACCESS,
            status_code=status_code or 403,
            url=url,
            source_id=source_id,
            message="Access restricted or anti-bot challenge encountered. Respecting access boundary.",
            is_transient=False,
            evidence={
                "detected_waf": "cloudflare" if "cloudflare" in body_lower else "generic_403",
                "sample_snippet": body_lower[:200] if response_body else "",
            }
        )

    # 2. Rate limiting (429)
    if status_code == 429:
        return CrawlErrorRecord(
            error_code=CrawlErrorCode.HTTP_429_RATE_LIMITED,
            status_code=429,
            url=url,
            source_id=source_id,
            message="Rate limit threshold exceeded by origin server (HTTP 429).",
            is_transient=True,
            suggested_backoff_seconds=5.0,
            evidence={"status": 429}
        )

    # 3. Payload Too Large (413)
    if status_code == 413:
        return CrawlErrorRecord(
            error_code=CrawlErrorCode.HTTP_413_PAYLOAD_TOO_LARGE,
            status_code=413,
            url=url,
            source_id=source_id,
            message="Payload size exceeded server quota (HTTP 413).",
            is_transient=True,
            evidence={"status": 413}
        )

    # 4. Request Timeout (408)
    if status_code == 408 or "timeout" in message.lower() or "timeouterror" in message.lower():
        return CrawlErrorRecord(
            error_code=CrawlErrorCode.NETWORK_TIMEOUT,
            status_code=status_code or 408,
            url=url,
            source_id=source_id,
            message=f"Request timed out: {message}",
            is_transient=True,
            suggested_backoff_seconds=2.0,
        )

    # 5. Upstream server errors (5xx)
    if status_code and 500 <= status_code < 600:
        return CrawlErrorRecord(
            error_code=CrawlErrorCode.HTTP_5XX_SERVER_ERROR,
            status_code=status_code,
            url=url,
            source_id=source_id,
            message=f"Upstream server error (HTTP {status_code}).",
            is_transient=True,
            suggested_backoff_seconds=3.0,
        )

    # 6. Parse failure
    if "json" in message.lower() or "parse" in message.lower() or "syntax" in message.lower():
        return CrawlErrorRecord(
            error_code=CrawlErrorCode.PARSING_FAILURE,
            status_code=status_code,
            url=url,
            source_id=source_id,
            message=f"Parsing error: {message}",
            is_transient=False,
        )

    # Fallback
    return CrawlErrorRecord(
        error_code=CrawlErrorCode.UNKNOWN_ERROR,
        status_code=status_code,
        url=url,
        source_id=source_id,
        message=message,
        is_transient=False,
    )
