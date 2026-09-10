"""SQLAlchemy database models and async engine configuration."""

import json
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, Optional
from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    TypeDecorator,
    event,
)


from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base
from crawler.config import settings

Base = declarative_base()


class RecordModel(Base):
    """Storage for all validated entity records."""

    __tablename__ = "records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    record_type = Column(String(32), nullable=False, index=True)
    canonical_url_hash = Column(String(64), nullable=False, index=True)
    content_hash = Column(String(64), nullable=False, unique=True, index=True)
    source_url = Column(Text, nullable=False)
    raw_payload = Column(Text, nullable=True)
    validated_data = Column(Text, nullable=False)
    collected_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        Index("idx_records_type_hash", "record_type", "content_hash"),
    )


class FrontierItemModel(Base):
    """Crawl frontier items tracking discovered URLs and lifecycle states."""

    __tablename__ = "crawl_frontier"

    url_hash = Column(String(64), primary_key=True)
    url = Column(Text, nullable=False)
    source_name = Column(String(64), nullable=False)
    record_type = Column(String(32), nullable=False, index=True)
    status = Column(String(32), default="PENDING", index=True)  # PENDING, RUNNING, DONE, FAILED
    retry_count = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class CheckpointModel(Base):
    """Persistent crawl state and pagination offsets per adapter."""

    __tablename__ = "checkpoints"

    adapter_name = Column(String(64), primary_key=True)
    offset_val = Column(Integer, default=0)
    cursor_token = Column(String(512), nullable=True)
    total_collected = Column(Integer, default=0)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class UTCDateTime(TypeDecorator):
    """DateTime type that forces UTC timezone on retrieval."""
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            else:
                value = value.astimezone(timezone.utc)
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            else:
                value = value.astimezone(timezone.utc)
        return value


# ==============================================================================
# PHASE II: SIGNAL INGESTION MODELS
# ==============================================================================

class NewsRecordModel(Base):
    """Storage for verified/fresh AI news articles."""

    __tablename__ = "news_records"

    id = Column(String(64), primary_key=True)
    source_id = Column(String(64), nullable=False, index=True)
    canonical_url = Column(Text, nullable=False)
    canonical_url_hash = Column(String(64), nullable=False, index=True)
    title = Column(Text, nullable=False)
    author = Column(Text, nullable=True)
    full_text = Column(Text, nullable=False)
    summary = Column(Text, nullable=True)
    published_at = Column(UTCDateTime, nullable=True, index=True)
    first_seen_at = Column(UTCDateTime, nullable=False)
    ingested_at = Column(UTCDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    date_extraction_method = Column(String(64), nullable=False, default="unknown")
    published_at_confidence = Column(Float, nullable=False, default=0.0)
    freshness_decision = Column(String(32), nullable=False, index=True)
    freshness_reason = Column(Text, nullable=False)
    content_hash = Column(String(64), nullable=False, unique=True, index=True)
    raw_metadata = Column(Text, nullable=True)

    __table_args__ = (
        Index("idx_news_source_url", "source_id", "canonical_url_hash"),
    )


class JobRecordModel(Base):
    """Storage for verified/fresh AI job listings."""

    __tablename__ = "job_records"

    id = Column(String(64), primary_key=True)
    source_id = Column(String(64), nullable=False, index=True)
    canonical_url = Column(Text, nullable=False)
    canonical_url_hash = Column(String(64), nullable=False, index=True)
    title = Column(Text, nullable=False)
    company = Column(Text, nullable=False)
    location = Column(Text, nullable=True)
    employment_type = Column(Text, nullable=True)
    salary = Column(Text, nullable=True)
    description_full_text = Column(Text, nullable=False)
    published_at = Column(UTCDateTime, nullable=True, index=True)
    first_seen_at = Column(UTCDateTime, nullable=False)
    ingested_at = Column(UTCDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    date_extraction_method = Column(String(64), nullable=False, default="unknown")
    published_at_confidence = Column(Float, nullable=False, default=0.0)
    freshness_decision = Column(String(32), nullable=False, index=True)
    freshness_reason = Column(Text, nullable=False)
    content_hash = Column(String(64), nullable=False, unique=True, index=True)
    raw_metadata = Column(Text, nullable=True)

    __table_args__ = (
        Index("idx_jobs_source_url", "source_id", "canonical_url_hash"),
    )


class SourceCrawlStateModel(Base):
    """Persistent crawl state and watermark boundary per signal source."""

    __tablename__ = "source_crawl_state"

    source_id = Column(String(64), primary_key=True)
    last_successful_crawl_at = Column(UTCDateTime, nullable=True)
    last_attempted_crawl_at = Column(UTCDateTime, nullable=True)
    last_boundary_item_id = Column(Text, nullable=True)
    observed_urls_snapshot = Column(Text, nullable=True)  # JSON list of seen URL hashes
    total_ingested = Column(Integer, default=0)
    updated_at = Column(
        UTCDateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class SourceRunHistoryModel(Base):
    """Observability and audit log for every signal ingestion run."""

    __tablename__ = "source_run_history"

    run_id = Column(String(64), primary_key=True)
    source_id = Column(String(64), nullable=False, index=True)
    status = Column(String(32), nullable=False)  # SUCCESS, PARTIAL, FAILED
    started_at = Column(UTCDateTime, nullable=False)
    completed_at = Column(UTCDateTime, nullable=False)
    candidates_discovered = Column(Integer, default=0)
    candidates_fetched = Column(Integer, default=0)
    accepted_count = Column(Integer, default=0)
    rejected_count = Column(Integer, default=0)
    error_count = Column(Integer, default=0)
    summary_json = Column(Text, nullable=True)


class EntityMappingLogModel(Base):
    """Storage for Entity Mapping Logs (Phase IV Deterministic Entity Resolution)."""

    __tablename__ = "entity_mapping_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_record_id = Column(String(128), nullable=False, index=True)
    raw_entity_name = Column(Text, nullable=False)
    normalized_entity_name = Column(Text, nullable=False)
    canonical_entity_id = Column(String(64), nullable=True, index=True)
    canonical_entity_name = Column(Text, nullable=True)
    match_strategy = Column(String(64), nullable=False, index=True)
    confidence = Column(Float, nullable=False, default=0.0)
    aliases_used = Column(Text, nullable=True)  # JSON list
    domains_used = Column(Text, nullable=True)  # JSON list
    resolver_version = Column(String(32), nullable=False, default="1.0.0")
    timestamp = Column(UTCDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    unresolved_reason = Column(Text, nullable=True)

    __table_args__ = (
        Index("idx_entity_res_strat", "match_strategy", "canonical_entity_id"),
    )


def create_engine_and_session(db_url: Optional[str] = None) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """Initializes async engine with WAL mode for SQLite and returns engine + session factory."""
    url = db_url or settings.database_url
    engine = create_async_engine(
        url,
        echo=False,
        future=True,
        pool_pre_ping=True,
    )

    # If using SQLite, configure WAL (Write-Ahead Logging) and high-concurrency PRAGMAs
    if "sqlite" in url:
        @event.listens_for(engine.sync_engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA synchronous=NORMAL;")
            cursor.execute("PRAGMA busy_timeout=30000;")
            cursor.execute("PRAGMA cache_size=-64000;")  # 64MB cache
            cursor.close()

    session_factory = async_sessionmaker(
        engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    return engine, session_factory


async def init_database(engine: AsyncEngine) -> None:
    """Creates database schema if tables do not exist."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
