"""URL canonicalization for Phase II signal ingestion deduplication."""

import hashlib
import re
from typing import Set
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
from crawler.url_normalizer import TRACKING_PARAMS, normalize_url

# Extended tracking parameters specifically seen in feeds, newsletters, job aggregators
EXTENDED_TRACKING_PARAMS: Set[str] = TRACKING_PARAMS | {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "utm_reader",
    "feed",
    "feed_type",
    "rss",
    "from",
    "ref",
    "referer",
    "source",
    "gh_src",
    "src",
    "session_id",
    "sessionid",
    "jsessionid",
    "phpsessid",
    "_ga",
    "_gl",
    "_hsenc",
    "_hsmi",
    "mc_cid",
    "mc_eid",
}


def canonicalize_signal_url(raw_url: str, base_url: str | None = None) -> str:
    """Produces deterministic canonical URL stripped of tracking, sessions, and fragments."""
    if not raw_url:
        return ""

    raw_url = raw_url.strip()
    if base_url:
        raw_url = urljoin(base_url, raw_url)

    parsed = urlparse(raw_url)
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        return raw_url

    netloc = parsed.netloc.lower()
    if scheme == "http" and netloc.endswith(":80"):
        netloc = netloc[:-3]
    elif scheme == "https" and netloc.endswith(":443"):
        netloc = netloc[:-4]

    # Clean path: collapse multiple slashes and strip trailing slash if length > 1
    path = parsed.path or "/"
    path = re.sub(r"/+", "/", path)
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]

    # Filter out tracking query params and sort deterministically
    filtered_params = []
    if parsed.query:
        query_params = parse_qsl(parsed.query, keep_blank_values=False)
        for key, value in query_params:
            k_clean = key.strip()
            if k_clean.lower() not in EXTENDED_TRACKING_PARAMS:
                filtered_params.append((k_clean, value.strip()))
        filtered_params.sort(key=lambda item: (item[0], item[1]))

    clean_query = urlencode(filtered_params, doseq=True) if filtered_params else ""

    # Discard fragments
    return urlunparse((scheme, netloc, path, "", clean_query, ""))


def compute_url_hash(canonical_url: str) -> str:
    """Computes SHA-256 hash of a normalized canonical URL."""
    return hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()
