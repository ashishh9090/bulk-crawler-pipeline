"""Tests for strict schema validation and field-level provenance audit structures."""

import pytest
from pydantic import ValidationError
from crawler.models.schemas import (
    StartupRecord,
    ProductRecord,
    ResearchPaperRecord,
    JobEntityRecord,
    FieldProvenance,
    RecordAuditProvenance,
    SourceModel,
    StartupContent,
    StartupData,
    ProductContent,
    PaperContent,
    JobEntityContent,
)


def test_startup_schema_validation():
    """Verify StartupEntity schema structure with strict validation."""
    record = StartupRecord(
        schemaVersion="1.0",
        recordType="STARTUP",
        source=SourceModel(name="Wikidata", url="https://about.google/"),
        content=StartupContent(
            entityName="Google",
            data=StartupData(employeeCount=187000)
        ),
        collectedAt="2026-09-10T04:39:50.773910+00:00"
    )
    assert record.recordType == "STARTUP"
    assert record.content.entityName == "Google"
    assert record.content.data.employeeCount == 187000

    # Unverified employee count defaults to None / null
    record_none = StartupRecord(
        source=SourceModel(name="Wikidata", url="https://about.google/"),
        content=StartupContent(entityName="Stealth Startup", data=StartupData())
    )
    assert record_none.content.data.employeeCount is None


def test_product_schema_validation():
    """Verify ProductEntity schema and pricingModel enum."""
    record = ProductRecord(
        schemaVersion="1.0",
        recordType="PRODUCT",
        source=SourceModel(name="SaaSHub", url="https://resend.com/"),
        content=ProductContent(startupName="Resend", pricingModel="FREEMIUM"),
        collectedAt="2026-09-10T04:39:32.596702+00:00"
    )
    assert record.recordType == "PRODUCT"
    assert record.content.pricingModel == "FREEMIUM"

    # Invalid pricing model raises ValidationError
    with pytest.raises(ValidationError):
        ProductRecord(
            source=SourceModel(name="SaaSHub", url="https://example.com/"),
            content=ProductContent(startupName="Example", pricingModel="UNKNOWN_MODEL")
        )


def test_research_paper_schema_validation():
    """Verify ResearchPaperEntity schema and github_stars/github_url handling."""
    record = ResearchPaperRecord(
        schemaVersion="1.0",
        recordType="RESEARCH_PAPER",
        content=PaperContent(
            title="Programmable World Model",
            authors=["Zheng-Hui Huang", "Guixu Lin"],
            paper_url="https://arxiv.org/abs/2609.10540v1",
            github_url="https://github.com/AlayaLab/pwm.git",
            github_stars=56,
            published_date="2026-09-09T17:59:32Z"
        )
    )
    assert record.recordType == "RESEARCH_PAPER"
    assert record.content.github_stars == 56
    # URL normalizer stripped .git
    assert record.content.github_url == "https://github.com/AlayaLab/pwm"

    # github_stars can be None if not fetched
    record_no_stars = ResearchPaperRecord(
        content=PaperContent(
            title="Theoretical Bounds",
            authors=["Alice Researcher"],
            paper_url="https://arxiv.org/abs/2609.99999v1",
            github_stars=None,
            published_date="2026-09-09T17:59:32Z"
        )
    )
    assert record_no_stars.content.github_stars is None


def test_job_entity_schema_validation():
    """Verify JobEntity schema structure."""
    job = JobEntityRecord(
        schemaVersion="1.0",
        recordType="JOB",
        content=JobEntityContent(
            company="Anthropic",
            date="2026-09-10T12:00:00Z",
            is_remote=True,
            role_family="Research"
        )
    )
    assert job.recordType == "JOB"
    assert job.content.company == "Anthropic"
    assert job.content.is_remote is True
    assert job.content.role_family == "Research"


def test_field_provenance_audit_structure():
    """Verify field-level provenance records and audit container."""
    field_prov = FieldProvenance(
        source_url="https://openai.com/careers/researcher",
        source_field_or_selector="meta[property='og:title']",
        confidence=0.98,
        is_direct_source_data=True
    )
    assert field_prov.source_url == "https://openai.com/careers/researcher"
    assert field_prov.confidence == 0.98
    assert field_prov.is_direct_source_data is True

    audit = RecordAuditProvenance(
        record_id="rec-audit-123",
        record_type="JOB",
        source_url="https://openai.com/careers/researcher",
        fields={"title": field_prov}
    )
    assert audit.record_id == "rec-audit-123"
    assert "title" in audit.fields
    assert audit.fields["title"].is_direct_source_data is True
