"""Multi-tier publication date extraction and normalization engine."""

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo
import warnings
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

META_DATE_TAGS: List[Tuple[str, str]] = [
    ("property", "article:published_time"),
    ("property", "og:published_time"),
    ("name", "article:published_time"),
    ("name", "pubdate"),
    ("name", "publishdate"),
    ("name", "timestamp"),
    ("name", "dc.date"),
    ("name", "dc.date.issued"),
    ("name", "date"),
    ("name", "parsely-pub-date"),
    ("name", "sailthru.date"),
]

RELATIVE_DATE_PATTERNS = [
    (re.compile(r"(\d+)\s*(?:seconds?|secs?|s)\s+ago", re.I), lambda m: timedelta(seconds=int(m.group(1)))),
    (re.compile(r"(\d+)\s*(?:minutes?|mins?|m)\s+ago", re.I), lambda m: timedelta(minutes=int(m.group(1)))),
    (re.compile(r"(\d+)\s*(?:hours?|hrs?|h)\s+ago", re.I), lambda m: timedelta(hours=int(m.group(1)))),
    (re.compile(r"(?:posted\s+)?(\d+)\s*(?:days?|d)\s+ago", re.I), lambda m: timedelta(days=int(m.group(1)))),
    (re.compile(r"^yesterday\b", re.I), lambda m: timedelta(days=1)),
    (re.compile(r"^today\b", re.I), lambda m: timedelta(seconds=0)),
    (re.compile(r"just\s+now", re.I), lambda m: timedelta(seconds=0)),
]


@dataclass
class ExtractedDate:
    """Represents the outcome of a prioritized date extraction."""
    datetime_utc: Optional[datetime]
    iso_utc: Optional[str]
    method: str
    confidence: float
    is_future: bool
    raw_value: Optional[str] = None


