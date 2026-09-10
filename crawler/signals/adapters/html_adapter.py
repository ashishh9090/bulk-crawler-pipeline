"""HTML listing and detail crawler adapter for signal sources."""

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


class HTMLSignalAdapter(BaseSignalAdapter):
    """Scrapes HTML listing pages to discover links, then crawls detail pages."""

    async def discover_candidates(
        self,
        session: aiohttp.ClientSession,
        client: HttpClient,
        limit: int = 50,
    ) -> AsyncGenerator[CandidateItem, None]:
        position = 0
        container_sel = self.config.selectors.get("item_container", "article, a[href]")
        link_sel = self.config.selectors.get("link", "")
        title_sel = self.config.selectors.get("listing_title", "h2, h3, .title")
        company_sel = self.config.selectors.get("listing_company", ".company")

        for listing_url in self.config.listing_urls:
            try:
                html_text = await client.fetch(listing_url)
                soup = BeautifulSoup(html_text, "lxml")

                items = soup.select(container_sel)
                for item in items:
                    if position >= limit:
                        return

                    # Find link
                    link = ""
                    if link_sel:
                        link_el = item.select_one(link_sel)
                        if link_el and link_el.get("href"):
                            link = link_el["href"]
                    elif item.name == "a" and item.get("href"):
                        link = item["href"]
                    else:
                        link_el = item.find("a")
                        if link_el and link_el.get("href"):
                            link = link_el["href"]

                    if not link or link.startswith("#") or link.startswith("javascript:"):
                        continue

                    full_url = urljoin(self.config.base_url, link)

                    # Title
                    title = ""
                    if title_sel:
                        title_el = item.select_one(title_sel)
                        if title_el:
                            title = title_el.get_text(strip=True)
                    if not title:
                        title = item.get_text(separator=" ", strip=True)[:120]

                    # Company / author
                    author_or_company = None
                    if company_sel:
                        comp_el = item.select_one(company_sel)
                        if comp_el:
                            author_or_company = comp_el.get_text(strip=True)

                    candidate = CandidateItem(
                        source_id=self.config.id,
                        raw_url=full_url,
                        title=title if title else None,
                        author_or_company=author_or_company,
                        listing_position=position,
                    )
                    position += 1
                    yield candidate

            except Exception as exc:
                logger.error("Failed to discover HTML candidates from %s: %s", listing_url, exc)

    async def extract_record(
        self,
        candidate: CandidateItem,
        session: aiohttp.ClientSession,
        client: HttpClient,
        freshness_gate: FreshnessGate,
        crawl_state: Optional[SourceCrawlStateModel] = None,
    ) -> Tuple[Optional[AnySignalRecord], FreshnessEvaluation]:
        canonical_url = canonicalize_signal_url(candidate.raw_url, self.config.base_url)

        # Fetch detail page
        html_text = ""
        try:
            html_text = await client.fetch(canonical_url)
        except Exception as exc:
            logger.warning("Could not fetch detail page %s: %s", canonical_url, exc)

        if self.config.type == "job":
            extracted = ContentCleaner.extract_job_content(
                html_text, selectors=self.config.selectors
            )
            title = extracted["title"] or candidate.title or "Untitled Job"
            company = extracted["company"] or candidate.author_or_company or self.config.name
            location = extracted["location"]
            salary = extracted["salary"]
            full_text = extracted["description_full_text"]
        else:
            extracted = ContentCleaner.extract_article_content(
                html_text, selectors=self.config.selectors
            )
            title = extracted["title"] or candidate.title or "Untitled Article"
            author = extracted["author"] or candidate.author_or_company
            full_text = extracted["full_text"]
            summary = extracted["summary"]

        extracted_date = DateParser.extract_date(
            html_text=html_text,
            url=canonical_url,
            reference_time=freshness_gate.reference_time,
            timezone_name=self.config.timezone,
            locale=self.config.locale,
            selectors=self.config.selectors,
            date_rules=self.config.date_rules,
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
                    location=location,
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
            else:
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

        return None, evaluation
