"""Canonical typed schemas for high-fidelity news and job signal records."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Field


class FreshnessDecision(str, Enum):
    ACCEPTED_VERIFIED = "accepted_verified"
    ACCEPTED_INFERRED = "accepted_inferred"
    REJECTED_STALE = "rejected_stale"
    REJECTED_UNKNOWN = "rejected_unknown"


def current_iso_timestamp() -> str:
    """Returns current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


class NewsRecord(BaseModel):
    """Canonical model for news articles."""
    model_config = ConfigDict(extra="ignore")

    id: str = Field(..., description="Unique record identifier (UUID or deterministic ID)")
    sourceId: str = Field(..., min_length=1, description="Source identifier e.g. techcrunch_ai")
    canonicalUrl: str = Field(..., min_length=1, description="Normalized canonical URL")
    title: str = Field(..., min_length=1, description="Article title")
    author: Optional[str] = Field(default=None, description="Author or editorial byline")
    fullText: str = Field(..., min_length=1, description="Cleaned, extracted readable full text")
    summary: Optional[str] = Field(default=None, description="Article summary or excerpt")
    publishedAt: Optional[str] = Field(
        default=None,
        description="Verified publication timestamp in ISO 8601 UTC, or None if inferred/unknown"
    )
    firstSeenAt: str = Field(default_factory=current_iso_timestamp, description="First time item was discovered (UTC)")
    ingestedAt: str = Field(default_factory=current_iso_timestamp, description="Timestamp of ingestion run (UTC)")
    dateExtractionMethod: str = Field(default="unknown", description="Extraction strategy used to discover date")
    publishedAtConfidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Confidence score for published date")
    freshnessDecision: str = Field(..., description="accepted_verified | accepted_inferred | rejected_stale | rejected_unknown")
    freshnessReason: str = Field(..., description="Human-readable decision explanation")
    contentHash: str = Field(..., min_length=1, description="SHA-256 hash of canonical content")
    rawMetadata: Dict[str, Any] = Field(default_factory=dict, description="Auditing and extraction metadata")


class JobRecord(BaseModel):
    """Canonical model for AI job postings."""
    model_config = ConfigDict(extra="ignore")

    id: str = Field(..., description="Unique record identifier (UUID or deterministic ID)")
    sourceId: str = Field(..., min_length=1, description="Source identifier e.g. ai_jobs_net")
    canonicalUrl: str = Field(..., min_length=1, description="Normalized canonical URL")
    title: str = Field(..., min_length=1, description="Job title")
    company: str = Field(..., min_length=1, description="Hiring company or organization")
    location: Optional[str] = Field(default=None, description="Work location (e.g. Remote, San Francisco, CA)")
    employmentType: Optional[str] = Field(default=None, description="e.g. Full-time, Contract, Part-time")
    salary: Optional[str] = Field(default=None, description="Salary or compensation range")
    descriptionFullText: str = Field(..., min_length=1, description="Full job description text")
    publishedAt: Optional[str] = Field(
        default=None,
        description="Verified publication timestamp in ISO 8601 UTC, or None if inferred/unknown"
    )
    firstSeenAt: str = Field(default_factory=current_iso_timestamp, description="First time job was discovered (UTC)")
    ingestedAt: str = Field(default_factory=current_iso_timestamp, description="Timestamp of ingestion run (UTC)")
    dateExtractionMethod: str = Field(default="unknown", description="Extraction strategy used to discover date")
    publishedAtConfidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Confidence score for published date")
    freshnessDecision: str = Field(..., description="accepted_verified | accepted_inferred | rejected_stale | rejected_unknown")
    freshnessReason: str = Field(..., description="Human-readable decision explanation")
    contentHash: str = Field(..., min_length=1, description="SHA-256 hash of canonical content")
    rawMetadata: Dict[str, Any] = Field(default_factory=dict, description="Auditing and extraction metadata")


class CandidateItem(BaseModel):
    """Represents a discovered listing item prior to detail extraction and freshness filtering."""
    model_config = ConfigDict(extra="ignore")

    source_id: str
    raw_url: str
    title: Optional[str] = None
    published_date_raw: Optional[str] = None
    author_or_company: Optional[str] = None
    listing_position: int = 0
    extra_metadata: Dict[str, Any] = Field(default_factory=dict)


class RunSummary(BaseModel):
    """Summary of an ingestion run for a single source."""
    model_config = ConfigDict(extra="ignore")

    source_id: str
    run_id: str
    status: str  # SUCCESS, PARTIAL, FAILED
    started_at: str
    completed_at: str
    candidates_discovered: int = 0
    candidates_fetched: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    rejection_breakdown: Dict[str, int] = Field(default_factory=dict)
    error_count: int = 0
    errors: List[str] = Field(default_factory=list)
    latency_ms: float = 0.0
