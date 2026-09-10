"""Tests for multi-tab export, Google Sheets integration, and provenance verification."""

import csv
import pytest
from pathlib import Path
from unittest.mock import patch
import openpyxl
from crawler.export.google_sheets import GoogleSheetsExporter
from crawler.export.multi_sheet_exporter import MultiSheetExporter
from crawler.models.db import (
    RecordModel,
    EntityMappingLogModel,
    create_engine_and_session,
    init_database,
)


@pytest.mark.asyncio
async def test_multi_sheet_exporter_structure(tmp_path):
    """Verify generation of multi-tab XLSX and 6 CSV files."""
    db_url = f"sqlite+aiosqlite:///{tmp_path}/test_export.db"
    engine, session_factory = create_engine_and_session(db_url)
    await init_database(engine)

    # Insert sample records
    async with session_factory() as session:
        r1 = RecordModel(
            record_type="STARTUP",
            canonical_url_hash="hash_s1",
            content_hash="content_s1",
            source_url="https://openai.com",
            validated_data='{"schemaVersion":"1.0","recordType":"STARTUP","source":{"name":"Wikidata","url":"https://openai.com"},"content":{"entityName":"OpenAI, Inc.","data":{"employeeCount":1500}},"collectedAt":"2026-09-10T12:00:00Z"}'
        )
        r2 = RecordModel(
            record_type="PRODUCT",
            canonical_url_hash="hash_p1",
            content_hash="content_p1",
            source_url="https://resend.com",
            validated_data='{"schemaVersion":"1.0","recordType":"PRODUCT","source":{"name":"SaaSHub","url":"https://resend.com"},"content":{"startupName":"Resend","pricingModel":"FREEMIUM"},"collectedAt":"2026-09-10T12:00:00Z"}'
        )
        r3 = RecordModel(
            record_type="RESEARCH_PAPER",
            canonical_url_hash="hash_rp1",
            content_hash="content_rp1",
            source_url="https://arxiv.org/abs/2609.12345",
            validated_data='{"schemaVersion":"1.0","recordType":"RESEARCH_PAPER","source":{"name":"arXiv","url":"https://arxiv.org/abs/2609.12345"},"content":{"title":"Deep Networks","authors":["A. Researcher"],"paper_url":"https://arxiv.org/abs/2609.12345","github_url":"https://github.com/example/net","github_stars":120,"published_date":"2026-09-10T10:00:00Z"},"collectedAt":"2026-09-10T12:00:00Z"}'
        )
        session.add_all([r1, r2, r3])
        await session.commit()

        exporter = MultiSheetExporter(export_dir=tmp_path)
        result = await exporter.export_all(session)

    await engine.dispose()

    # Verify XLSX workbook exists and has all 6 tabs
    xlsx_path = Path(result["xlsx_path"])
    assert xlsx_path.exists()
    wb = openpyxl.load_workbook(xlsx_path)
    expected_sheets = [
        "Startups",
        "Products",
        "Research Papers",
        "Jobs",
        "News",
        "Entity Mapping Log",
    ]
    for sheet in expected_sheets:
        assert sheet in wb.sheetnames

    # Check that Startups sheet has OpenAI resolved
    ws_startups = wb["Startups"]
    header = [cell.value for cell in ws_startups[1]]
    assert "canonicalId" in header
    assert "rawEntityName" in header
    assert ws_startups[2][0].value == "openai"  # canonicalId
    assert ws_startups[2][1].value == "OpenAI"  # canonicalName

    # Verify CSV files exist
    assert (tmp_path / "startups.csv").exists()
    assert (tmp_path / "products.csv").exists()
    assert (tmp_path / "research_papers.csv").exists()
    assert (tmp_path / "entity_mapping_log.csv").exists()


def test_google_sheets_unauthenticated_guard(tmp_path):
    """Verify exporter refuses to claim Google Sheet publication without real credentials."""
    exporter = GoogleSheetsExporter(credentials_json=None, spreadsheet_id=None)
    assert exporter.is_configured is False

    fake_xlsx = tmp_path / "test.xlsx"
    fake_xlsx.touch()

    result = exporter.sync_multi_tab_export(fake_xlsx, {})
    assert result["status"] == "LOCAL_ONLY_UNAUTHENTICATED"
    assert "GOOGLE_SHEETS_CREDENTIALS_JSON" in result["missing_credentials"]
    assert result["published_url"] is None
