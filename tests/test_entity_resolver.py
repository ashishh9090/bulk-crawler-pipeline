"""Comprehensive test suite for Phase IV Deterministic Entity Resolution."""

import pytest
from pathlib import Path
from crawler.entity_resolution.models import MatchStrategy
from crawler.entity_resolution.normalizer import normalize_domain, normalize_entity_name
from crawler.entity_resolution.resolver import DeterministicEntityResolver


@pytest.fixture
def resolver():
    return DeterministicEntityResolver()


def test_seed_database_count(resolver):
    """Verify seed database has at least 50 real AI startups."""
    assert resolver.total_entities >= 50


def test_normalization_rules():
    """Verify deterministic normalization of corporate suffixes, unicode, whitespace, and AI spacing."""
    assert normalize_entity_name("OpenAI, Inc.") == "openai"
    assert normalize_entity_name("Open AI") == "openai"
    assert normalize_entity_name("OpenAI LLC") == "openai"
    assert normalize_entity_name("OpenAI OpCo LLC") == "openai"
    assert normalize_entity_name("Cohere Inc.") == "cohere"
    assert normalize_entity_name("DeepL GmbH") == "deepl"
    assert normalize_entity_name("Synthesia Limited") == "synthesia"
    assert normalize_entity_name("Weaviate B.V.") == "weaviate"
    assert normalize_entity_name("Anthropic, PBC") == "anthropic"
    assert normalize_entity_name("Mistral AI SAS") == "mistral ai"
    assert normalize_entity_name("  Eleven   Labs   Inc.  ") == "elevenlabs"
    assert normalize_entity_name("W&B") == "weights and biases"


def test_domain_normalization():
    """Verify domain normalization strips protocols, paths, ports, and www."""
    assert normalize_domain("https://www.openai.com/research?id=123") == "openai.com"
    assert normalize_domain("HTTP://ANTHROPIC.COM:443/company") == "anthropic.com"
    assert normalize_domain("blog.weaviate.io/") == "blog.weaviate.io"
    assert normalize_domain("https://scale.com/about") == "scale.com"


def test_openai_naming_variants(resolver):
    """Verify all real-world variants of OpenAI resolve strictly to canonical OpenAI."""
    variants = [
        "OpenAI",
        "OpenAI, Inc.",
        "Open AI",
        "OpenAI Inc",
        "OpenAI LLC",
        "OpenAI OpCo LLC",
        "OPENAI",
        "openai",
    ]

    for variant in variants:
        result = resolver.resolve(variant, source_record_id="rec-openai-test")
        assert result.canonical_entity_id == "openai"
        assert result.canonical_entity_name == "OpenAI"
        assert result.confidence >= 0.98
        assert result.raw_entity_name == variant
        assert result.normalized_entity_name == "openai"
        assert result.resolver_version == "1.0.0"
        assert result.unresolved_reason is None


def test_safe_domain_matching(resolver):
    """Verify official domain matching resolves entities with 1.0 confidence."""
    # Even with an unhelpful raw name, official domain resolves accurately
    result = resolver.resolve(
        raw_name="Uninformative Title",
        source_record_id="rec-domain-test",
        domain="https://www.openai.com/careers",
    )
    assert result.canonical_entity_id == "openai"
    assert result.canonical_entity_name == "OpenAI"
    assert result.match_strategy == MatchStrategy.OFFICIAL_DOMAIN
    assert result.confidence == 1.0
    assert "openai.com" in result.domains_used


def test_corporate_suffixes_and_punctuation(resolver):
    """Verify diverse corporate legal suffixes resolve to their respective canonical entities."""
    test_cases = [
        ("Anthropic, PBC", "anthropic", "Anthropic"),
        ("Cohere Inc.", "cohere", "Cohere"),
        ("Mistral AI SAS", "mistral_ai", "Mistral AI"),
        ("Hugging Face, Inc.", "hugging_face", "Hugging Face"),
        ("Databricks, Inc.", "databricks", "Databricks"),
        ("DeepL SE", "deepl", "DeepL"),
        ("Weaviate B.V.", "weaviate", "Weaviate"),
        ("Synthesia Ltd", "synthesia", "Synthesia"),
    ]

    for raw, expected_id, expected_name in test_cases:
        result = resolver.resolve(raw, source_record_id="rec-suffix-test")
        assert result.canonical_entity_id == expected_id
        assert result.canonical_entity_name == expected_name
        assert result.confidence >= 0.98


def test_ambiguous_names_remain_unresolved(tmp_path):
    """Verify that ambiguous matches across multiple plausible entities are NEVER silently mapped."""
    # Create a fixture with deliberate collision
    custom_seed_file = tmp_path / "seed.json"
    import json
    seed_data = [
        {
            "canonical_id": "alpha_labs",
            "canonical_name": "Alpha Labs",
            "verified_aliases": ["Alpha", "Alpha Systems"],
            "normalized_aliases": ["alpha", "alpha systems"],
            "official_domains": ["alpha.ai"],
        },
        {
            "canonical_id": "alpha_ai",
            "canonical_name": "Alpha AI",
            "verified_aliases": ["Alpha", "Alpha Technologies"],
            "normalized_aliases": ["alpha", "alpha technologies"],
            "official_domains": ["alpha-ai.com"],
        },
    ]
    with open(custom_seed_file, "w") as f:
        json.dump(seed_data, f)

    ambig_resolver = DeterministicEntityResolver(seed_data_path=custom_seed_file)
    result = ambig_resolver.resolve("Alpha", source_record_id="ambig-1")

    assert result.canonical_entity_id is None
    assert result.canonical_entity_name is None
    assert result.match_strategy == MatchStrategy.AMBIGUOUS_MULTI_CANDIDATE
    assert result.confidence == 0.0
    assert "Ambiguous" in result.unresolved_reason
    assert "Alpha Labs" in result.unresolved_reason
    assert "Alpha AI" in result.unresolved_reason


def test_false_positive_prevention(resolver):
    """Verify generic AI stopwords alone do not trigger matches."""
    stopwords = ["AI", "Artificial Intelligence", "Labs", "Systems", "Technologies", "Data", "Cloud"]
    for word in stopwords:
        result = resolver.resolve(word, source_record_id="noise-test")
        assert result.canonical_entity_id is None
        assert result.confidence == 0.0
        assert result.match_strategy == MatchStrategy.UNRESOLVED


def test_deterministic_repeated_results(resolver):
    """Verify that resolving the exact same input 100 times returns identical results."""
    first = resolver.resolve("Anthropic, PBC", source_record_id="det-test-1")
    for _ in range(100):
        subsequent = resolver.resolve("Anthropic, PBC", source_record_id="det-test-1")
        assert subsequent.canonical_entity_id == first.canonical_entity_id
        assert subsequent.canonical_entity_name == first.canonical_entity_name
        assert subsequent.match_strategy == first.match_strategy
        assert subsequent.confidence == first.confidence
        assert subsequent.normalized_entity_name == first.normalized_entity_name
        assert subsequent.unresolved_reason == first.unresolved_reason
