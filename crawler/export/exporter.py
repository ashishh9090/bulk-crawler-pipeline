"""Streaming data exporter for JSON, JSONL, and CSV formats."""

import csv
import json
from pathlib import Path
from typing import Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from crawler.config import settings
from crawler.logging import logger
from crawler.models.db import RecordModel
from crawler.models.schemas import RecordType


class DataExporter:
    """Streams records from database into disk files in bounded memory batches."""

    def __init__(self, export_dir: Optional[Path] = None, batch_size: int = 1000):
        self.export_dir = export_dir or settings.export_dir
        self.export_dir.mkdir(parents=True, exist_ok=True)
        self.batch_size = batch_size

    def _flatten_for_csv(self, record_type: str, data: Dict) -> Dict:
        """Flattens nested JSON object into a tabular row."""
        row = {
            "schemaVersion": data.get("schemaVersion", "1.0"),
            "recordType": data.get("recordType", record_type),
            "source_name": data.get("source", {}).get("name", ""),
            "source_url": data.get("source", {}).get("url", ""),
            "collectedAt": data.get("collectedAt", ""),
        }
        content = data.get("content", {})
        if record_type == "STARTUP":
            row["entityName"] = content.get("entityName", "")
            emp = content.get("data", {}).get("employeeCount")
            row["employeeCount"] = emp if emp is not None else ""
        elif record_type == "PRODUCT":
            row["startupName"] = content.get("startupName", "")
            row["pricingModel"] = content.get("pricingModel", "")
        elif record_type == "RESEARCH_PAPER":
            row["title"] = content.get("title", "")
            authors = content.get("authors", [])
            row["authors"] = "; ".join(authors) if isinstance(authors, list) else str(authors)
            row["paper_url"] = content.get("paper_url", "")
            row["github_url"] = content.get("github_url") or ""
            row["github_stars"] = content.get("github_stars", 0)
            row["published_date"] = content.get("published_date", "")

        return row

    async def export_records(
        self,
        session: AsyncSession,
        record_type: Optional[RecordType] = None,
        export_format: str = "json",
    ) -> Dict[str, Path]:
        """Streams records of specified type or all types to disk files."""
        types_to_export = [record_type.value] if record_type else [t.value for t in RecordType]
        results: Dict[str, Path] = {}

        for rtype in types_to_export:
            stmt = (
                select(RecordModel)
                .where(RecordModel.record_type == rtype)
                .order_by(RecordModel.id.asc())
            )
            result = await session.stream(stmt)

            file_stem = rtype.lower()
            exported_count = 0

            if export_format in ("json", "all"):
                json_path = self.export_dir / f"{file_stem}.json"
                with open(json_path, "w", encoding="utf-8") as f:
                    f.write("[\n")
                    first = True
                    async for row in result.yield_per(self.batch_size):
                        record: RecordModel = row[0]
                        data_obj = json.loads(record.validated_data)
                        if not first:
                            f.write(",\n")
                        f.write("  " + json.dumps(data_obj, indent=2).replace("\n", "\n  "))
                        first = False
                        exported_count += 1
                    f.write("\n]\n")
                results[f"{rtype}_json"] = json_path
                logger.info("Exported %d %s records to %s", exported_count, rtype, json_path)

            if export_format in ("jsonl", "all"):
                # Re-query for stream
                result = await session.stream(stmt)
                jsonl_path = self.export_dir / f"{file_stem}.jsonl"
                with open(jsonl_path, "w", encoding="utf-8") as f:
                    async for row in result.yield_per(self.batch_size):
                        record = row[0]
                        f.write(record.validated_data.strip() + "\n")
                results[f"{rtype}_jsonl"] = jsonl_path

            if export_format in ("csv", "all"):
                result = await session.stream(stmt)
                csv_path = self.export_dir / f"{file_stem}.csv"
                first_row = True
                writer = None
                with open(csv_path, "w", newline="", encoding="utf-8") as f:
                    async for row in result.yield_per(self.batch_size):
                        record = row[0]
                        flat = self._flatten_for_csv(rtype, json.loads(record.validated_data))
                        if first_row:
                            writer = csv.DictWriter(f, fieldnames=list(flat.keys()))
                            writer.writeheader()
                            first_row = False
                        if writer:
                            writer.writerow(flat)
                results[f"{rtype}_csv"] = csv_path
                logger.info("Exported %s records to CSV: %s", rtype, csv_path)

        return results
