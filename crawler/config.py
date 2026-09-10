"""Configuration management using Pydantic Settings and environment variables."""

import os
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Production configuration loaded from environment or .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Concurrency and bounded worker execution
    concurrency_limit: int = Field(default=50, alias="CONCURRENCY_LIMIT")
    per_domain_concurrency: int = Field(default=5, alias="PER_DOMAIN_CONCURRENCY")
    request_timeout_seconds: float = Field(default=30.0, alias="REQUEST_TIMEOUT_SECONDS")
    rate_limit_delay_seconds: float = Field(default=0.2, alias="RATE_LIMIT_DELAY_SECONDS")

    # Retries and exponential backoff
    max_retries: int = Field(default=5, alias="MAX_RETRIES")
    backoff_factor: float = Field(default=1.5, alias="BACKOFF_FACTOR")

    # Storage and persistence
    database_url: str = Field(
        default="sqlite+aiosqlite:///data/crawler_data.db",
        alias="DATABASE_URL",
    )

    # Volume targets
    target_records_per_type: int = Field(default=1000, alias="TARGET_RECORDS_PER_TYPE")

    # External APIs
    github_token: str = Field(default="", alias="GITHUB_TOKEN")

    # Logging
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_format: str = Field(default="json", alias="LOG_FORMAT")

    # Browser automation
    enable_playwright: bool = Field(default=False, alias="ENABLE_PLAYWRIGHT")

    # Storage directories
    base_dir: Path = Field(default_factory=lambda: Path(__file__).resolve().parent.parent)
    data_dir: Path = Field(default_factory=lambda: Path(__file__).resolve().parent.parent / "data")
    export_dir: Path = Field(default_factory=lambda: Path(__file__).resolve().parent.parent / "exports")

    def ensure_directories(self) -> None:
        """Ensure runtime directories exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.export_dir.mkdir(parents=True, exist_ok=True)


# Global singleton settings instance
settings = Settings()
settings.ensure_directories()