class DateParser:
    """Extracts, parses, and normalizes publication dates with prioritized strategies."""

    @staticmethod
    def parse_iso_or_rfc2822(date_str: str) -> Optional[datetime]:
        """Tries parsing standard ISO-8601 or RFC 2822 date strings."""
        if not date_str or not isinstance(date_str, str):
            return None

        clean_str = date_str.strip()

        # Try RFC 2822 first (e.g. "Thu, 10 Sep 2026 14:00:00 +0000")
        try:
            dt = parsedate_to_datetime(clean_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            pass

        # Try ISO format
        # Normalize trailing Z to +00:00
        iso_clean = clean_str
        if iso_clean.endswith("Z"):
            iso_clean = iso_clean[:-1] + "+00:00"

        try:
            dt = datetime.fromisoformat(iso_clean)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            pass

        # Try common numeric formats
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d",
            "%B %d, %Y",
            "%b %d, %Y",
            "%d %B %Y",
            "%d %b %Y",
        ):
            try:
                dt = datetime.strptime(clean_str, fmt)
                return dt.replace(tzinfo=timezone.utc)
            except Exception:
                continue

        return None

    @staticmethod
    def parse_ambiguous_numeric(date_str: str, locale: str = "en_US") -> Optional[datetime]:
        """Handles ambiguous dates like 09/10/2026 vs 10/09/2026 based on configured locale."""
        clean_str = date_str.strip()
        # Look for pattern DD/MM/YYYY or MM/DD/YYYY
        m = re.match(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?$", clean_str)
        if not m:
            return None

        p1, p2, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        hour = int(m.group(4) or 0)
        minute = int(m.group(5) or 0)
        second = int(m.group(6) or 0)

        # In en_US: p1 is month, p2 is day
        if locale.startswith("en_US"):
            month, day = p1, p2
        else:
            # Default international: p1 is day, p2 is month
            day, month = p1, p2

        try:
            dt = datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)
            return dt
        except ValueError:
            # Swap if invalid (e.g. 13/05 in en_US)
            try:
                dt = datetime(year, day, month, hour, minute, second, tzinfo=timezone.utc)
                return dt
            except ValueError:
                return None

    @classmethod
    def parse_relative_date(
        cls,
        text: str,
        reference_time: datetime,
        tz_name: str = "UTC",
    ) -> Optional[datetime]:
        """Resolves relative date strings against the crawl reference time in the source's timezone."""
        if not text:
            return None

        clean_text = text.strip()

        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = timezone.utc

        # Convert reference time to source local timezone
        ref_local = reference_time.astimezone(tz)

        for pattern, delta_fn in RELATIVE_DATE_PATTERNS:
            m = pattern.search(clean_text)
            if m:
                delta = delta_fn(m)
                dt_local = ref_local - delta
                # Return in UTC
                return dt_local.astimezone(timezone.utc)

        return None

    @classmethod
    def parse_url_date(cls, url: str, pattern: Optional[str] = None) -> Optional[datetime]:
        """Extracts date encoded in URL path if configured."""
        if not url:
            return None

        regex = pattern or r"/(?P<year>\d{4})/(?P<month>\d{1,2})/(?P<day>\d{1,2})/"
        try:
            m = re.search(regex, url)
            if m:
                year = int(m.group("year"))
                month = int(m.group("month"))
                day = int(m.group("day"))
                return datetime(year, month, day, tzinfo=timezone.utc)
        except Exception:
            pass

        return None

    @classmethod
    def extract_from_json_ld(
        cls,
        soup: BeautifulSoup,
        allow_modified: bool = False,
    ) -> Optional[Tuple[datetime, str]]:
        """Extracts datePublished (or dateModified) from JSON-LD schema blocks."""
        for script in soup.find_all("script", type="application/ld+json"):
            if not script.string:
                continue
            try:
                data = json.loads(script.string)
            except Exception:
                continue

            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue

                # Handle @graph
                candidates = [item]
                if "@graph" in item and isinstance(item["@graph"], list):
                    candidates.extend(item["@graph"])

                for node in candidates:
                    if not isinstance(node, dict):
                        continue

                    # datePublished is prioritized
                    if "datePublished" in node and node["datePublished"]:
                        dt = cls.parse_iso_or_rfc2822(str(node["datePublished"]))
                        if dt:
                            return dt, "json_ld_published"

                    if allow_modified and "dateModified" in node and node["dateModified"]:
                        dt = cls.parse_iso_or_rfc2822(str(node["dateModified"]))
                        if dt:
                            return dt, "json_ld_modified"

        return None

    @classmethod
    def extract_date(
        cls,
        html_text: Optional[str] = None,
        feed_raw_date: Optional[str] = None,
        url: Optional[str] = None,
        reference_time: Optional[datetime] = None,
        timezone_name: str = "UTC",
        locale: str = "en_US",
        selectors: Optional[Dict[str, Any]] = None,
        date_rules: Optional[Dict[str, Any]] = None,
        clock_skew_minutes: int = 15,
    ) -> ExtractedDate:
        """Executes the full prioritized date extraction workflow."""
        ref_time = reference_time or datetime.now(timezone.utc)
        clock_skew_tolerance = timedelta(minutes=clock_skew_minutes)
        future_limit = ref_time + clock_skew_tolerance
        date_rules = date_rules or {}
        selectors = selectors or {}

        soup: Optional[BeautifulSoup] = None
        if html_text:
            soup = BeautifulSoup(html_text, "lxml")

        # -------------------------------------------------------------
        # 1. Structured Metadata (Priority 1)
        # -------------------------------------------------------------

        # 1a. JSON-LD
        if soup:
            allow_mod = date_rules.get("allow_modified_as_published", False)
            json_ld_res = cls.extract_from_json_ld(soup, allow_modified=allow_mod)
            if json_ld_res:
                dt, method = json_ld_res
                is_future = dt > future_limit
                return ExtractedDate(
                    datetime_utc=dt,
                    iso_utc=dt.isoformat(),
                    method=f"structured_{method}",
                    confidence=0.98,
                    is_future=is_future,
                )

        # 1b. RSS/Atom feed date provided directly
        if feed_raw_date:
            dt = cls.parse_iso_or_rfc2822(feed_raw_date)
            if dt:
                is_future = dt > future_limit
                return ExtractedDate(
                    datetime_utc=dt,
                    iso_utc=dt.isoformat(),
                    method="structured_feed_pubdate",
                    confidence=0.95,
                    is_future=is_future,
                    raw_value=feed_raw_date,
                )

        # 1c. Open Graph & Meta tags
        if soup:
            preferred_meta = date_rules.get("preferred_meta", [])
            # Check preferred meta tags first
            for tag_name in preferred_meta:
                meta_el = soup.find("meta", attrs={"property": tag_name}) or soup.find("meta", attrs={"name": tag_name})
                if meta_el and meta_el.get("content"):
                    dt = cls.parse_iso_or_rfc2822(meta_el["content"])
                    if dt:
                        is_future = dt > future_limit
                        return ExtractedDate(
                            datetime_utc=dt,
                            iso_utc=dt.isoformat(),
                            method=f"meta_preferred_{tag_name}",
                            confidence=0.92,
                            is_future=is_future,
                            raw_value=meta_el["content"],
                        )

            # Standard meta tags
            for attr_name, attr_val in META_DATE_TAGS:
                meta_el = soup.find("meta", attrs={attr_name: attr_val})
                if meta_el and meta_el.get("content"):
                    dt = cls.parse_iso_or_rfc2822(meta_el["content"])
                    if dt:
                        is_future = dt > future_limit
                        return ExtractedDate(
                            datetime_utc=dt,
                            iso_utc=dt.isoformat(),
                            method=f"meta_{attr_val}",
                            confidence=0.88,
                            is_future=is_future,
                            raw_value=meta_el["content"],
                        )

        # -------------------------------------------------------------
        # 2. Visible Page Content (Priority 2)
        # -------------------------------------------------------------
        if soup:
            # <time datetime="...">
            time_tag = soup.find("time")
            if time_tag:
                dt_val = time_tag.get("datetime")
                if dt_val:
                    dt = cls.parse_iso_or_rfc2822(dt_val)
                    if dt:
                        is_future = dt > future_limit
                        return ExtractedDate(
                            datetime_utc=dt,
                            iso_utc=dt.isoformat(),
                            method="visible_time_datetime",
                            confidence=0.85,
                            is_future=is_future,
                            raw_value=dt_val,
                        )

                # Check inner text of time tag
                time_text = time_tag.get_text(strip=True)
                if time_text:
                    # Check relative date inside time tag
                    dt_rel = cls.parse_relative_date(time_text, ref_time, timezone_name)
                    if dt_rel:
                        is_future = dt_rel > future_limit
                        return ExtractedDate(
                            datetime_utc=dt_rel,
                            iso_utc=dt_rel.isoformat(),
                            method="visible_time_relative",
                            confidence=0.80,
                            is_future=is_future,
                            raw_value=time_text,
                        )
                    dt_parsed = cls.parse_iso_or_rfc2822(time_text)
                    if dt_parsed:
                        is_future = dt_parsed > future_limit
                        return ExtractedDate(
                            datetime_utc=dt_parsed,
                            iso_utc=dt_parsed.isoformat(),
                            method="visible_time_text",
                            confidence=0.82,
                            is_future=is_future,
                            raw_value=time_text,
                        )

            # Custom date selector
            date_sel = selectors.get("date")
            if date_sel:
                date_el = soup.select_one(date_sel)
                if date_el:
                    # Check datetime attribute
                    if date_el.get("datetime"):
                        dt = cls.parse_iso_or_rfc2822(date_el["datetime"])
                        if dt:
                            is_future = dt > future_limit
                            return ExtractedDate(
                                datetime_utc=dt,
                                iso_utc=dt.isoformat(),
                                method="selector_datetime",
                                confidence=0.85,
                                is_future=is_future,
                                raw_value=date_el["datetime"],
                            )
                    raw_text = date_el.get_text(strip=True)
                    # Check relative
                    dt_rel = cls.parse_relative_date(raw_text, ref_time, timezone_name)
                    if dt_rel:
                        is_future = dt_rel > future_limit
                        return ExtractedDate(
                            datetime_utc=dt_rel,
                            iso_utc=dt_rel.isoformat(),
                            method="selector_relative",
                            confidence=0.80,
                            is_future=is_future,
                            raw_value=raw_text,
                        )
                    # Check ambiguous numeric
                    dt_num = cls.parse_ambiguous_numeric(raw_text, locale)
                    if dt_num:
                        is_future = dt_num > future_limit
                        return ExtractedDate(
                            datetime_utc=dt_num,
                            iso_utc=dt_num.isoformat(),
                            method="selector_numeric_locale",
                            confidence=0.78,
                            is_future=is_future,
                            raw_value=raw_text,
                        )
                    dt_iso = cls.parse_iso_or_rfc2822(raw_text)
                    if dt_iso:
                        is_future = dt_iso > future_limit
                        return ExtractedDate(
                            datetime_utc=dt_iso,
                            iso_utc=dt_iso.isoformat(),
                            method="selector_text",
                            confidence=0.80,
                            is_future=is_future,
                            raw_value=raw_text,
                        )

        # -------------------------------------------------------------
        # 3. URL and Context Fallback (Priority 4)
        # -------------------------------------------------------------
        if url:
            pattern = date_rules.get("url_date_pattern")
            if pattern:
                dt_url = cls.parse_url_date(url, pattern)
                if dt_url:
                    is_future = dt_url > future_limit
                    return ExtractedDate(
                        datetime_utc=dt_url,
                        iso_utc=dt_url.isoformat(),
                        method="url_date_regex",
                        confidence=0.70,
                        is_future=is_future,
                        raw_value=url,
                    )

        # -------------------------------------------------------------
        # 4. Sitemap lastmod fallback (if present in extra metadata)
        # -------------------------------------------------------------
        if date_rules.get("sitemap_lastmod"):
            dt_sitemap = cls.parse_iso_or_rfc2822(date_rules["sitemap_lastmod"])
            if dt_sitemap:
                is_future = dt_sitemap > future_limit
                return ExtractedDate(
                    datetime_utc=dt_sitemap,
                    iso_utc=dt_sitemap.isoformat(),
                    method="sitemap_lastmod_fallback",
                    confidence=0.50,
                    is_future=is_future,
                    raw_value=date_rules["sitemap_lastmod"],
                )

        # No date discovered
        return ExtractedDate(
            datetime_utc=None,
            iso_utc=None,
            method="not_found",
            confidence=0.0,
            is_future=False,
            raw_value=None,
        )
