"""JSON API adapter for structured signal endpoints."""

import hashlib
import json
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple
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


class APISignalAdapter(BaseSignalAdapter):
    """Parses JSON API endpoints to discover and extract signals directly."""

    async def discover_candidates(
        self,
        session: aiohttp.ClientSession,
        client: HttpClient,
        limit: int = 50,
    ) -> AsyncGenerator[CandidateItem, None]:
        position = 0
        for endpoint_url in self.config.listing_urls:
            try:
                response_text = await client.fetch(endpoint_url)
                data = json.loads(response_text)

                items: List[Dict[str, Any]] = []
                if isinstance(data, list):
                    items = data
                elif isinstance(data, dict):
                    key = self.config.selectors.get("api_item_key")
                    if key and key in data and isinstance(data[key], list):
                        items = data[key]
                    else:
                        for v in data.values():
                            if isinstance(v, list):
                                items = v
                                break

                # Skip header/legal notices if RemoteOK or similar returns disclaimer in first element
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    if position >= limit:
                        return

                    # Resolve URL
                    url_field = self.config.selectors.get("url_field", "url")
                    raw_url = item.get(url_field)
                    if not raw_url:
                        # Some APIs provide id
                        item_id = item.get(self.config.selectors.get("id_field", "id"))
                        if item_id:
                            raw_url = f"{self.config.base_url}/job/{item_id}"
                    if not raw_url:
                        continue

                    # Title
                    title_field = self.config.selectors.get("title_field", "position")
                    title = item.get(title_field) or item.get("title") or ""

                    # Company / author
                    company_field = self.config.selectors.get("company_field", "company")
                    author_or_company = item.get(company_field)

                    # Date
                    date_field = self.config.selectors.get("date_field", "date")
                    raw_date = item.get(date_field) or item.get("epoch") or item.get("published_at")

                    candidate = CandidateItem(
                        source_id=self.config.id,
                        raw_url=str(raw_url),
                        title=str(title) if title else None,
                        published_date_raw=str(raw_date) if raw_date else None,
                        author_or_company=str(author_or_company) if author_or_company else None,
                        listing_position=position,
                        extra_metadata={"api_payload": item},
                    )
                    position += 1
                    yield candidate

            except Exception as exc:
                logger.error("Failed to fetch/parse API signals from %s: %s", endpoint_url, exc)

    async def extract_record(
        self,
        candidate: CandidateItem,
        session: aiohttp.ClientSession,
        client: HttpClient,
        freshness_gate: FreshnessGate,
        crawl_state: Optional[SourceCrawlStateModel] = None,
    ) -> Tuple[Optional[AnySignalRecord], FreshnessEvaluation]:
        canonical_url = canonicalize_signal_url(candidate.raw_url, self.config.base_url)
        payload = candidate.extra_metadata.get("api_payload", {})

        title = candidate.title or payload.get("title") or "Untitled Signal"
        company = candidate.author_or_company or payload.get("company") or self.config.name

        # Clean description
        desc_field = self.config.selectors.get("description_field", "description")
        raw_description = payload.get(desc_field, "")
        if "<" in raw_description and ">" in raw_description:
            # HTML description
            cleaned_soup = ContentCleaner.clean_html(raw_description)
            full_text = ContentCleaner.extract_text(cleaned_soup)
        else:
            full_text = str(raw_description).strip()

        # Location and salary
        loc_field = self.config.selectors.get("location_field", "location")
        location = payload.get(loc_field)

        sal_min = payload.get("salary_min")
        sal_max = payload.get("salary_max")
        salary = None
        if sal_min or sal_max:
            salary = f"${sal_min:,} - ${sal_max:,}" if sal_min and sal_max else f"${(sal_min or sal_max):,}"
        elif self.config.selectors.get("salary_field"):
            salary = str(payload.get(self.config.selectors["salary_field"])) if payload.get(self.config.selectors["salary_field"]) else None

        # Extract publication date
        extracted_date = DateParser.extract_date(
            feed_raw_date=candidate.published_date_raw,
            url=canonical_url,
            reference_time=freshness_gate.reference_time,
            timezone_name=self.config.timezone,
            locale=self.config.locale,
            clock_skew_minutes=int(freshness_gate.clock_skew_tolerance.total_seconds() / 60),
        )

        hash_payload = f"{self.config.id}:{title.strip().lower()}:{canonical_url}"
        content_hash = hashlib.sha256(hash_payload.encode("utf-8")).hexdigest()

        evaluation = freshness_gate.evaluate(
            extracted_date=extracted_date,
            candidate=candidate,
            canonical_url=canonical_url,
            content_hash=content_hash,
            crawl_state=crawl_state,
        )

        if evaluation.decision in (FreshnessDecision.ACCEPTED_VERIFIED, FreshnessDecision.ACCEPTED_INFERRED):
            record_id = str(uuid.uuid4())
            if self.config.type == "job":
                record = JobRecord(
                    id=record_id,
                    sourceId=self.config.id,
                    canonicalUrl=canonical_url,
                    title=title,
                    company=company,
                    location=str(location) if location else None,
                    employmentType=payload.get("employment_type") or ("Remote" if payload.get("remote") else None),
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
                    rawMetadata={"tags": payload.get("tags", [])},
                )
                return record, evaluation
            else:
                record = NewsRecord(
                    id=record_id,
                    sourceId=self.config.id,
                    canonicalUrl=canonical_url,
                    title=title,
                    author=candidate.author_or_company,
                    fullText=full_text,
                    summary=payload.get("summary"),
                    publishedAt=evaluation.published_at,
                    firstSeenAt=evaluation.first_seen_at,
                    ingestedAt=evaluation.ingested_at,
                    dateExtractionMethod=evaluation.date_extraction_method,
                    publishedAtConfidence=evaluation.published_at_confidence,
                    freshnessDecision=evaluation.decision.value,
                    freshnessReason=evaluation.reason,
                    contentHash=content_hash,
                    rawMetadata=payload,
                )
                return record, evaluation

        return None, evaluation
