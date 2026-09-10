"""Startups acquisition adapter extracting verified enterprise and startup records."""

import json
import urllib.parse
from typing import Any, AsyncGenerator, Dict, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from crawler.adapters.base import BaseAdapter
from crawler.checkpoint import checkpoint_manager
from crawler.logging import logger
from crawler.models.schemas import (
    RecordType,
    SourceModel,
    StartupContent,
    StartupData,
    StartupRecord,
)
from crawler.queue import CrawlTask


class StartupsAdapter(BaseAdapter):
    """Adapter collecting verified startup records from corporate enterprise registries."""

    name = "startups"
    record_type = RecordType.STARTUP

    def __init__(self, batch_size: int = 100):
        self.batch_size = batch_size

    async def discover(
        self, session: AsyncSession, limit: int = 1000
    ) -> AsyncGenerator[CrawlTask, None]:
        """Discovers batch tasks using Wikidata SPARQL endpoint and HN startups."""
        offset, _, _ = await checkpoint_manager.get_checkpoint(session, self.name)
        total_queued = 0

        # 1. Wikidata Corporate Registry Query
        while total_queued < limit:
            batch_count = min(self.batch_size, limit - total_queued)

            sparql_query = f"""
            SELECT ?item ?itemLabel ?website ?employees WHERE {{
              ?item wdt:P31 wd:Q4830453 .
              ?item wdt:P856 ?website .
              OPTIONAL {{ ?item wdt:P1128 ?employees . }}
              SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
            }} LIMIT {batch_count} OFFSET {offset}
            """
            wikidata_url = (
                f"https://query.wikidata.org/sparql?query="
                f"{urllib.parse.quote(sparql_query)}&format=json"
            )

            yield CrawlTask(
                url=wikidata_url,
                adapter_name=self.name,
                record_type=self.record_type,
                metadata={"source_flavor": "wikidata", "offset": offset, "batch_count": batch_count},
            )

            offset += batch_count
            total_queued += batch_count

        # 2. Complementary SEC EDGAR high-volume verified company directory (10,407 verified entities)
        sec_url = "https://www.sec.gov/files/company_tickers.json"
        yield CrawlTask(
            url=sec_url,
            adapter_name=self.name,
            record_type=self.record_type,
            metadata={"source_flavor": "sec_edgar", "batch_count": limit},
        )

    async def parse(
        self, response_text: str, task: CrawlTask
    ) -> AsyncGenerator[Tuple[StartupRecord, Dict[str, Any]], None]:
        """Parses response into validated StartupRecord entities."""
        source_flavor = task.metadata.get("source_flavor", "wikidata")

        if source_flavor == "wikidata":
            async for rec, raw in self._parse_wikidata(response_text, task):
                yield rec, raw
        elif source_flavor == "sec_edgar":
            async for rec, raw in self._parse_sec_edgar(response_text, task):
                yield rec, raw

    async def _parse_sec_edgar(
        self, response_text: str, task: CrawlTask
    ) -> AsyncGenerator[Tuple[StartupRecord, Dict[str, Any]], None]:
        try:
            data = json.loads(response_text)
        except Exception as err:
            logger.error("Failed to parse SEC EDGAR JSON: %s", err)
            return

        # data is a dict of index -> {cik_str, ticker, title}
        count = 0
        limit = task.metadata.get("batch_count", 1000)
        for _, company in data.items():
            if count >= limit:
                break
            try:
                name = company.get("title", "").strip().title()
                cik = str(company.get("cik_str", "")).zfill(10)
                ticker = company.get("ticker", "").strip()
                if not name:
                    continue

                official_sec_url = f"https://www.sec.gov/edgar/browse/?CIK={cik}"

                record = StartupRecord(
                    schemaVersion="1.0",
                    recordType="STARTUP",
                    source=SourceModel(name="SEC EDGAR", url=official_sec_url),
                    content=StartupContent(
                        entityName=name,
                        data=StartupData(employeeCount=None),
                    ),
                )

                raw_dict = {
                    "entity_name": name,
                    "ticker": ticker,
                    "cik": cik,
                    "sec_url": official_sec_url,
                }
                yield record, raw_dict
                count += 1
            except Exception as item_err:
                logger.warning("Error parsing SEC company: %s", item_err)

    async def _parse_wikidata(
        self, response_text: str, task: CrawlTask
    ) -> AsyncGenerator[Tuple[StartupRecord, Dict[str, Any]], None]:
        try:
            data = json.loads(response_text)
            bindings = data.get("results", {}).get("bindings", [])
        except Exception as err:
            logger.error("Failed to parse Wikidata JSON response: %s", err)
            return

        for item in bindings:
            try:
                name = item.get("itemLabel", {}).get("value", "").strip()
                website = item.get("website", {}).get("value", "").strip()
                item_uri = item.get("item", {}).get("value", "").strip()

                # Ignore entities missing a name or having generic Q-identifiers as name
                if not name or name.startswith("Q") and name[1:].isdigit():
                    continue

                source_url = website if website and website.startswith("http") else item_uri
                if not source_url:
                    continue

                raw_emp = item.get("employees", {}).get("value")
                employee_count: Optional[int] = None
                if raw_emp is not None:
                    try:
                        employee_count = int(float(raw_emp))
                    except (ValueError, TypeError):
                        employee_count = None

                record = StartupRecord(
                    schemaVersion="1.0",
                    recordType="STARTUP",
                    source=SourceModel(name="Wikidata", url=source_url),
                    content=StartupContent(
                        entityName=name,
                        data=StartupData(employeeCount=employee_count),
                    ),
                )

                raw_dict = {
                    "wikidata_uri": item_uri,
                    "entity_name": name,
                    "website": website,
                    "employee_count": employee_count,
                }

                yield record, raw_dict
            except Exception as item_err:
                logger.warning("Error parsing startup record: %s", item_err)
