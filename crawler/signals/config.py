"""Source configuration and runtime settings for Phase II signal ingestion."""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class SourceConfig(BaseModel):
    """Configuration metadata for an individual news or job source."""
    model_config = ConfigDict(extra="ignore")

    id: str = Field(..., min_length=1, description="Unique source identifier")
    name: str = Field(..., min_length=1, description="Human-readable source name")
    type: Literal["news", "job"] = Field(..., description="Source type (news or job)")
    base_url: str = Field(..., min_length=1, description="Root URL of origin platform")
    listing_urls: List[str] = Field(..., min_length=1, description="Feed, listing or API endpoint URLs")
    crawl_interval_minutes: int = Field(default=60, ge=1, description="Crawl interval frequency in minutes")
    timezone: str = Field(default="UTC", description="Origin timezone for relative dates")
    locale: str = Field(default="en_US", description="Default locale for date disambiguation")
    adapter_type: Literal["rss", "api", "html_listing"] = Field(
        default="rss", description="Adapter implementation type"
    )
    selectors: Dict[str, Any] = Field(default_factory=dict, description="CSS selectors or field mappings")
    date_rules: Dict[str, Any] = Field(default_factory=dict, description="Source-specific date parsing rules")
    rate_limit_delay: float = Field(default=0.5, ge=0.0, description="Polite delay between requests in seconds")
    concurrency: int = Field(default=2, ge=1, le=10, description="Source-specific max concurrency")
    headers: Dict[str, str] = Field(default_factory=dict, description="Custom HTTP headers")


class SignalSettings(BaseSettings):
    """Runtime ingestion settings."""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    freshness_window_hours: int = Field(default=24, alias="FRESHNESS_WINDOW_HOURS")
    clock_skew_tolerance_minutes: int = Field(default=15, alias="CLOCK_SKEW_TOLERANCE_MINUTES")
    user_agent: str = Field(
        default="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 (AI-Intelligence-Signal-Bot/2.0)",
        alias="SIGNAL_USER_AGENT"
    )
    request_timeout_seconds: float = Field(default=20.0, alias="SIGNAL_REQUEST_TIMEOUT")
    max_retries: int = Field(default=3, alias="SIGNAL_MAX_RETRIES")
    backoff_factor: float = Field(default=1.5, alias="SIGNAL_BACKOFF_FACTOR")
    sources_config_path: Optional[str] = Field(default=None, alias="SOURCES_CONFIG_PATH")
    honor_robots_txt: bool = Field(default=True, alias="HONOR_ROBOTS_TXT")


signal_settings = SignalSettings()


def get_default_sources_config_path() -> Path:
    """Returns absolute path to bundled sources.json."""
    return Path(__file__).resolve().parent / "sources.json"


def load_sources_config(path: Optional[str] = None) -> List[SourceConfig]:
    """Loads and validates source configurations from JSON file."""
    target_path = Path(path) if path else Path(signal_settings.sources_config_path or get_default_sources_config_path())
    if not target_path.exists():
        raise FileNotFoundError(f"Source configuration file not found at: {target_path}")

    with open(target_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError("Sources configuration root must be a JSON array")

    return [SourceConfig.model_validate(item) for item in data]
