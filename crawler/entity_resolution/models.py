"""Pydantic schemas and dataclasses for deterministic entity resolution."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class MatchStrategy(str, Enum):
    EXACT_CANONICAL_NAME = "EXACT_CANONICAL_NAME"
    EXACT_CONFIGURED_ALIAS = "EXACT_CONFIGURED_ALIAS"
    EXACT_NORMALIZED_ALIAS = "EXACT_NORMALIZED_ALIAS"
    OFFICIAL_DOMAIN = "OFFICIAL_DOMAIN"
    CONSERVATIVE_TOKEN_MATCH = "CONSERVATIVE_TOKEN_MATCH"
    UNRESOLVED = "UNRESOLVED"
    AMBIGUOUS_MULTI_CANDIDATE = "AMBIGUOUS_MULTI_CANDIDATE"


def current_iso_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


class EntitySeedRecord(BaseModel):
    """Configuration record for a known canonical entity."""
    model_config = ConfigDict(extra="ignore")

    canonical_id: str
    canonical_name: str
    verified_aliases: List[str] = Field(default_factory=list)
    normalized_aliases: List[str] = Field(default_factory=list)
    official_domains: List[str] = Field(default_factory=list)
    verification_url: Optional[str] = None


class EntityResolutionResult(BaseModel):
    """Entity Mapping Log entry representing the full audit trail of a resolution attempt."""
    model_config = ConfigDict(extra="ignore")

    source_record_id: str = Field(..., description="ID or content hash of source record")
    raw_entity_name: str = Field(..., description="Original raw entity name before normalization")
    normalized_entity_name: str = Field(..., description="Cleaned, normalized name")
    canonical_entity_id: Optional[str] = Field(default=None, description="Resolved canonical ID, or None")
    canonical_entity_name: Optional[str] = Field(default=None, description="Resolved canonical name, or None")
    match_strategy: MatchStrategy = Field(..., description="Strategy utilized to resolve")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score 0.0 to 1.0")
    aliases_used: List[str] = Field(default_factory=list, description="Matching aliases")
    domains_used: List[str] = Field(default_factory=list, description="Matching domains")
    resolver_version: str = Field(default="1.0.0", description="Resolver algorithm version")
    timestamp: str = Field(default_factory=current_iso_timestamp, description="Resolution UTC timestamp")
    unresolved_reason: Optional[str] = Field(default=None, description="Detailed reason if unresolved or ambiguous")

    def to_log_dict(self) -> Dict[str, Any]:
        """Returns JSON-serializable dictionary representation."""
        return self.model_dump()
