"""Unit tests for source adapters parsing mock real-world XML/HTML/JSON payloads."""

import pytest
from crawler.adapters.arxiv_papers import ArxivPapersAdapter
from crawler.adapters.github_stars import github_extractor
from crawler.adapters.saashub_products import ProductsAdapter
from crawler.adapters.wikidata_startups import StartupsAdapter
from crawler.models.schemas import RecordType
from crawler.queue import CrawlTask


SAMPLE_ARXIV_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2303.12345v1</id>
    <published>2023-03-22T18:00:00Z</published>
    <title>Deep Residual Learning for Vision</title>
    <summary>We introduce a novel architecture. Code: https://github.com/microsoft/resnet</summary>
    <author><name>Kaiming He</name></author>
    <author><name>Xiangyu Zhang</name></author>
    <link rel="alternate" href="https://arxiv.org/abs/2303.12345" type="text/html"/>
  </entry>
</feed>
"""

SAMPLE_WIKIDATA_JSON = """{
  "results": {
    "bindings": [
      {
        "item": {"value": "http://www.wikidata.org/entity/Q95"},
        "itemLabel": {"value": "Google LLC"},
        "website": {"value": "https://about.google/"},
        "employees": {"value": "182502"}
      },
      {
        "item": {"value": "http://www.wikidata.org/entity/Q100"},
        "itemLabel": {"value": "Stealth Innovators"},
        "website": {"value": "https://stealth.ai/"}
      }
    ]
  }
}
"""

SAMPLE_SAASHUB_HTML = """<!DOCTYPE html>
<html>
<body>
  <div>
    <h3><a href="/p/resend">Resend</a></h3>
    <div>
      <a href="https://resend.com">Visit website</a>
      <span class="tag is-price-freemium">freemium</span>
    </div>
  </div>
  <div>
    <h3><a href="/p/supabase">Supabase</a></h3>
    <div>
      <a href="https://supabase.com">Visit website</a>
      <span class="tag is-price-free">Open Source</span>
    </div>
  </div>
</body>
</html>
"""


@pytest.mark.asyncio
async def test_arxiv_adapter_parser(monkeypatch):
    # Mock github star lookup to return 5000 stars
    async def mock_get_stars(url: str) -> int:
        return 5000

    monkeypatch.setattr(github_extractor, "get_stars", mock_get_stars)

    adapter = ArxivPapersAdapter()
    task = CrawlTask(
        url="http://export.arxiv.org/api/query",
        adapter_name="arxiv_papers",
        record_type=RecordType.RESEARCH_PAPER,
    )

    records = [rec async for rec, _ in adapter.parse(SAMPLE_ARXIV_XML, task)]
    assert len(records) == 1
    paper = records[0]
    assert paper.recordType == "RESEARCH_PAPER"
    assert paper.content.title == "Deep Residual Learning for Vision"
    assert paper.content.authors == ["Kaiming He", "Xiangyu Zhang"]
    assert paper.content.github_url == "https://github.com/microsoft/resnet"
    assert paper.content.github_stars == 5000
    assert paper.source.name == "arXiv"


@pytest.mark.asyncio
async def test_wikidata_startups_parser():
    adapter = StartupsAdapter()
    task = CrawlTask(
        url="https://query.wikidata.org/sparql",
        adapter_name="startups",
        record_type=RecordType.STARTUP,
        metadata={"source_flavor": "wikidata"},
    )

    records = [rec async for rec, _ in adapter.parse(SAMPLE_WIKIDATA_JSON, task)]
    assert len(records) == 2

    # First has employee count
    assert records[0].content.entityName == "Google LLC"
    assert records[0].content.data.employeeCount == 182502
    assert records[0].source.url == "https://about.google/"

    # Second has null employee count
    assert records[1].content.entityName == "Stealth Innovators"
    assert records[1].content.data.employeeCount is None


@pytest.mark.asyncio
async def test_saashub_products_parser():
    adapter = ProductsAdapter()
    task = CrawlTask(
        url="https://www.saashub.com/developer-tools",
        adapter_name="products",
        record_type=RecordType.PRODUCT,
    )

    records = [rec async for rec, _ in adapter.parse(SAMPLE_SAASHUB_HTML, task)]
    assert len(records) == 2

    r1 = records[0]
    assert r1.content.startupName == "Resend"
    assert r1.content.pricingModel == "FREEMIUM"
    assert r1.source.url == "https://resend.com/"

    r2 = records[1]
    assert r2.content.startupName == "Supabase"
    assert r2.content.pricingModel == "FREE"
    assert r2.source.url == "https://supabase.com/"


def test_github_slug_parser():
    assert github_extractor.parse_github_slug("https://github.com/pytorch/pytorch") == ("pytorch", "pytorch")
    assert github_extractor.parse_github_slug("https://github.com/torvalds/linux.git") == ("torvalds", "linux")
    assert github_extractor.parse_github_slug("https://github.com/topics/ai") is None
    assert github_extractor.parse_github_slug("invalid_url") is None
