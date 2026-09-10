"""Unit tests for strict 24-hour freshness gate and stateful heuristic."""

import json
from datetime import datetime, timedelta, timezone
import pytest
from crawler.models.db import SourceCrawlStateModel
from crawler.signals.date_parser import ExtractedDate
from crawler.signals.freshness_gate import FreshnessGate
from crawler.signals.models import CandidateItem, FreshnessDecision
from crawler.signals.url_canonicalizer import compute_url_hash


@pytest.fixture
def ref_time():
    return datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def freshness_gate(ref_time):
    return FreshnessGate(
        reference_time=ref_time,
        freshness_window_hours=24,
        clock_skew_minutes=15,
    )


def test_item_inside_24h_boundary(freshness_gate, ref_time):
    # 23 hours 59 minutes ago -> should be accepted
    pub_dt = ref_time - timedelta(hours=23, minutes=59)
    extracted = ExtractedDate(
        datetime_utc=pub_dt,
        iso_utc=pub_dt.isoformat(),
        method="json_ld",
        confidence=0.98,
        is_future=False,
    )
    cand = CandidateItem(source_id="techcrunch_ai", raw_url="https://techcrunch.com/article1")
    eval_res = freshness_gate.evaluate(
        extracted_date=extracted,
        candidate=cand,
        canonical_url=cand.raw_url,
        content_hash="hash1",
    )
    assert eval_res.decision == FreshnessDecision.ACCEPTED_VERIFIED
    assert eval_res.published_at == pub_dt.isoformat()
    assert eval_res.published_at_confidence == 0.98
    assert "within 24h" in eval_res.reason


def test_item_outside_24h_boundary(freshness_gate, ref_time):
    # 24 hours 1 minute ago -> should be rejected as stale
    pub_dt = ref_time - timedelta(hours=24, minutes=1)
    extracted = ExtractedDate(
        datetime_utc=pub_dt,
        iso_utc=pub_dt.isoformat(),
        method="json_ld",
        confidence=0.98,
        is_future=False,
    )
    cand = CandidateItem(source_id="techcrunch_ai", raw_url="https://techcrunch.com/article_stale")
    eval_res = freshness_gate.evaluate(
        extracted_date=extracted,
        candidate=cand,
        canonical_url=cand.raw_url,
        content_hash="hash2",
    )
    assert eval_res.decision == FreshnessDecision.REJECTED_STALE
    assert "older than 24h" in eval_res.reason


def test_future_date_rejected(freshness_gate, ref_time):
    # 30 mins in future -> rejected
    pub_dt = ref_time + timedelta(minutes=30)
    extracted = ExtractedDate(
        datetime_utc=pub_dt,
        iso_utc=pub_dt.isoformat(),
        method="feed_pubdate",
        confidence=0.95,
        is_future=True,
    )
    cand = CandidateItem(source_id="techcrunch_ai", raw_url="https://techcrunch.com/article_future")
    eval_res = freshness_gate.evaluate(
        extracted_date=extracted,
        candidate=cand,
        canonical_url=cand.raw_url,
        content_hash="hash_fut",
    )
    assert eval_res.decision == FreshnessDecision.REJECTED_STALE
    assert "in the future" in eval_res.reason


def test_missing_date_rejected_when_no_baseline(freshness_gate):
    extracted = ExtractedDate(
        datetime_utc=None,
        iso_utc=None,
        method="not_found",
        confidence=0.0,
        is_future=False,
    )
    cand = CandidateItem(source_id="ai_jobs_net", raw_url="https://ai-jobs.net/job/123", listing_position=0)
    # No crawl state
    eval_res = freshness_gate.evaluate(
        extracted_date=extracted,
        candidate=cand,
        canonical_url=cand.raw_url,
        content_hash="hash_undated",
        crawl_state=None,
    )
    assert eval_res.decision == FreshnessDecision.REJECTED_UNKNOWN
    assert "no prior successful baseline" in eval_res.reason


def test_missing_date_accepted_via_heuristic(freshness_gate, ref_time):
    extracted = ExtractedDate(
        datetime_utc=None,
        iso_utc=None,
        method="not_found",
        confidence=0.0,
        is_future=False,
    )
    cand_url = "https://ai-jobs.net/job/new-fresh-posting"
    cand = CandidateItem(source_id="ai_jobs_net", raw_url=cand_url, listing_position=2)

    # Prior crawl was 2 hours ago
    last_success = ref_time - timedelta(hours=2)
    state = SourceCrawlStateModel(
        source_id="ai_jobs_net",
        last_successful_crawl_at=last_success,
        observed_urls_snapshot=json.dumps(["prior_hash_1", "prior_hash_2"]),
    )

    eval_res = freshness_gate.evaluate(
        extracted_date=extracted,
        candidate=cand,
        canonical_url=cand_url,
        content_hash="new_content_hash",
        crawl_state=state,
        first_seen_at=ref_time,
    )
    assert eval_res.decision == FreshnessDecision.ACCEPTED_INFERRED
    assert eval_res.published_at is None  # Requirement: never infer exact publishedAt
    assert eval_res.published_at_confidence == 0.65
    assert "Accepted via heuristic" in eval_res.reason


def test_missing_date_rejected_if_already_in_snapshot(freshness_gate, ref_time):
    extracted = ExtractedDate(
        datetime_utc=None,
        iso_utc=None,
        method="not_found",
        confidence=0.0,
        is_future=False,
    )
    cand_url = "https://ai-jobs.net/job/known-posting"
    url_hash = compute_url_hash(cand_url)
    cand = CandidateItem(source_id="ai_jobs_net", raw_url=cand_url, listing_position=1)

    state = SourceCrawlStateModel(
        source_id="ai_jobs_net",
        last_successful_crawl_at=ref_time - timedelta(hours=1),
        observed_urls_snapshot=json.dumps([url_hash]),
    )

    eval_res = freshness_gate.evaluate(
        extracted_date=extracted,
        candidate=cand,
        canonical_url=cand_url,
        content_hash="hash_x",
        crawl_state=state,
    )
    assert eval_res.decision == FreshnessDecision.REJECTED_UNKNOWN
    assert "already observed" in eval_res.reason
