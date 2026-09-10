"""Two-tier deduplication engine combining memory set with DB uniqueness constraints."""

import hashlib
import json
from collections import OrderedDict
from typing import Any, Dict, Optional, Set
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from crawler.logging import logger
from crawler.models.db import RecordModel
from crawler.models.schemas import (
    AnyCrawlRecord,
    ProductRecord,
    ResearchPaperRecord,
    StartupRecord,
)
from crawler.url_normalizer import hash_url, normalize_url


class DeduplicationEngine:
    """Manages URL and entity content deduplication in-memory and in persistent storage."""

    def __init__(self, max_memory_entries: int = 1_000_000):
        self._max_memory_entries = max_memory_entries
        self._seen_content_hashes: Set[str] = set()
        self._seen_url_hashes: Set[str] = set()

    def compute_content_hash(self, record: AnyCrawlRecord) -> str:
        """Computes a deterministic SHA-256 fingerprint for the semantic entity."""
        if isinstance(record, StartupRecord):
            key = f"STARTUP:{record.content.entityName.strip().lower()}:{normalize_url(record.source.url)}"
        elif isinstance(record, ProductRecord):
            key = f"PRODUCT:{record.content.startupName.strip().lower()}:{record.content.pricingModel}:{normalize_url(record.source.url)}"
        elif isinstance(record, ResearchPaperRecord):
            # Papers deduplicated by title and canonical paper URL
            key = f"PAPER:{record.content.title.strip().lower()}:{normalize_url(record.content.paper_url)}"
        else:
            raise ValueError(f"Unknown record type: {type(record)}")

        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    def is_content_seen_memory(self, content_hash: str) -> bool:
        """Fast O(1) in-memory check."""
        return content_hash in self._seen_content_hashes

    def mark_content_seen_memory(self, content_hash: str) -> None:
        """Records hash into memory set, trimming if capacity exceeded."""
        if len(self._seen_content_hashes) >= self._max_memory_entries:
            # Pop roughly 10% oldest to maintain bounded memory
            self._seen_content_hashes.clear()
        self._seen_content_hashes.add(content_hash)

    def is_url_seen_memory(self, url_hash: str) -> bool:
        return url_hash in self._seen_url_hashes

    def mark_url_seen_memory(self, url_hash: str) -> None:
        if len(self._seen_url_hashes) >= self._max_memory_entries:
            self._seen_url_hashes.clear()
        self._seen_url_hashes.add(url_hash)

    async def check_and_save_record(
        self,
        session: AsyncSession,
        record: AnyCrawlRecord,
        raw_payload: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Atomically saves record to DB if unique. Returns True if inserted, False if duplicate."""
        content_hash = self.compute_content_hash(record)
        canonical_url = normalize_url(record.source.url)
        url_hash = hash_url(canonical_url)

        # Quick memory check
        if self.is_content_seen_memory(content_hash):
            return False

        # Persistent DB check
        stmt = select(RecordModel.id).where(RecordModel.content_hash == content_hash)
        existing = await session.execute(stmt)
        if existing.scalar_one_or_none() is not None:
            self.mark_content_seen_memory(content_hash)
            return False

        # Attempt insert with concurrency safety
        db_record = RecordModel(
            record_type=record.recordType,
            canonical_url_hash=url_hash,
            content_hash=content_hash,
            source_url=record.source.url,
            raw_payload=json.dumps(raw_payload, default=str) if raw_payload else None,
            validated_data=json.dumps(record.model_dump(), default=str),
        )

        try:
            session.add(db_record)
            await session.commit()
            self.mark_content_seen_memory(content_hash)
            self.mark_url_seen_memory(url_hash)
            return True
        except IntegrityError:
            await session.rollback()
            self.mark_content_seen_memory(content_hash)
            return False
        except Exception as e:
            await session.rollback()
            logger.error("Failed to commit record to DB: %s", e)
            raise


deduplicator = DeduplicationEngine()
