"""Unit tests verifying Pydantic v2 schemas and validation constraints."""

import pytest
from pydantic import ValidationError
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


def test_startup_schema_valid():
    record = StartupRecord(
        source=SourceModel(name="Wikidata", url="https://stripe.com"),
        content=StartupContent(
            entityName="Stripe",
            data=StartupData(employeeCount=8000),
        ),
    )
    dump = record.model_dump()
    assert dump["schemaVersion"] == "1.0"
    assert dump["recordType"] == "STARTUP"
    assert dump["content"]["entityName"] == "Stripe"
    assert dump["content"]["data"]["employeeCount"] == 8000
    assert "collectedAt" in dump


def test_startup_schema_null_employee_count():
    record = StartupRecord(
        source=SourceModel(name="Wikidata", url="https://stealthstartup.io"),
        content=StartupContent(
            entityName="Stealth AI",
            data=StartupData(employeeCount=None),
        ),
    )
    assert record.content.data.employeeCount is None


def test_product_schema_pricing_model_normalization():
    p1 = ProductRecord(
        source=SourceModel(name="SaaSHub", url="https://product.io"),
        content=ProductContent(startupName="Tool A", pricingModel="Free"),
    )
    assert p1.content.pricingModel == "FREE"

    p2 = ProductRecord(
        source=SourceModel(name="SaaSHub", url="https://product.io"),
        content=ProductContent(startupName="Tool B", pricingModel="freemium"),
    )
    assert p2.content.pricingModel == "FREEMIUM"

    p3 = ProductRecord(
        source=SourceModel(name="SaaSHub", url="https://product.io"),
        content=ProductContent(startupName="Tool C", pricingModel="Paid"),
    )
    assert p3.content.pricingModel == "PAID"

    p4 = ProductRecord(
        source=SourceModel(name="SaaSHub", url="https://product.io"),
        content=ProductContent(startupName="Tool D", pricingModel="ENTERPRISE"),
    )
    assert p4.content.pricingModel == "ENTERPRISE"


def test_product_schema_invalid_pricing_model():
    with pytest.raises(ValidationError):
        ProductRecord(
            source=SourceModel(name="SaaSHub", url="https://product.io"),
            content=ProductContent(startupName="Tool E", pricingModel="UNKNOWN_MODEL"),
        )


def test_research_paper_schema_valid():
    record = ResearchPaperRecord(
        source=SourceModel(name="arXiv", url="http://arxiv.org/abs/2301.00001"),
        content=PaperContent(
            title="Attention Is All You Need",
            authors=["Ashish Vaswani", "Noam Shazeer"],
            paper_url="http://arxiv.org/abs/1706.03762",
            github_url="https://github.com/tensorflow/tensor2tensor",
            github_stars=13500,
            published_date="2017-06-12T00:00:00Z",
        ),
    )
    dump = record.model_dump()
    assert dump["schemaVersion"] == "1.0"
    assert dump["recordType"] == "RESEARCH_PAPER"
    assert dump["content"]["title"] == "Attention Is All You Need"
    assert dump["content"]["github_stars"] == 13500
    assert len(dump["content"]["authors"]) == 2


def test_research_paper_github_url_cleaning():
    p = PaperContent(
        title="Test",
        authors=["Author"],
        paper_url="http://arxiv.org/abs/1",
        github_url="https://github.com/pytorch/pytorch.git/",
        github_stars=80000,
        published_date="2020-01-01",
    )
    assert p.github_url == "https://github.com/pytorch/pytorch"
