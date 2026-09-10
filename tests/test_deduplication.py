"""Unit tests for deduplication engine across memory and database layers."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from crawler.deduplication import DeduplicationEngine
from crawler.models.schemas import (
    PaperContent,
    ProductContent,
    ProductRecord,
    ResearchPaperRecord,
    SourceModel,
    StartupContent,
    StartupData,
    StartupRecord,
)


@pytest.mark.asyncio
async def test_content_hash_differentiation():
    engine = DeduplicationEngine()

    s1 = StartupRecord(
        source=SourceModel(name="Test", url="https://example.com/company1"),
        content=StartupContent(entityName="Acme Corp", data=StartupData(employeeCount=50)),
    )
    s2 = StartupRecord(
        source=SourceModel(name="Test", url="https://example.com/company2"),
        content=StartupContent(entityName="Beta Labs", data=StartupData(employeeCount=10)),
    )
    s3_dup = StartupRecord(
        source=SourceModel(name="Test", url="https://example.com/company1"),
        content=StartupContent(entityName="Acme Corp", data=StartupData(employeeCount=999)),
    )

    h1 = engine.compute_content_hash(s1)
    h2 = engine.compute_content_hash(s2)
    h3 = engine.compute_content_hash(s3_dup)

    assert h1 != h2
    assert h1 == h3  # Deduplicates semantic entity irrespective of minor mutable changes


@pytest.mark.asyncio
async def test_database_deduplication_atomicity(test_session: AsyncSession):
    engine = DeduplicationEngine()

    record = ProductRecord(
        source=SourceModel(name="SaaSHub", url="https://example.com/app"),
        content=ProductContent(startupName="SuperTool", pricingModel="FREEMIUM"),
    )

    # First save should succeed
    saved_first = await engine.check_and_save_record(test_session, record)
    assert saved_first is True

    # Immediate duplicate save should be detected and return False
    saved_second = await engine.check_and_save_record(test_session, record)
    assert saved_second is False

    # New engine instance (memory cleared) should still detect duplicate via DB
    fresh_engine = DeduplicationEngine()
    saved_third = await fresh_engine.check_and_save_record(test_session, record)
    assert saved_third is False
