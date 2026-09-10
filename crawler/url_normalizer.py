"""URL normalization and canonicalization engine for crawler deduplication."""

import hashlib
import re
from typing import Set
from urllib.parse import parse_qsl, quote, unquote, urlencode, urljoin, urlparse, urlunparse

# Common tracking parameters to strip during normalization
TRACKING_PARAMS: Set[str] = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "fbclid",
    "gclid",
    "gclsrc",
    "dclid",
    "zanpid",
    "msclkid",
    "ref",
    "ref_src",
    "source",
    "_hsenc",
    "_hsmi",
    "mc_cid",
    "mc_eid",
}


def normalize_url(raw_url: str, base_url: str | None = None) -> str:
    """Produces a canonical, deterministic representation of a URL."""
    if not raw_url:
        return ""

    raw_url = raw_url.strip()

    # Resolve relative URLs if base provided
    if base_url:
        raw_url = urljoin(base_url, raw_url)

    parsed = urlparse(raw_url)

    # Require http or https scheme
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        return raw_url

    # Lowercase hostname and strip default ports
    netloc = parsed.netloc.lower()
    if scheme == "http" and netloc.endswith(":80"):
        netloc = netloc[:-3]
    elif scheme == "https" and netloc.endswith(":443"):
        netloc = netloc[:-4]

    # Normalize path: collapse multiple slashes and resolve relative segments
    path = parsed.path
    if not path:
        path = "/"
    else:
        # Collapse multiple consecutive slashes
        path = re.sub(r"/+", "/", path)
        # Strip trailing slash if path is longer than "/"
        if len(path) > 1 and path.endswith("/"):
            path = path[:-1]

    # Filter and sort query parameters
    filtered_params = []
    if parsed.query:
        query_params = parse_qsl(parsed.query, keep_blank_values=False)
        for key, value in query_params:
            key_clean = key.strip()
            if key_clean.lower() not in TRACKING_PARAMS:
                filtered_params.append((key_clean, value.strip()))
        filtered_params.sort(key=lambda item: (item[0], item[1]))

    clean_query = urlencode(filtered_params, doseq=True) if filtered_params else ""

    # Discard fragments (#...) completely
    canonical = urlunparse((scheme, netloc, path, "", clean_query, ""))
    return canonical


def hash_url(canonical_url: str) -> str:
    """Computes SHA-256 hash of a normalized canonical URL."""
    return hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()
