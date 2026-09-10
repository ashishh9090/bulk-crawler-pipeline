"""Pydantic v2 schemas validating records for all target entity types."""

from datetime import datetime, timezone
from enum import Enum
from typing import List, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator


class RecordType(str, Enum):
    STARTUP = "STARTUP"
    PRODUCT = "PRODUCT"
    RESEARCH_PAPER = "RESEARCH_PAPER"
    NEWS = "NEWS"
    JOB = "JOB"


PricingModel = Literal["FREE", "FREEMIUM", "PAID", "ENTERPRISE"]


def current_iso_timestamp() -> str:
    """Returns current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


class SourceModel(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str = Field(..., min_length=1, description="Origin platform or provider name")
    url: str = Field(..., min_length=1, description="Legitimate, verifiable source URL")


# ==============================================================================
# STARTUP SCHEMA
# ==============================================================================

class StartupData(BaseModel):
    model_config = ConfigDict(extra="ignore")
    employeeCount: Optional[int] = Field(
        default=None,
        description="Verified employee count, or null if unverified"
    )

    @field_validator("employeeCount", mode="before")
    @classmethod
    def parse_employee_count(cls, v: Optional[Union[int, str]]) -> Optional[int]:
        if v is None or v == "":
            return None
        try:
            val = int(v)
            return val if val >= 0 else None
        except (ValueError, TypeError):
            return None


class StartupContent(BaseModel):
    model_config = ConfigDict(extra="ignore")
    entityName: str = Field(..., min_length=1, description="Name of the startup / company")
    data: StartupData = Field(default_factory=StartupData)


class StartupRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")
    schemaVersion: Literal["1.0"] = "1.0"
    recordType: Literal["STARTUP"] = "STARTUP"
    source: SourceModel
    content: StartupContent
    collectedAt: str = Field(default_factory=current_iso_timestamp)


# ==============================================================================
# PRODUCT SCHEMA
# ==============================================================================

class ProductContent(BaseModel):
    model_config = ConfigDict(extra="ignore")
    startupName: str = Field(..., min_length=1, description="Maker, company, or startup name")
    pricingModel: PricingModel = Field(..., description="One of: FREE, FREEMIUM, PAID, ENTERPRISE")

    @field_validator("pricingModel", mode="before")
    @classmethod
    def normalize_pricing_model(cls, v: str) -> str:
        if not isinstance(v, str):
            raise ValueError("Pricing model must be a string")
        norm = v.strip().upper()
        if "FREE TRIAL" in norm or "FREEMIUM" in norm:
            return "FREEMIUM"
        if "FREE" in norm or "OPEN SOURCE" in norm:
            return "FREE"
        if "ENTERPRISE" in norm or "CUSTOM" in norm or "QUOTE" in norm:
            return "ENTERPRISE"
        if "PAID" in norm or "COMMERCIAL" in norm or "SUBSCRIPTION" in norm or "$" in norm:
            return "PAID"
        if norm in ("FREE", "FREEMIUM", "PAID", "ENTERPRISE"):
            return norm
        raise ValueError(f"Invalid pricing model: {v}. Must map to FREE, FREEMIUM, PAID, or ENTERPRISE")


class ProductRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")
    schemaVersion: Literal["1.0"] = "1.0"
    recordType: Literal["PRODUCT"] = "PRODUCT"
    source: SourceModel
    content: ProductContent
    collectedAt: str = Field(default_factory=current_iso_timestamp)


# ==============================================================================
# RESEARCH PAPER SCHEMA
# ==============================================================================

class PaperContent(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: str = Field(..., min_length=1, description="Official paper title")
    authors: List[str] = Field(default_factory=list, description="List of paper author names")
    paper_url: str = Field(..., min_length=1, description="Official canonical paper URL")
    github_url: Optional[str] = Field(
        default=None,
        description="Linked GitHub repository URL, or null if none available"
    )
    github_stars: int = Field(
        default=0,
        ge=0,
        description="Exact live GitHub stargazers count from GitHub API"
    )
    published_date: str = Field(..., description="ISO-8601 publication date")

    @field_validator("github_url", mode="before")
    @classmethod
    def clean_github_url(cls, v: Optional[str]) -> Optional[str]:
        if not v or not isinstance(v, str):
            return None
        cleaned = v.strip()
        if "github.com/" in cleaned.lower():
            # Strip trailing .git, slash, issues/pulls suffix if attached
            import re
            m = re.search(r"https?://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", cleaned)
            if m:
                url = m.group(0).rstrip("/")
                if url.endswith(".git"):
                    url = url[:-4]
                return url
        return None


class ResearchPaperRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")
    schemaVersion: Literal["1.0"] = "1.0"
    recordType: Literal["RESEARCH_PAPER"] = "RESEARCH_PAPER"
    source: SourceModel
    content: PaperContent
    collectedAt: str = Field(default_factory=current_iso_timestamp)


AnyCrawlRecord = Union[StartupRecord, ProductRecord, ResearchPaperRecord]

# Phase II Signal Records
from crawler.signals.models import NewsRecord, JobRecord  # noqa: E402
AnySignalRecord = Union[NewsRecord, JobRecord]
