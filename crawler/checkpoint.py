"""Checkpoint and resume engine for fault-tolerant long-running crawls."""

from datetime import datetime, timezone
from typing import Optional, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from crawler.logging import logger
from crawler.models.db import CheckpointModel


class CheckpointManager:
    """Manages persistent pagination offsets and crawl state."""

    async def get_checkpoint(
        self, session: AsyncSession, adapter_name: str
    ) -> Tuple[int, Optional[str], int]:
        """Retrieves (offset_val, cursor_token, total_collected) for an adapter."""
        stmt = select(CheckpointModel).where(CheckpointModel.adapter_name == adapter_name)
        result = await session.execute(stmt)
        record = result.scalar_one_or_none()
        if record:
            return record.offset_val, record.cursor_token, record.total_collected
        return 0, None, 0

    async def update_checkpoint(
        self,
        session: AsyncSession,
        adapter_name: str,
        offset_val: int,
        cursor_token: Optional[str] = None,
        increment_collected: int = 0,
    ) -> None:
        """Persists updated state for an adapter."""
        stmt = select(CheckpointModel).where(CheckpointModel.adapter_name == adapter_name)
        result = await session.execute(stmt)
        record = result.scalar_one_or_none()
        if not record:
            record = CheckpointModel(
                adapter_name=adapter_name,
                offset_val=offset_val,
                cursor_token=cursor_token,
                total_collected=increment_collected,
            )
            session.add(record)
        else:
            record.offset_val = offset_val
            if cursor_token is not None:
                record.cursor_token = cursor_token
            record.total_collected += increment_collected
            record.updated_at = datetime.now(timezone.utc)

        await session.commit()
        logger.debug(
            "Updated checkpoint for %s: offset=%d, total=%d",
            adapter_name,
            record.offset_val,
            record.total_collected,
        )

    async def reset_checkpoint(self, session: AsyncSession, adapter_name: str) -> None:
        """Resets the checkpoint for an adapter."""
        stmt = select(CheckpointModel).where(CheckpointModel.adapter_name == adapter_name)
        result = await session.execute(stmt)
        record = result.scalar_one_or_none()
        if record:
            await session.delete(record)
            await session.commit()
            logger.info("Reset checkpoint for %s", adapter_name)


checkpoint_manager = CheckpointManager()
