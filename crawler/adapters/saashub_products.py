"""Products acquisition adapter extracting software products and verified pricing models."""

import re
from typing import Any, AsyncGenerator, Dict, List, Tuple
from bs4 import BeautifulSoup
from sqlalchemy.ext.asyncio import AsyncSession
from crawler.adapters.base import BaseAdapter
from crawler.checkpoint import checkpoint_manager
from crawler.logging import logger
from crawler.models.schemas import (
    PricingModel,
    ProductContent,
    ProductRecord,
    RecordType,
    SourceModel,
)
from crawler.queue import CrawlTask
from crawler.url_normalizer import normalize_url

CATEGORIES = [
    "developer-tools",
    "ai-tools",
    "business-software",
    "marketing-software",
    "collaboration-software",
    "design-software",
    "finance-software",
    "security-software",
    "customer-support-software",
    "analytics-software",
    "e-commerce-software",
    "human-resources-software",
    "project-management-software",
    "cloud-storage-software",
    "database-software",
]


class ProductsAdapter(BaseAdapter):
    """Adapter discovering software products and extracting verified pricing models."""

    name = "products"
    record_type = RecordType.PRODUCT

    def __init__(self, pages_per_category: int = 15):
        self.pages_per_category = pages_per_category

    async def discover(
        self, session: AsyncSession, limit: int = 1000
    ) -> AsyncGenerator[CrawlTask, None]:
        """Discovers category page URLs from SaaSHub and verified developer tools catalogs."""
        offset, _, _ = await checkpoint_manager.get_checkpoint(session, self.name)
        total_queued = 0

        # 1. SaaSHub software categories (Freemium, Paid, Enterprise, Free)
        for category in CATEGORIES:
            for page in range(1, self.pages_per_category + 1):
                if total_queued >= limit:
                    break

                page_url = f"https://www.saashub.com/{category}?page={page}"
                yield CrawlTask(
                    url=page_url,
                    adapter_name=self.name,
                    record_type=self.record_type,
                    metadata={"source_flavor": "saashub", "category": category, "page": page},
                )
                total_queued += 25

        # 2. Complementary Open Source Developer Products Catalog (GitHub API topic)
        for gh_page in range(1, 15):
            gh_url = f"https://api.github.com/search/repositories?q=topic:developer-tools+stars:>100&per_page=100&page={gh_page}"
            yield CrawlTask(
                url=gh_url,
                adapter_name=self.name,
                record_type=self.record_type,
                metadata={"source_flavor": "github_tools", "page": gh_page},
            )

    async def parse(
        self, response_text: str, task: CrawlTask
    ) -> AsyncGenerator[Tuple[ProductRecord, Dict[str, Any]], None]:
        """Parses HTML or JSON response into validated ProductRecords."""
        source_flavor = task.metadata.get("source_flavor", "saashub")
        if source_flavor == "github_tools":
            async for rec, raw in self._parse_github_tools(response_text, task):
                yield rec, raw
            return

        soup = BeautifulSoup(response_text, "html.parser")

        # Find service cards or product blocks
        # SaaSHub displays each product in div elements with headers and tags
        headers = soup.find_all(["h3", "h4"])
        for h in headers:
            try:
                title_link = h.find("a")
                if not title_link:
                    continue

                raw_name = title_link.get_text(strip=True)
                # Strip promotional/verification badge prefixes
                product_name = re.sub(
                    r"^(Officially verified details|Verified|Featured|Promoted)\s*",
                    "",
                    raw_name,
                    flags=re.I,
                ).strip()

                saashub_href = title_link.get("href", "")
                if not product_name or not saashub_href or "/compare/" in saashub_href:
                    continue

                canonical_source_url = normalize_url(saashub_href, base_url="https://www.saashub.com")

                # Look in parent container for external website link and pricing tags
                container = h.find_parent("div")
                if container is None:
                    continue

                # Check for direct website link
                website_link = container.find("a", href=re.compile(r"^https?://(?!www\.saashub\.com|cdn)"))
                if website_link and website_link.get("href"):
                    canonical_source_url = normalize_url(website_link["href"])

                # Determine pricing model
                # Check for badges like <span class="tag is-price-freemium">
                pricing_model: PricingModel = "FREE"
                container_text = container.get_text(" ", strip=True).lower()

                price_tag = container.find("span", class_=re.compile(r"is-price-(\w+)"))
                if price_tag:
                    raw_tag = price_tag.get_text(strip=True).upper()
                    if "FREEMIUM" in raw_tag or "FREE TRIAL" in raw_tag:
                        pricing_model = "FREEMIUM"
                    elif "FREE" in raw_tag or "OPEN SOURCE" in raw_tag:
                        pricing_model = "FREE"
                    elif "ENTERPRISE" in raw_tag:
                        pricing_model = "ENTERPRISE"
                    elif "PAID" in raw_tag or "COMMERCIAL" in raw_tag:
                        pricing_model = "PAID"
                else:
                    # Heuristic inspection of container text
                    if "freemium" in container_text or "free trial" in container_text:
                        pricing_model = "FREEMIUM"
                    elif "open source" in container_text or " free " in container_text:
                        pricing_model = "FREE"
                    elif "enterprise" in container_text:
                        pricing_model = "ENTERPRISE"
                    elif "paid" in container_text or "$" in container_text or "pricing" in container_text:
                        pricing_model = "PAID"

                record = ProductRecord(
                    schemaVersion="1.0",
                    recordType="PRODUCT",
                    source=SourceModel(name="SaaSHub", url=canonical_source_url),
                    content=ProductContent(
                        startupName=product_name,
                        pricingModel=pricing_model,
                    ),
                )

                raw_dict = {
                    "product_name": product_name,
                    "saashub_url": saashub_href,
                    "source_url": canonical_source_url,
                    "pricing_model": pricing_model,
                    "category": task.metadata.get("category"),
                }

                yield record, raw_dict
            except Exception as item_err:
                logger.warning("Error parsing product card: %s", item_err)

    async def _parse_github_tools(
        self, response_text: str, task: CrawlTask
    ) -> AsyncGenerator[Tuple[ProductRecord, Dict[str, Any]], None]:
        import json
        try:
            data = json.loads(response_text)
            items = data.get("items", [])
        except Exception as err:
            logger.error("Failed to parse GitHub tools JSON: %s", err)
            return

        for repo in items:
            try:
                name = repo.get("name", "").strip()
                owner = repo.get("owner", {}).get("login", "").strip()
                html_url = repo.get("html_url", "")
                homepage = repo.get("homepage", "")
                source_url = homepage if homepage and homepage.startswith("http") else html_url
                if not name or not source_url:
                    continue

                canonical_url = normalize_url(source_url)
                display_name = f"{owner}/{name}" if owner else name

                record = ProductRecord(
                    schemaVersion="1.0",
                    recordType="PRODUCT",
                    source=SourceModel(name="GitHub Developer Tools", url=canonical_url),
                    content=ProductContent(
                        startupName=display_name,
                        pricingModel="FREE",
                    ),
                )

                raw_dict = {
                    "product_name": name,
                    "owner": owner,
                    "html_url": html_url,
                    "stars": repo.get("stargazers_count", 0),
                    "pricing_model": "FREE",
                }
                yield record, raw_dict
            except Exception as item_err:
                logger.warning("Error parsing GitHub tool item: %s", item_err)
