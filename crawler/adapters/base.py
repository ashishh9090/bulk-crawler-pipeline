"""Base adapter contract for source-specific crawlers and parsers."""

from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Dict, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from crawler.models.schemas import AnyCrawlRecord, RecordType
from crawler.queue import CrawlTask


class BaseAdapter(ABC):
    """Abstract base class that every source adapter must implement."""

    name: str
    record_type: RecordType

    @abstractmethod
    async def discover(
        self, session: AsyncSession, limit: int = 1000
    ) -> AsyncGenerator[CrawlTask, None]:
        """Discovers URLs or paginated work items and yields CrawlTasks."""
        ...

    @abstractmethod
    async def parse(
        self, response_text: str, task: CrawlTask
    ) -> AsyncGenerator[Tuple[AnyCrawlRecord, Dict[str, Any]], None]:
        """Parses response text into validated schema records and raw dictionaries."""
        ...
