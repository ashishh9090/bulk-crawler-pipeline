"""Base adapter interface for Phase II signal sources."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, Optional, Tuple, Union
import aiohttp
from crawler.http_client import HttpClient
from crawler.models.db import SourceCrawlStateModel
from crawler.signals.config import SourceConfig
from crawler.signals.freshness_gate import FreshnessEvaluation, FreshnessGate
from crawler.signals.models import CandidateItem, JobRecord, NewsRecord

AnySignalRecord = Union[NewsRecord, JobRecord]


class BaseSignalAdapter(ABC):
    """Abstract interface for all signal ingestion adapters."""

    def __init__(self, config: SourceConfig):
        self.config = config

    @abstractmethod
    async def discover_candidates(
        self,
        session: aiohttp.ClientSession,
        client: HttpClient,
        limit: int = 50,
    ) -> AsyncGenerator[CandidateItem, None]:
        """Discovers candidate items from feeds, APIs, or listing pages."""
        pass

    @abstractmethod
    async def extract_record(
        self,
        candidate: CandidateItem,
        session: aiohttp.ClientSession,
        client: HttpClient,
        freshness_gate: FreshnessGate,
        crawl_state: Optional[SourceCrawlStateModel] = None,
    ) -> Tuple[Optional[AnySignalRecord], FreshnessEvaluation]:
        """Fetches detail page (if needed), extracts text, evaluates freshness, and builds record."""
        pass
