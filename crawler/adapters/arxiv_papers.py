"""arXiv bulk acquisition adapter extracting peer-reviewed AI/ML research papers."""

import re
import xml.etree.ElementTree as ET
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from crawler.adapters.base import BaseAdapter
from crawler.adapters.github_stars import github_extractor
from crawler.checkpoint import checkpoint_manager
from crawler.logging import logger
from crawler.models.schemas import (
    PaperContent,
    RecordType,
    ResearchPaperRecord,
    SourceModel,
)
from crawler.queue import CrawlTask

ATOM_NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
GITHUB_URL_REGEX = re.compile(r"https?://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", re.I)


class ArxivPapersAdapter(BaseAdapter):
    """Adapter acquiring AI/ML research papers from the official arXiv Bulk API."""

    name = "arxiv_papers"
    record_type = RecordType.RESEARCH_PAPER

    def __init__(self, batch_size: int = 100):
        self.batch_size = batch_size
        self.categories = "cat:cs.AI+OR+cat:cs.LG+OR+cat:cs.CV+OR+cat:cs.CL"

    async def discover(
        self, session: AsyncSession, limit: int = 1000
    ) -> AsyncGenerator[CrawlTask, None]:
        """Discovers paginated query batches from arXiv based on checkpoint."""
        offset, _, _ = await checkpoint_manager.get_checkpoint(session, self.name)
        total_queued = 0

        while total_queued < limit:
            batch_count = min(self.batch_size, limit - total_queued)
            url = (
                f"http://export.arxiv.org/api/query?"
                f"search_query={self.categories}&start={offset}&max_results={batch_count}"
                f"&sortBy=submittedDate&sortOrder=descending"
            )
            yield CrawlTask(
                url=url,
                adapter_name=self.name,
                record_type=self.record_type,
                metadata={"offset": offset, "batch_count": batch_count},
            )
            offset += batch_count
            total_queued += batch_count

    async def parse(
        self, response_text: str, task: CrawlTask
    ) -> AsyncGenerator[Tuple[ResearchPaperRecord, Dict[str, Any]], None]:
        """Parses arXiv Atom XML feed into validated ResearchPaperRecords."""
        try:
            root = ET.fromstring(response_text)
        except ET.ParseError as err:
            logger.error("Failed to parse arXiv XML: %s", err)
            return

        entries = root.findall("atom:entry", ATOM_NS)
        for entry in entries:
            try:
                title_elem = entry.find("atom:title", ATOM_NS)
                title = " ".join(title_elem.text.split()) if title_elem is not None and title_elem.text else ""
                if not title:
                    continue

                # Authors
                author_elems = entry.findall("atom:author", ATOM_NS)
                authors: List[str] = []
                for a in author_elems:
                    name_elem = a.find("atom:name", ATOM_NS)
                    if name_elem is not None and name_elem.text:
                        authors.append(name_elem.text.strip())

                # Canonical paper URL
                id_elem = entry.find("atom:id", ATOM_NS)
                paper_url = id_elem.text.strip() if id_elem is not None and id_elem.text else ""

                # Alternate link if available
                alt_link = entry.find("atom:link[@rel='alternate']", ATOM_NS)
                if alt_link is not None and alt_link.get("href"):
                    paper_url = alt_link.get("href")

                # Published date
                pub_elem = entry.find("atom:published", ATOM_NS)
                published_date = pub_elem.text.strip() if pub_elem is not None and pub_elem.text else ""

                # Extract potential GitHub links from summary/abstract and comments
                summary_elem = entry.find("atom:summary", ATOM_NS)
                comment_elem = entry.find("arxiv:comment", ATOM_NS)
                full_text = ""
                if summary_elem is not None and summary_elem.text:
                    full_text += summary_elem.text + " "
                if comment_elem is not None and comment_elem.text:
                    full_text += comment_elem.text

                github_url: Optional[str] = None
                m = GITHUB_URL_REGEX.search(full_text)
                if m:
                    clean_url = m.group(0).rstrip("/.,:;)")
                    if clean_url.endswith(".git"):
                        clean_url = clean_url[:-4]
                    github_url = clean_url

                # Live GitHub stars extraction
                github_stars = 0
                if github_url:
                    github_stars = await github_extractor.get_stars(github_url)

                record = ResearchPaperRecord(
                    schemaVersion="1.0",
                    recordType="RESEARCH_PAPER",
                    source=SourceModel(name="arXiv", url=paper_url),
                    content=PaperContent(
                        title=title,
                        authors=authors,
                        paper_url=paper_url,
                        github_url=github_url,
                        github_stars=github_stars,
                        published_date=published_date,
                    ),
                )

                raw_dict = {
                    "arxiv_id": paper_url,
                    "title": title,
                    "authors": authors,
                    "published": published_date,
                    "github_url": github_url,
                    "github_stars": github_stars,
                }

                yield record, raw_dict
            except Exception as item_err:
                logger.warning("Error parsing arXiv paper entry: %s", item_err)
