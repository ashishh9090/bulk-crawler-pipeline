"""Multi-tab Excel (XLSX) and CSV exporter for the 6 required intelligence-ingestion datasets."""

import csv
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from crawler.config import settings
from crawler.entity_resolution.models import MatchStrategy
from crawler.entity_resolution.resolver import DeterministicEntityResolver
from crawler.logging import logger
from crawler.models.db import (
    EntityMappingLogModel,
    JobRecordModel,
    NewsRecordModel,
    RecordModel,
)


class MultiSheetExporter:
    """Exports all 6 required datasets into a multi-tab .xlsx workbook and individual CSV files."""

    def __init__(
        self,
        export_dir: Optional[Path] = None,
        seed_path: Optional[Path] = None,
    ):
        self.export_dir = export_dir or settings.export_dir
        self.export_dir.mkdir(parents=True, exist_ok=True)
        self.resolver = DeterministicEntityResolver(seed_data_path=seed_path)

    async def ensure_entity_mappings_populated(self, session: AsyncSession) -> int:
        """Resolves startups and products against the deterministic resolver and persists mapping logs."""
        # Check existing count
        count_stmt = select(EntityMappingLogModel)
        existing = await session.execute(count_stmt)
        if len(existing.scalars().all()) >= 50:
            return 0

        # Query all STARTUP and PRODUCT records
        stmt = select(RecordModel).where(
            RecordModel.record_type.in_(["STARTUP", "PRODUCT"])
        )
        records_result = await session.execute(stmt)
        records = records_result.scalars().all()

        added_count = 0
        for rec in records:
            data = json.loads(rec.validated_data)
            content = data.get("content", {})
            source = data.get("source", {})
            source_url = source.get("url", rec.source_url)

            raw_name = content.get("entityName") if rec.record_type == "STARTUP" else content.get("startupName")
            if not raw_name:
                continue

            res = self.resolver.resolve(
                raw_name=raw_name,
                source_record_id=f"{rec.record_type}:{rec.id}",
                domain=source_url,
            )

            log_entry = EntityMappingLogModel(
                source_record_id=res.source_record_id,
                raw_entity_name=res.raw_entity_name,
                normalized_entity_name=res.normalized_entity_name,
                canonical_entity_id=res.canonical_entity_id,
                canonical_entity_name=res.canonical_entity_name,
                match_strategy=res.match_strategy.value,
                confidence=res.confidence,
                aliases_used=json.dumps(res.aliases_used),
                domains_used=json.dumps(res.domains_used),
                resolver_version=res.resolver_version,
                unresolved_reason=res.unresolved_reason,
            )
            session.add(log_entry)
            added_count += 1

        if added_count > 0:
            await session.commit()
            logger.info("Populated %d entity mapping logs in database", added_count)
        return added_count

    async def fetch_dataset(self, session: AsyncSession, tab_name: str) -> List[Dict[str, Any]]:
        """Fetches rows for a specific tab from database."""
        rows: List[Dict[str, Any]] = []

        if tab_name == "Startups":
            stmt = select(RecordModel).where(RecordModel.record_type == "STARTUP").order_by(RecordModel.id.asc())
            result = await session.execute(stmt)
            for rec in result.scalars().all():
                d = json.loads(rec.validated_data)
                content = d.get("content", {})
                source = d.get("source", {})
                raw_name = content.get("entityName", "")
                source_url = source.get("url", rec.source_url)

                res = self.resolver.resolve(raw_name, source_record_id=str(rec.id), domain=source_url)
                rows.append({
                    "canonicalId": res.canonical_entity_id or "",
                    "canonicalName": res.canonical_entity_name or "",
                    "rawEntityName": raw_name,
                    "employeeCount": content.get("data", {}).get("employeeCount", ""),
                    "sourceName": source.get("name", ""),
                    "sourceUrl": source_url,
                    "collectedAt": d.get("collectedAt", str(rec.collected_at)),
                    "matchStrategy": res.match_strategy.value,
                    "confidence": res.confidence,
                })

        elif tab_name == "Products":
            stmt = select(RecordModel).where(RecordModel.record_type == "PRODUCT").order_by(RecordModel.id.asc())
            result = await session.execute(stmt)
            for rec in result.scalars().all():
                d = json.loads(rec.validated_data)
                content = d.get("content", {})
                source = d.get("source", {})
                raw_name = content.get("startupName", "")
                source_url = source.get("url", rec.source_url)

                res = self.resolver.resolve(raw_name, source_record_id=str(rec.id), domain=source_url)
                rows.append({
                    "startupName": raw_name,
                    "canonicalStartupId": res.canonical_entity_id or "",
                    "canonicalStartupName": res.canonical_entity_name or "",
                    "pricingModel": content.get("pricingModel", ""),
                    "sourceName": source.get("name", ""),
                    "sourceUrl": source_url,
                    "collectedAt": d.get("collectedAt", str(rec.collected_at)),
                    "matchStrategy": res.match_strategy.value,
                    "confidence": res.confidence,
                })

        elif tab_name == "Research Papers":
            stmt = select(RecordModel).where(RecordModel.record_type == "RESEARCH_PAPER").order_by(RecordModel.id.asc())
            result = await session.execute(stmt)
            for rec in result.scalars().all():
                d = json.loads(rec.validated_data)
                content = d.get("content", {})
                source = d.get("source", {})
                authors = content.get("authors", [])
                collected_at = d.get("collectedAt", str(rec.collected_at))
                rows.append({
                    "title": content.get("title", ""),
                    "authors": "; ".join(authors) if isinstance(authors, list) else str(authors),
                    "paper_url": content.get("paper_url", ""),
                    "github_url": content.get("github_url") or "",
                    "github_stars": content.get("github_stars", ""),
                    "github_stars_retrieved_at": collected_at if content.get("github_stars") is not None else "",
                    "published_date": content.get("published_date", ""),
                    "sourceName": source.get("name", ""),
                    "collectedAt": collected_at,
                })

        elif tab_name == "Jobs":
            stmt = select(JobRecordModel).order_by(JobRecordModel.ingested_at.desc())
            result = await session.execute(stmt)
            for j in result.scalars().all():
                rows.append({
                    "id": j.id,
                    "company": j.company,
                    "title": j.title,
                    "location": j.location or "",
                    "employmentType": j.employment_type or "",
                    "salary": j.salary or "",
                    "publishedAt": str(j.published_at) if j.published_at else "",
                    "freshnessDecision": j.freshness_decision,
                    "sourceId": j.source_id,
                    "canonicalUrl": j.canonical_url,
                    "collectedAt": str(j.ingested_at),
                })

        elif tab_name == "News":
            stmt = select(NewsRecordModel).order_by(NewsRecordModel.ingested_at.desc())
            result = await session.execute(stmt)
            for n in result.scalars().all():
                rows.append({
                    "id": n.id,
                    "title": n.title,
                    "author": n.author or "",
                    "publishedAt": str(n.published_at) if n.published_at else "",
                    "freshnessDecision": n.freshness_decision,
                    "sourceId": n.source_id,
                    "canonicalUrl": n.canonical_url,
                    "summary": (n.summary or n.full_text[:200]).replace("\n", " "),
                    "collectedAt": str(n.ingested_at),
                })

        elif tab_name == "Entity Mapping Log":
            stmt = select(EntityMappingLogModel).order_by(EntityMappingLogModel.id.asc())
            result = await session.execute(stmt)
            for el in result.scalars().all():
                rows.append({
                    "sourceRecordId": el.source_record_id,
                    "rawEntityName": el.raw_entity_name,
                    "normalizedEntityName": el.normalized_entity_name,
                    "canonicalEntityId": el.canonical_entity_id or "",
                    "canonicalEntityName": el.canonical_entity_name or "",
                    "matchStrategy": el.match_strategy,
                    "confidence": el.confidence,
                    "aliasesUsed": el.aliases_used or "[]",
                    "domainsUsed": el.domains_used or "[]",
                    "resolverVersion": el.resolver_version,
                    "timestamp": str(el.timestamp),
                    "unresolvedReason": el.unresolved_reason or "",
                })

        return rows

    async def export_all(self, session: AsyncSession) -> Dict[str, Any]:
        """Generates multi-tab XLSX and 6 CSV files."""
        await self.ensure_entity_mappings_populated(session)

        tabs = [
            "Startups",
            "Products",
            "Research Papers",
            "Jobs",
            "News",
            "Entity Mapping Log",
        ]

        wb = openpyxl.Workbook()
        # Remove default sheet
        wb.remove(wb.active)

        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")

        csv_paths: Dict[str, Path] = {}
        counts: Dict[str, int] = {}

        for tab in tabs:
            data = await self.fetch_dataset(session, tab)
            counts[tab] = len(data)

            # Create XLSX Sheet
            ws = wb.create_sheet(title=tab)
            if data:
                headers = list(data[0].keys())
                ws.append(headers)

                for cell in ws[1]:
                    cell.font = header_font
                    cell.fill = header_fill
                    cell.alignment = Alignment(horizontal="center", vertical="center")

                for row_dict in data:
                    ws.append([row_dict.get(h, "") for h in headers])

                # Auto-fit columns
                for col in ws.columns:
                    max_len = max(len(str(cell.value or "")) for cell in col)
                    col_letter = openpyxl.utils.get_column_letter(col[0].column)
                    ws.column_dimensions[col_letter].width = min(max(max_len + 2, 12), 60)
            else:
                ws.append(["No records collected within the last 24 hours for this category."])

            # Also create corresponding CSV file
            csv_filename = tab.lower().replace(" ", "_") + ".csv"
            csv_path = self.export_dir / csv_filename
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                if data:
                    writer = csv.DictWriter(f, fieldnames=list(data[0].keys()))
                    writer.writeheader()
                    writer.writerows(data)
                else:
                    f.write("status\nNo records collected within window\n")
            csv_paths[tab] = csv_path

        xlsx_path = self.export_dir / "intelligence_ingestion_export.xlsx"
        wb.save(xlsx_path)
        logger.info("Saved multi-tab XLSX workbook to %s", xlsx_path)

        return {
            "xlsx_path": xlsx_path,
            "csv_paths": csv_paths,
            "counts": counts,
        }
