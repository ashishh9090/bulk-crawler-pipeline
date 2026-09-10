"""Deterministic Startup & Product Entity Resolution Engine."""

import json
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from crawler.entity_resolution.models import (
    EntityResolutionResult,
    EntitySeedRecord,
    MatchStrategy,
    current_iso_timestamp,
)
from crawler.entity_resolution.normalizer import (
    normalize_domain,
    normalize_entity_name,
)

RESOLVER_VERSION = "1.0.0"

# Stopwords / generic tokens that must NEVER trigger single-token matches
GENERIC_AI_STOPWORDS: Set[str] = {
    "ai", "artificial", "intelligence", "lab", "labs", "systems",
    "technologies", "technology", "software", "solutions", "robotics",
    "cloud", "data", "deep", "machine", "learning", "ml", "group", "holdings"
}


class DeterministicEntityResolver:
    """High-precision, multi-tier deterministic entity resolver for AI startups and products."""

    def __init__(self, seed_data_path: Optional[Path] = None):
        if seed_data_path is None:
            seed_data_path = Path(__file__).resolve().parent / "seed_data.json"
        self.seed_data_path = seed_data_path
        self._entities: Dict[str, EntitySeedRecord] = {}
        
        # Fast lookup indexes
        self._exact_canonical_index: Dict[str, str] = {}       # lower(name) -> canonical_id
        self._normalized_canonical_index: Dict[str, str] = {}  # normalize(name) -> canonical_id
        self._exact_alias_index: Dict[str, Set[str]] = {}      # lower(alias) -> Set[canonical_id]
        self._normalized_alias_index: Dict[str, Set[str]] = {} # normalize(alias) -> Set[canonical_id]
        self._domain_index: Dict[str, str] = {}                # normalized_domain -> canonical_id

        self._load_seed_data()

    def _load_seed_data(self) -> None:
        """Loads and precomputes deterministic indexes from seed data."""
        with open(self.seed_data_path, "r", encoding="utf-8") as f:
            raw_list = json.load(f)

        for item in raw_list:
            record = EntitySeedRecord(**item)
            cid = record.canonical_id
            self._entities[cid] = record

            # Canonical name indexing
            cname_lower = record.canonical_name.strip().lower()
            self._exact_canonical_index[cname_lower] = cid
            cname_norm = normalize_entity_name(record.canonical_name)
            if cname_norm:
                self._normalized_canonical_index[cname_norm] = cid

            # Aliases indexing
            for alias in record.verified_aliases:
                al_lower = alias.strip().lower()
                self._exact_alias_index.setdefault(al_lower, set()).add(cid)
                al_norm = normalize_entity_name(alias)
                if al_norm:
                    self._normalized_alias_index.setdefault(al_norm, set()).add(cid)

            for norm_al in record.normalized_aliases:
                norm_clean = normalize_entity_name(norm_al)
                if norm_clean:
                    self._normalized_alias_index.setdefault(norm_clean, set()).add(cid)

            # Domain indexing
            for domain in record.official_domains:
                clean_domain = normalize_domain(domain)
                if clean_domain:
                    self._domain_index[clean_domain] = cid

    @property
    def total_entities(self) -> int:
        return len(self._entities)

    def resolve(
        self,
        raw_name: str,
        source_record_id: str = "unknown",
        domain: Optional[str] = None,
    ) -> EntityResolutionResult:
        """Resolves an entity name (and optional domain) using strict prioritized deterministic tiers."""
        raw_name_clean = (raw_name or "").strip()
        normalized_name = normalize_entity_name(raw_name_clean)
        clean_domain = normalize_domain(domain) if domain else ""
        now_ts = current_iso_timestamp()

        # Handle empty/invalid input
        if not raw_name_clean and not clean_domain:
            return EntityResolutionResult(
                source_record_id=source_record_id,
                raw_entity_name=raw_name_clean,
                normalized_entity_name="",
                canonical_entity_id=None,
                canonical_entity_name=None,
                match_strategy=MatchStrategy.UNRESOLVED,
                confidence=0.0,
                resolver_version=RESOLVER_VERSION,
                timestamp=now_ts,
                unresolved_reason="EMPTY_INPUT",
            )

        # ----------------------------------------------------------------------
        # Tier 1: Exact Match on Official Domain (Highest structural signal)
        # ----------------------------------------------------------------------
        if clean_domain and clean_domain in self._domain_index:
            cid = self._domain_index[clean_domain]
            entity = self._entities[cid]
            return EntityResolutionResult(
                source_record_id=source_record_id,
                raw_entity_name=raw_name_clean,
                normalized_entity_name=normalized_name,
                canonical_entity_id=cid,
                canonical_entity_name=entity.canonical_name,
                match_strategy=MatchStrategy.OFFICIAL_DOMAIN,
                confidence=1.0,
                domains_used=[clean_domain],
                resolver_version=RESOLVER_VERSION,
                timestamp=now_ts,
            )

        # ----------------------------------------------------------------------
        # Tier 2: Exact Canonical Name Match (Case-Insensitive)
        # ----------------------------------------------------------------------
        raw_lower = raw_name_clean.lower()
        if raw_lower in self._exact_canonical_index:
            cid = self._exact_canonical_index[raw_lower]
            entity = self._entities[cid]
            return EntityResolutionResult(
                source_record_id=source_record_id,
                raw_entity_name=raw_name_clean,
                normalized_entity_name=normalized_name,
                canonical_entity_id=cid,
                canonical_entity_name=entity.canonical_name,
                match_strategy=MatchStrategy.EXACT_CANONICAL_NAME,
                confidence=1.0,
                aliases_used=[entity.canonical_name],
                resolver_version=RESOLVER_VERSION,
                timestamp=now_ts,
            )

        # ----------------------------------------------------------------------
        # Tier 3: Exact Configured Alias Match
        # ----------------------------------------------------------------------
        if raw_lower in self._exact_alias_index:
            matching_ids = list(self._exact_alias_index[raw_lower])
            if len(matching_ids) == 1:
                cid = matching_ids[0]
                entity = self._entities[cid]
                return EntityResolutionResult(
                    source_record_id=source_record_id,
                    raw_entity_name=raw_name_clean,
                    normalized_entity_name=normalized_name,
                    canonical_entity_id=cid,
                    canonical_entity_name=entity.canonical_name,
                    match_strategy=MatchStrategy.EXACT_CONFIGURED_ALIAS,
                    confidence=1.0,
                    aliases_used=[raw_name_clean],
                    resolver_version=RESOLVER_VERSION,
                    timestamp=now_ts,
                )
            elif len(matching_ids) > 1:
                # Ambiguous match! Never guess!
                cnames = [self._entities[i].canonical_name for i in matching_ids]
                return EntityResolutionResult(
                    source_record_id=source_record_id,
                    raw_entity_name=raw_name_clean,
                    normalized_entity_name=normalized_name,
                    canonical_entity_id=None,
                    canonical_entity_name=None,
                    match_strategy=MatchStrategy.AMBIGUOUS_MULTI_CANDIDATE,
                    confidence=0.0,
                    aliases_used=[raw_name_clean],
                    resolver_version=RESOLVER_VERSION,
                    timestamp=now_ts,
                    unresolved_reason=f"Ambiguous exact alias mapped to multiple entities: {cnames}",
                )

        # ----------------------------------------------------------------------
        # Tier 4: Exact Normalized Canonical Name Match
        # ----------------------------------------------------------------------
        if normalized_name in self._normalized_canonical_index:
            cid = self._normalized_canonical_index[normalized_name]
            entity = self._entities[cid]
            return EntityResolutionResult(
                source_record_id=source_record_id,
                raw_entity_name=raw_name_clean,
                normalized_entity_name=normalized_name,
                canonical_entity_id=cid,
                canonical_entity_name=entity.canonical_name,
                match_strategy=MatchStrategy.EXACT_CANONICAL_NAME,
                confidence=0.99,
                aliases_used=[entity.canonical_name],
                resolver_version=RESOLVER_VERSION,
                timestamp=now_ts,
            )

        # ----------------------------------------------------------------------
        # Tier 5: Exact Normalized Alias Match
        # ----------------------------------------------------------------------
        if normalized_name in self._normalized_alias_index:
            matching_ids = list(self._normalized_alias_index[normalized_name])
            if len(matching_ids) == 1:
                cid = matching_ids[0]
                entity = self._entities[cid]
                return EntityResolutionResult(
                    source_record_id=source_record_id,
                    raw_entity_name=raw_name_clean,
                    normalized_entity_name=normalized_name,
                    canonical_entity_id=cid,
                    canonical_entity_name=entity.canonical_name,
                    match_strategy=MatchStrategy.EXACT_NORMALIZED_ALIAS,
                    confidence=0.98,
                    aliases_used=[normalized_name],
                    resolver_version=RESOLVER_VERSION,
                    timestamp=now_ts,
                )
            elif len(matching_ids) > 1:
                cnames = [self._entities[i].canonical_name for i in matching_ids]
                return EntityResolutionResult(
                    source_record_id=source_record_id,
                    raw_entity_name=raw_name_clean,
                    normalized_entity_name=normalized_name,
                    canonical_entity_id=None,
                    canonical_entity_name=None,
                    match_strategy=MatchStrategy.AMBIGUOUS_MULTI_CANDIDATE,
                    confidence=0.0,
                    aliases_used=[normalized_name],
                    resolver_version=RESOLVER_VERSION,
                    timestamp=now_ts,
                    unresolved_reason=f"Ambiguous normalized alias mapped to multiple entities: {cnames}",
                )

        # ----------------------------------------------------------------------
        # Tier 6: Conservative Token Similarity (Safe Guardrails)
        # ----------------------------------------------------------------------
        # Rules for conservative token similarity:
        # 1. Input tokens must have at least 1 significant non-stopword token
        # 2. Match candidate ONLY if all significant tokens of the canonical entity are satisfied
        # 3. If multiple distinct canonical entities match, REJECT as ambiguous!
        # 4. Never match if the input token is purely generic (e.g. "AI", "Lab")
        tokens = set(normalized_name.split())
        significant_tokens = tokens - GENERIC_AI_STOPWORDS

        if len(significant_tokens) >= 1:
            candidate_matches: List[Tuple[str, float, str]] = []  # (cid, score, matched_alias)

            for cid, entity in self._entities.items():
                c_norm = normalize_entity_name(entity.canonical_name)
                c_tokens = set(c_norm.split())
                c_sig = c_tokens - GENERIC_AI_STOPWORDS

                # Exact significant tokens match between input and canonical
                if significant_tokens and significant_tokens == c_sig:
                    candidate_matches.append((cid, 0.90, entity.canonical_name))
                    continue

                # Check aliases
                for alias in entity.verified_aliases:
                    al_norm = normalize_entity_name(alias)
                    al_tokens = set(al_norm.split())
                    al_sig = al_tokens - GENERIC_AI_STOPWORDS
                    if significant_tokens and significant_tokens == al_sig:
                        candidate_matches.append((cid, 0.88, alias))
                        break

            # Deduplicate candidates by cid
            unique_candidates: Dict[str, Tuple[float, str]] = {}
            for cid, score, al in candidate_matches:
                if cid not in unique_candidates or score > unique_candidates[cid][0]:
                    unique_candidates[cid] = (score, al)

            if len(unique_candidates) == 1:
                cid, (score, matched_al) = list(unique_candidates.items())[0]
                entity = self._entities[cid]
                return EntityResolutionResult(
                    source_record_id=source_record_id,
                    raw_entity_name=raw_name_clean,
                    normalized_entity_name=normalized_name,
                    canonical_entity_id=cid,
                    canonical_entity_name=entity.canonical_name,
                    match_strategy=MatchStrategy.CONSERVATIVE_TOKEN_MATCH,
                    confidence=score,
                    aliases_used=[matched_al],
                    resolver_version=RESOLVER_VERSION,
                    timestamp=now_ts,
                )
            elif len(unique_candidates) > 1:
                cnames = [self._entities[i].canonical_name for i in unique_candidates.keys()]
                return EntityResolutionResult(
                    source_record_id=source_record_id,
                    raw_entity_name=raw_name_clean,
                    normalized_entity_name=normalized_name,
                    canonical_entity_id=None,
                    canonical_entity_name=None,
                    match_strategy=MatchStrategy.AMBIGUOUS_MULTI_CANDIDATE,
                    confidence=0.0,
                    resolver_version=RESOLVER_VERSION,
                    timestamp=now_ts,
                    unresolved_reason=f"Ambiguous token match candidates: {cnames}",
                )

        # ----------------------------------------------------------------------
        # Fallthrough: Unresolved
        # ----------------------------------------------------------------------
        return EntityResolutionResult(
            source_record_id=source_record_id,
            raw_entity_name=raw_name_clean,
            normalized_entity_name=normalized_name,
            canonical_entity_id=None,
            canonical_entity_name=None,
            match_strategy=MatchStrategy.UNRESOLVED,
            confidence=0.0,
            resolver_version=RESOLVER_VERSION,
            timestamp=now_ts,
            unresolved_reason="NO_MATCHING_ENTITY_FOUND",
        )
