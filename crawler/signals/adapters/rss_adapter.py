"""RSS and Atom feed adapter for news and job signal sources."""

import hashlib
import uuid
from typing import Any, AsyncGenerator, Dict, Optional, Tuple
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import aiohttp
from crawler.http_client import HttpClient
from crawler.logging import logger
from crawler.models.db import SourceCrawlStateModel
from crawler.signals.adapters.base import AnySignalRecord, BaseSignalAdapter
from crawler.signals.content_cleaner import ContentCleaner
from crawler.signals.date_parser import DateParser
from crawler.signals.freshness_gate import FreshnessEvaluation, FreshnessGate
from crawler.signals.models import CandidateItem, FreshnessDecision, JobRecord, NewsRecord
from crawler.signals.url_canonicalizer import canonicalize_signal_url


class RSSSignalAdapter(BaseSignalAdapter):
    """Parses RSS/Atom feeds to discover candidates, then extracts detail pages."""

    async def discover_candidates(
        self,
        session: aiohttp.ClientSession,
        client: HttpClient,
        limit: int = 50,
    ) -> AsyncGenerator[CandidateItem, None]:
        position = 0
        for listing_url in self.config.listing_urls:
            try:
                xml_text = await client.fetch(listing_url)
                soup = BeautifulSoup(xml_text, "xml")

                # Look for RSS items or Atom entries
                items = soup.find_all("item")
                if not items:
                    items = soup.find_all("entry")

                for item in items:
                    if position >= limit:
                        return

                    # Extract link
                    link = ""
                    link_el = item.find("link")
                    if link_el:
                        link = link_el.get("href") or link_el.get_text(strip=True)
                    if not link:
                        guid = item.find("guid") or item.find("id")
                        if guid and (guid.get_text().startswith("http://") or guid.get_text().startswith("https://")):
                            link = guid.get_text(strip=True)

                    if not link:
                        continue

                    link = urljoin(self.config.base_url, link)

                    # Extract title
                    title = ""
                    title_el = item.find("title")
                    if title_el:
                        title = title_el.get_text(strip=True)

                    # Filter keywords if configured (e.g. for job feeds)
                    filter_kws = self.config.date_rules.get("filter_keywords", [])
                    if filter_kws:
                        content_for_filter = (title + " " + item.get_text()).lower()
                        if not any(kw.lower() in content_for_filter for kw in filter_kws):
                            continue

                    # Extract raw pubDate
                    pub_date_raw = None
                    date_tag = (
                        item.find(["pubDate", "pubdate", "published", "updated", "date", "dc:date"])
                        or item.find(lambda t: t.name and (t.name.lower() in ("pubdate", "published", "updated", "date") or t.name.endswith(":date")))
                    )
                    if date_tag:
                        pub_date_raw = date_tag.get_text(strip=True)

                    # Extract author or company
                    author_or_company = None
                    creator_tag = (
                        item.find(["creator", "dc:creator", "author", "dc:author", "company"])
                        or item.find(lambda t: t.name and (t.name in ("creator", "author", "company") or t.name.endswith(":creator") or t.name.endswith(":author")))
                    )
                    if creator_tag:
                        author_or_company = creator_tag.get_text(strip=True)

                    candidate = CandidateItem(
                        source_id=self.config.id,
                        raw_url=link,
                        title=title,
                        published_date_raw=pub_date_raw,
                        author_or_company=author_or_company,
                        listing_position=position,
                        extra_metadata={
                            "feed_description": (item.find("description") or item.find("summary") or item).get_text(strip=True)
                        },
                    )
                    position += 1
                    yield candidate

            except Exception as exc:
                logger.error("Failed to discover candidates from RSS feed %s: %s", listing_url, exc)
                raise

    async def extract_record(
        self,
        candidate: CandidateItem,
        session: aiohttp.ClientSession,
        client: HttpClient,
        freshness_gate: FreshnessGate,
        crawl_state: Optional[SourceCrawlStateModel] = None,
    ) -> Tuple[Optional[AnySignalRecord], FreshnessEvaluation]:
        canonical_url = canonicalize_signal_url(candidate.raw_url, self.config.base_url)

        # Fetch detail page HTML
        html_text = ""
        try:
            html_text = await client.fetch(canonical_url)
        except Exception as exc:
            logger.warning("Could not fetch detail page %s: %s. Using feed fallback if possible.", canonical_url, exc)

        # Clean content & extract text
        if self.config.type == "news":
            extracted = ContentCleaner.extract_article_content(
                html_text or candidate.extra_metadata.get("feed_description", ""),
                selectors=self.config.selectors,
            )
            title = extracted["title"] or candidate.title or "Untitled Article"
            author = extracted["author"] or candidate.author_or_company
            full_text = extracted["full_text"] or candidate.extra_metadata.get("feed_description", "")
            summary = extracted["summary"] or candidate.extra_metadata.get("feed_description", "")
        else:
            extracted = ContentCleaner.extract_job_content(
                html_text or candidate.extra_metadata.get("feed_description", ""),
                selectors=self.config.selectors,
            )
            title = extracted["title"] or candidate.title or "Untitled Job"
            company = extracted["company"] or candidate.author_or_company or self.config.name
            location = extracted["location"]
            salary = extracted["salary"]
            full_text = extracted["description_full_text"] or candidate.extra_metadata.get("feed_description", "")

        # Extract publication date
        extracted_date = DateParser.extract_date(
            html_text=html_text,
            feed_raw_date=candidate.published_date_raw,
            url=canonical_url,
            reference_time=freshness_gate.reference_time,
            timezone_name=self.config.timezone,
            locale=self.config.locale,
            selectors=self.config.selectors,
            date_rules=self.config.date_rules,
            clock_skew_minutes=int(freshness_gate.clock_skew_tolerance.total_seconds() / 60),
        )

        # Compute semantic content hash
        hash_payload = f"{self.config.id}:{title.strip().lower()}:{canonical_url}"
        content_hash = hashlib.sha256(hash_payload.encode("utf-8")).hexdigest()

        # Freshness evaluation
        evaluation = freshness_gate.evaluate(
            extracted_date=extracted_date,
            candidate=candidate,
            canonical_url=canonical_url,
            content_hash=content_hash,
            crawl_state=crawl_state,
        )

        if evaluation.decision in (FreshnessDecision.ACCEPTED_VERIFIED, FreshnessDecision.ACCEPTED_INFERRED):
            record_id = str(uuid.uuid4())
            if self.config.type == "news":
                record = NewsRecord(
                    id=record_id,
                    sourceId=self.config.id,
                    canonicalUrl=canonical_url,
                    title=title,
                    author=author,
                    fullText=full_text,
                    summary=summary,
                    publishedAt=evaluation.published_at,
                    firstSeenAt=evaluation.first_seen_at,
                    ingestedAt=evaluation.ingested_at,
                    dateExtractionMethod=evaluation.date_extraction_method,
                    publishedAtConfidence=evaluation.published_at_confidence,
                    freshnessDecision=evaluation.decision.value,
                    freshnessReason=evaluation.reason,
                    contentHash=content_hash,
                    rawMetadata={"raw_date_extracted": extracted_date.raw_value},
                )
                return record, evaluation
            else:
                record = JobRecord(
                    id=record_id,
                    sourceId=self.config.id,
                    canonicalUrl=canonical_url,
                    title=title,
                    company=company,
                    location=location,
                    employmentType=None,
                    salary=salary,
                    descriptionFullText=full_text,
                    publishedAt=evaluation.published_at,
                    firstSeenAt=evaluation.first_seen_at,
                    ingestedAt=evaluation.ingested_at,
                    dateExtractionMethod=evaluation.date_extraction_method,
                    publishedAtConfidence=evaluation.published_at_confidence,
                    freshnessDecision=evaluation.decision.value,
                    freshnessReason=evaluation.reason,
                    contentHash=content_hash,
                    rawMetadata={"raw_date_extracted": extracted_date.raw_value},
                )
                return record, evaluation

        return None, evaluation
