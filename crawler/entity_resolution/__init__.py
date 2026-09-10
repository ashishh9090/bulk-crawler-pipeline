"""Phase IV Deterministic Entity Resolution package."""

from crawler.entity_resolution.models import (
    EntityResolutionResult,
    EntitySeedRecord,
    MatchStrategy,
)
from crawler.entity_resolution.normalizer import (
    normalize_domain,
    normalize_entity_name,
)
from crawler.entity_resolution.resolver import DeterministicEntityResolver

__all__ = [
    "DeterministicEntityResolver",
    "EntityResolutionResult",
    "EntitySeedRecord",
    "MatchStrategy",
    "normalize_domain",
    "normalize_entity_name",
]
