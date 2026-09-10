"""SQLAlchemy database models and async engine configuration."""

import json
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, Optional
from sqlalchemy import (
    Column,
    DateTime,
    Index,
    Integer,
    String,
    Text,
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
