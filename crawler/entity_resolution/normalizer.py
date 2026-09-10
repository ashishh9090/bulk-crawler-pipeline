"""Deterministic entity and domain normalization rules."""

import re
import unicodedata
from urllib.parse import urlparse
from typing import Optional

# Comprehensive corporate legal suffixes regex (anchored or word-bounded)
CORPORATE_SUFFIXES_REGEX = re.compile(
    r"""
    \b(
        inc(\.|\b)|
        incorporated\b|
        llc(\.|\b)|
        l\.l\.c\.?|
        ltd(\.|\b)|
        limited\b|
        corp(\.|\b)|
        corporation\b|
        gmbh\b|
        co(\.|\b)|
        company\b|
        pbc\b|
        sas\b|
        se\b|
        ag\b|
        s\.a\.?|
        b\.v\.?|
        bv\b|
        k\.k\.?|
        kk\b|
        pte(\.|\s)+ltd(\.|\b)|
        pvt(\.|\s)+ltd(\.|\b)|
        opco(\s+llc)?\b
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Known joined vs spaced AI patterns (e.g., Open AI -> OpenAI)
AI_SPACING_REPLACEMENTS = [
    (re.compile(r"\bopen\s+ai\b", re.IGNORECASE), "openai"),
    (re.compile(r"\bmistral\s+ai\b", re.IGNORECASE), "mistral ai"),
    (re.compile(r"\bperplexity\s+ai\b", re.IGNORECASE), "perplexity ai"),
    (re.compile(r"\bscale\s+ai\b", re.IGNORECASE), "scale ai"),
    (re.compile(r"\bstability\s+ai\b", re.IGNORECASE), "stability ai"),
    (re.compile(r"\binflection\s+ai\b", re.IGNORECASE), "inflection ai"),
    (re.compile(r"\beleven\s+labs\b", re.IGNORECASE), "elevenlabs"),
    (re.compile(r"\bcursor\s+ai\b", re.IGNORECASE), "cursor"),
    (re.compile(r"\bhugging\s+face\b", re.IGNORECASE), "hugging face"),
    (re.compile(r"\bhuggingface\b", re.IGNORECASE), "hugging face"),
    (re.compile(r"\brunway\s*ml\b", re.IGNORECASE), "runway"),
    (re.compile(r"\bw\s*&\s*b\b", re.IGNORECASE), "weights and biases"),
    (re.compile(r"\bwandb\b", re.IGNORECASE), "weights and biases"),
]


def normalize_entity_name(raw_name: Optional[str]) -> str:
    """Deterministically normalizes an entity name.
    
    Steps:
    1. Unicode normalization (NFKD then NFC).
    2. Lowercase comparison form.
    3. Safe AI spacing normalization (e.g. Open AI -> openai).
    4. Corporate legal suffix removal (Inc, LLC, Ltd, Corp, GmbH, etc.).
    5. Punctuation and whitespace normalization.
    """
    if not raw_name or not isinstance(raw_name, str):
        return ""

    # Step 1: Unicode normalization (NFKD to decompose, NFC to compose)
    normalized = unicodedata.normalize("NFKD", raw_name)
    # Strip non-spacing mark diacritics
    normalized = "".join(c for c in normalized if not unicodedata.combining(c))
    normalized = unicodedata.normalize("NFC", normalized)

    # Step 2: Lowercase comparison form
    normalized = normalized.lower()

    # Step 3: Handle specific known AI spacing variants before suffix stripping
    for pattern, replacement in AI_SPACING_REPLACEMENTS:
        normalized = pattern.sub(replacement, normalized)

    # Step 4: Corporate suffix removal
    # Remove trailing corporate suffixes (e.g. ", Inc.", " LLC", " Corporation")
    # First replace commas and trailing punctuation around suffixes
    normalized = re.sub(r"[\s,]+$", "", normalized)
    normalized = CORPORATE_SUFFIXES_REGEX.sub(" ", normalized)

    # Step 5: Replace remaining punctuation with space, except keep alphanumeric
    normalized = re.sub(r"[^\w\s]", " ", normalized)

    # Step 6: Normalize whitespace
    normalized = re.sub(r"\s+", " ", normalized).strip()

    return normalized


def normalize_domain(url_or_domain: Optional[str]) -> str:
    """Extracts and normalizes a domain from a URL or raw domain string.
    
    Examples:
    - 'https://www.openai.com/research' -> 'openai.com'
    - 'OPENAI.COM/' -> 'openai.com'
    - 'http://blog.anthropic.com:8080' -> 'anthropic.com' (root domain extracted)
    """
    if not url_or_domain or not isinstance(url_or_domain, str):
        return ""

    raw = url_or_domain.strip().lower()
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw

    try:
        parsed = urlparse(raw)
        host = parsed.netloc or parsed.path
        # Remove port if present
        host = host.split(":")[0]
        # Remove leading 'www.'
        if host.startswith("www."):
            host = host[4:]
        return host.strip()
    except Exception:
        return ""
