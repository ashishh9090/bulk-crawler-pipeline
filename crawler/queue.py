"""Bounded asynchronous queue for producer-consumer pipeline decoupled from transport."""

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from crawler.models.schemas import RecordType


@dataclass
class CrawlTask:
    """Individual work item queued for worker processing."""

    url: str
    adapter_name: str
    record_type: RecordType
    depth: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    retry_count: int = 0


class BoundedAsyncQueue:
    """Bounded async queue preventing unbounded memory growth during high-volume discovery."""

    def __init__(self, maxsize: int = 5000):
        self._queue: asyncio.Queue[Optional[CrawlTask]] = asyncio.Queue(maxsize=maxsize)

    async def put(self, task: Optional[CrawlTask]) -> None:
        """Puts a task onto the queue, backpressuring if maxsize reached."""
        await self._queue.put(task)

    async def get(self) -> Optional[CrawlTask]:
        """Pops a task from the queue."""
        return await self._queue.get()

    def task_done(self) -> None:
        """Signals task completion for queue.join()."""
        self._queue.task_done()

    async def join(self) -> None:
        """Blocks until all items in the queue have been gotten and processed."""
        await self._queue.join()

    def qsize(self) -> int:
        return self._queue.qsize()

    def empty(self) -> bool:
        return self._queue.empty()
