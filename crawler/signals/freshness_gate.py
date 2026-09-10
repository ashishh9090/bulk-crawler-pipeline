"""Strict 24-hour freshness gate and stateful missing-date heuristic engine."""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Set
from crawler.models.db import SourceCrawlStateModel
from crawler.signals.date_parser import ExtractedDate
from crawler.signals.models import CandidateItem, FreshnessDecision
from crawler.signals.url_canonicalizer import compute_url_hash


@dataclass
class FreshnessEvaluation:
    """Output of freshness evaluation for a candidate item."""
    decision: FreshnessDecision
    reason: str
    published_at: Optional[str]
    published_at_confidence: float
    date_extraction_method: str
    first_seen_at: str
    ingested_at: str


class FreshnessGate:
    """Evaluates candidate items against strict 24-hour window and stateful freshness heuristics."""

    def __init__(
        self,
        reference_time: Optional[datetime] = None,
        freshness_window_hours: int = 24,
        clock_skew_minutes: int = 15,
    ):
        self.reference_time = reference_time or datetime.now(timezone.utc)
        if self.reference_time.tzinfo is None:
            self.reference_time = self.reference_time.replace(tzinfo=timezone.utc)

        self.freshness_window_hours = freshness_window_hours
        self.clock_skew_tolerance = timedelta(minutes=clock_skew_minutes)
        self.cutoff_time = self.reference_time - timedelta(hours=freshness_window_hours)
        self.future_limit = self.reference_time + self.clock_skew_tolerance

    def evaluate(
        self,
        extracted_date: ExtractedDate,
        candidate: CandidateItem,
        canonical_url: str,
        content_hash: str,
        crawl_state: Optional[SourceCrawlStateModel] = None,
        first_seen_at: Optional[datetime] = None,
    ) -> FreshnessEvaluation:
        """Evaluates candidate and returns explicit freshness decision."""
        first_seen = first_seen_at or self.reference_time
        if first_seen.tzinfo is None:
            first_seen = first_seen.replace(tzinfo=timezone.utc)

        ingested_at_str = self.reference_time.isoformat()
        first_seen_at_str = first_seen.isoformat()

        # -------------------------------------------------------------
        # 1. Strict Date Available
        # -------------------------------------------------------------
        if extracted_date.datetime_utc is not None:
            dt = extracted_date.datetime_utc
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)

            # Check future date beyond clock skew
            if dt > self.future_limit:
                return FreshnessEvaluation(
                    decision=FreshnessDecision.REJECTED_STALE,
                    reason=(
                        f"Publication date {dt.isoformat()} is in the future beyond "
                        f"{int(self.clock_skew_tolerance.total_seconds() / 60)}m clock skew tolerance."
                    ),
                    published_at=dt.isoformat(),
                    published_at_confidence=extracted_date.confidence,
                    date_extraction_method=extracted_date.method,
                    first_seen_at=first_seen_at_str,
                    ingested_at=ingested_at_str,
                )

            # Check 24-hour freshness boundary
            if dt >= self.cutoff_time:
                return FreshnessEvaluation(
                    decision=FreshnessDecision.ACCEPTED_VERIFIED,
                    reason=(
                        f"Verified publication date {dt.isoformat()} is within "
                        f"{self.freshness_window_hours}h freshness window (cutoff: {self.cutoff_time.isoformat()})."
                    ),
                    published_at=dt.isoformat(),
                    published_at_confidence=extracted_date.confidence,
                    date_extraction_method=extracted_date.method,
                    first_seen_at=first_seen_at_str,
                    ingested_at=ingested_at_str,
                )
            else:
                return FreshnessEvaluation(
                    decision=FreshnessDecision.REJECTED_STALE,
                    reason=(
                        f"Publication date {dt.isoformat()} is older than "
                        f"{self.freshness_window_hours}h freshness window (cutoff: {self.cutoff_time.isoformat()})."
                    ),
                    published_at=dt.isoformat(),
                    published_at_confidence=extracted_date.confidence,
                    date_extraction_method=extracted_date.method,
                    first_seen_at=first_seen_at_str,
                    ingested_at=ingested_at_str,
                )

        # -------------------------------------------------------------
        # 2. Missing Strict Date: Stateful Heuristic
        # -------------------------------------------------------------
        # Conservative default: reject unknown if no prior successful baseline
        if crawl_state is None or crawl_state.last_successful_crawl_at is None:
            return FreshnessEvaluation(
                decision=FreshnessDecision.REJECTED_UNKNOWN,
                reason="Missing publication date and no prior successful baseline crawl state to infer freshness.",
                published_at=None,
                published_at_confidence=0.0,
                date_extraction_method="heuristic_missing_baseline",
                first_seen_at=first_seen_at_str,
                ingested_at=ingested_at_str,
            )

        last_success = crawl_state.last_successful_crawl_at
        if last_success.tzinfo is None:
            last_success = last_success.replace(tzinfo=timezone.utc)

        # Parse observed URLs / hashes snapshot
        observed_hashes: Set[str] = set()
        if crawl_state.observed_urls_snapshot:
            try:
                snapshot = json.loads(crawl_state.observed_urls_snapshot)
                if isinstance(snapshot, list):
                    observed_hashes = set(snapshot)
            except Exception:
                pass

        url_hash = compute_url_hash(canonical_url)

        # Check 1: Was this URL or content already observed in prior snapshot?
        if url_hash in observed_hashes or content_hash in observed_hashes:
            return FreshnessEvaluation(
                decision=FreshnessDecision.REJECTED_UNKNOWN,
                reason="Item was already observed in prior successful source snapshot; cannot infer fresh publication.",
                published_at=None,
                published_at_confidence=0.0,
                date_extraction_method="heuristic_previously_observed",
                first_seen_at=first_seen_at_str,
                ingested_at=ingested_at_str,
            )

        # Check 2: First seen must not be prior to previous successful run
        if first_seen < last_success - timedelta(minutes=5):
            return FreshnessEvaluation(
                decision=FreshnessDecision.REJECTED_UNKNOWN,
                reason=f"Item first seen ({first_seen.isoformat()}) prior to last successful crawl ({last_success.isoformat()}).",
                published_at=None,
                published_at_confidence=0.0,
                date_extraction_method="heuristic_stale_first_seen",
                first_seen_at=first_seen_at_str,
                ingested_at=ingested_at_str,
            )

        # Check 3: Listing position / order (if position indicates deep pagination)
        if candidate.listing_position > 25:
            return FreshnessEvaluation(
                decision=FreshnessDecision.REJECTED_UNKNOWN,
                reason=f"Candidate listing position ({candidate.listing_position}) exceeds top recency window.",
                published_at=None,
                published_at_confidence=0.0,
                date_extraction_method="heuristic_deep_listing_position",
                first_seen_at=first_seen_at_str,
                ingested_at=ingested_at_str,
            )

        # All signals confidently confirm the item is fresh since last successful run
        return FreshnessEvaluation(
            decision=FreshnessDecision.ACCEPTED_INFERRED,
            reason=(
                f"Accepted via heuristic: item is new since last successful run ({last_success.isoformat()}), "
                f"absent from prior snapshot, and ranked at position {candidate.listing_position}."
            ),
            published_at=None,  # Never infer an exact publishedAt when unavailable
            published_at_confidence=0.65,
            date_extraction_method="heuristic_stateful_new_since_last_run",
            first_seen_at=first_seen_at_str,
            ingested_at=ingested_at_str,
        )
