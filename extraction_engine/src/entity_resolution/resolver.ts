/**
 * Deterministic entity resolver in TypeScript.
 */

import { normalizeDomain, normalizeEntityName } from './normalizer.js';
import type { EntityResolutionResult, EntitySeedRecord } from './types.js';
import seedData from './seed_data.json' with { type: 'json' };

export const RESOLVER_VERSION = '1.0.0';

const GENERIC_AI_STOPWORDS = new Set([
  'ai', 'artificial', 'intelligence', 'lab', 'labs', 'systems',
  'technologies', 'technology', 'software', 'solutions', 'robotics',
  'cloud', 'data', 'deep', 'machine', 'learning', 'ml', 'group', 'holdings'
]);

export class DeterministicEntityResolver {
  private entities: Map<string, EntitySeedRecord> = new Map();
  private exactCanonicalIndex: Map<string, string> = new Map();
  private normalizedCanonicalIndex: Map<string, string> = new Map();
  private exactAliasIndex: Map<string, Set<string>> = new Map();
  private normalizedAliasIndex: Map<string, Set<string>> = new Map();
  private domainIndex: Map<string, string> = new Map();

  constructor(customSeed?: EntitySeedRecord[]) {
    const list = customSeed || (seedData as unknown as EntitySeedRecord[]);
    this.loadSeed(list);
  }

  private loadSeed(seedList: EntitySeedRecord[]) {
    for (const record of seedList) {
      const cid = record.canonical_id;
      this.entities.set(cid, record);

      const cnameLower = record.canonical_name.trim().toLowerCase();
      this.exactCanonicalIndex.set(cnameLower, cid);
      const cnameNorm = normalizeEntityName(record.canonical_name);
      if (cnameNorm) {
        this.normalizedCanonicalIndex.set(cnameNorm, cid);
      }

      for (const alias of record.verified_aliases || []) {
        const alLower = alias.trim().toLowerCase();
        if (!this.exactAliasIndex.has(alLower)) {
          this.exactAliasIndex.set(alLower, new Set());
        }
        this.exactAliasIndex.get(alLower)!.add(cid);

        const alNorm = normalizeEntityName(alias);
        if (alNorm) {
          if (!this.normalizedAliasIndex.has(alNorm)) {
            this.normalizedAliasIndex.set(alNorm, new Set());
          }
          this.normalizedAliasIndex.get(alNorm)!.add(cid);
        }
      }

      for (const domain of record.official_domains || []) {
        const cleanDomain = normalizeDomain(domain);
        if (cleanDomain) {
          this.domainIndex.set(cleanDomain, cid);
        }
      }
    }
  }

  public resolve(
    rawName: string,
    sourceRecordId: string = 'unknown',
    domain?: string | null
  ): EntityResolutionResult {
    const rawNameClean = (rawName || '').trim();
    const normalizedName = normalizeEntityName(rawNameClean);
    const cleanDomain = domain ? normalizeDomain(domain) : '';
    const nowTs = new Date().toISOString();

    if (!rawNameClean && !cleanDomain) {
      return {
        source_record_id: sourceRecordId,
        raw_entity_name: rawNameClean,
        normalized_entity_name: '',
        canonical_entity_id: null,
        canonical_entity_name: null,
        match_strategy: 'UNRESOLVED',
        confidence: 0.0,
        aliases_used: [],
        domains_used: [],
        resolver_version: RESOLVER_VERSION,
        timestamp: nowTs,
        unresolved_reason: 'EMPTY_INPUT',
      };
    }

    // Tier 1: Official Domain Match
    if (cleanDomain && this.domainIndex.has(cleanDomain)) {
      const cid = this.domainIndex.get(cleanDomain)!;
      const entity = this.entities.get(cid)!;
      return {
        source_record_id: sourceRecordId,
        raw_entity_name: rawNameClean,
        normalized_entity_name: normalizedName,
        canonical_entity_id: cid,
        canonical_entity_name: entity.canonical_name,
        match_strategy: 'OFFICIAL_DOMAIN',
        confidence: 1.0,
        aliases_used: [],
        domains_used: [cleanDomain],
        resolver_version: RESOLVER_VERSION,
        timestamp: nowTs,
      };
    }

    // Tier 2: Exact Canonical Name Match
    const rawLower = rawNameClean.toLowerCase();
    if (this.exactCanonicalIndex.has(rawLower)) {
      const cid = this.exactCanonicalIndex.get(rawLower)!;
      const entity = this.entities.get(cid)!;
      return {
        source_record_id: sourceRecordId,
        raw_entity_name: rawNameClean,
        normalized_entity_name: normalizedName,
        canonical_entity_id: cid,
        canonical_entity_name: entity.canonical_name,
        match_strategy: 'EXACT_CANONICAL_NAME',
        confidence: 1.0,
        aliases_used: [entity.canonical_name],
        domains_used: [],
        resolver_version: RESOLVER_VERSION,
        timestamp: nowTs,
      };
    }

    // Tier 3: Exact Configured Alias Match
    if (this.exactAliasIndex.has(rawLower)) {
      const matchingIds = Array.from(this.exactAliasIndex.get(rawLower)!);
      if (matchingIds.length === 1) {
        const cid = matchingIds[0];
        if (cid && this.entities.has(cid)) {
          const entity = this.entities.get(cid)!;
          return {
            source_record_id: sourceRecordId,
            raw_entity_name: rawNameClean,
            normalized_entity_name: normalizedName,
            canonical_entity_id: cid,
            canonical_entity_name: entity.canonical_name,
            match_strategy: 'EXACT_CONFIGURED_ALIAS',
            confidence: 1.0,
            aliases_used: [rawNameClean],
            domains_used: [],
            resolver_version: RESOLVER_VERSION,
            timestamp: nowTs,
          };
        }
      }
      if (matchingIds.length > 1) {
        const cnames = matchingIds.map((id) => this.entities.get(id)?.canonical_name || id);
        return {
          source_record_id: sourceRecordId,
          raw_entity_name: rawNameClean,
          normalized_entity_name: normalizedName,
          canonical_entity_id: null,
          canonical_entity_name: null,
          match_strategy: 'AMBIGUOUS_MULTI_CANDIDATE',
          confidence: 0.0,
          aliases_used: [rawNameClean],
          domains_used: [],
          resolver_version: RESOLVER_VERSION,
          timestamp: nowTs,
          unresolved_reason: `Ambiguous exact alias mapped to multiple entities: ${JSON.stringify(cnames)}`,
        };
      }
    }

    // Tier 4: Exact Normalized Canonical Name Match
    if (this.normalizedCanonicalIndex.has(normalizedName)) {
      const cid = this.normalizedCanonicalIndex.get(normalizedName)!;
      const entity = this.entities.get(cid)!;
      return {
        source_record_id: sourceRecordId,
        raw_entity_name: rawNameClean,
        normalized_entity_name: normalizedName,
        canonical_entity_id: cid,
        canonical_entity_name: entity.canonical_name,
        match_strategy: 'EXACT_CANONICAL_NAME',
        confidence: 0.99,
        aliases_used: [entity.canonical_name],
        domains_used: [],
        resolver_version: RESOLVER_VERSION,
        timestamp: nowTs,
      };
    }

    // Tier 5: Exact Normalized Alias Match
    if (this.normalizedAliasIndex.has(normalizedName)) {
      const matchingIds = Array.from(this.normalizedAliasIndex.get(normalizedName)!);
      if (matchingIds.length === 1) {
        const cid = matchingIds[0];
        if (cid && this.entities.has(cid)) {
          const entity = this.entities.get(cid)!;
          return {
            source_record_id: sourceRecordId,
            raw_entity_name: rawNameClean,
            normalized_entity_name: normalizedName,
            canonical_entity_id: cid,
            canonical_entity_name: entity.canonical_name,
            match_strategy: 'EXACT_NORMALIZED_ALIAS',
            confidence: 0.98,
            aliases_used: [normalizedName],
            domains_used: [],
            resolver_version: RESOLVER_VERSION,
            timestamp: nowTs,
          };
        }
      }
      if (matchingIds.length > 1) {
        const cnames = matchingIds.map((id) => this.entities.get(id)?.canonical_name || id);
        return {
          source_record_id: sourceRecordId,
          raw_entity_name: rawNameClean,
          normalized_entity_name: normalizedName,
          canonical_entity_id: null,
          canonical_entity_name: null,
          match_strategy: 'AMBIGUOUS_MULTI_CANDIDATE',
          confidence: 0.0,
          aliases_used: [normalizedName],
          domains_used: [],
          resolver_version: RESOLVER_VERSION,
          timestamp: nowTs,
          unresolved_reason: `Ambiguous normalized alias mapped to multiple entities: ${JSON.stringify(cnames)}`,
        };
      }
    }

    // Tier 6: Conservative Token Similarity
    const tokens = new Set(normalizedName.split(' ').filter(Boolean));
    const significantTokens = Array.from(tokens).filter((t) => !GENERIC_AI_STOPWORDS.has(t));

    if (significantTokens.length >= 1) {
      const candidateMatches: Array<{ cid: string; score: number; alias: string }> = [];

      for (const [cid, entity] of this.entities.entries()) {
        const cNorm = normalizeEntityName(entity.canonical_name);
        const cTokens = new Set(cNorm.split(' ').filter(Boolean));
        const cSig = Array.from(cTokens).filter((t) => !GENERIC_AI_STOPWORDS.has(t));

        if (
          significantTokens.length === cSig.length &&
          significantTokens.every((t) => cTokens.has(t))
        ) {
          candidateMatches.push({ cid, score: 0.9, alias: entity.canonical_name });
          continue;
        }

        for (const alias of entity.verified_aliases) {
          const alNorm = normalizeEntityName(alias);
          const alTokens = new Set(alNorm.split(' ').filter(Boolean));
          const alSig = Array.from(alTokens).filter((t) => !GENERIC_AI_STOPWORDS.has(t));

          if (
            significantTokens.length === alSig.length &&
            significantTokens.every((t) => alTokens.has(t))
          ) {
            candidateMatches.push({ cid, score: 0.88, alias });
            break;
          }
        }
      }

      // Deduplicate by cid
      const uniqueCids = Array.from(new Set(candidateMatches.map((c) => c.cid)));
      if (uniqueCids.length === 1) {
        const firstMatch = candidateMatches[0];
        if (firstMatch) {
          const entity = this.entities.get(firstMatch.cid)!;
          return {
            source_record_id: sourceRecordId,
            raw_entity_name: rawNameClean,
            normalized_entity_name: normalizedName,
            canonical_entity_id: firstMatch.cid,
            canonical_entity_name: entity.canonical_name,
            match_strategy: 'CONSERVATIVE_TOKEN_MATCH',
            confidence: firstMatch.score,
            aliases_used: [firstMatch.alias],
            domains_used: [],
            resolver_version: RESOLVER_VERSION,
            timestamp: nowTs,
          };
        }
      } else if (uniqueCids.length > 1) {
        const cnames = uniqueCids.map((id) => this.entities.get(id)?.canonical_name || id);
        return {
          source_record_id: sourceRecordId,
          raw_entity_name: rawNameClean,
          normalized_entity_name: normalizedName,
          canonical_entity_id: null,
          canonical_entity_name: null,
          match_strategy: 'AMBIGUOUS_MULTI_CANDIDATE',
          confidence: 0.0,
          aliases_used: [],
          domains_used: [],
          resolver_version: RESOLVER_VERSION,
          timestamp: nowTs,
          unresolved_reason: `Ambiguous token match candidates: ${JSON.stringify(cnames)}`,
        };
      }
    }

    // Fallthrough: Unresolved
    return {
      source_record_id: sourceRecordId,
      raw_entity_name: rawNameClean,
      normalized_entity_name: normalizedName,
      canonical_entity_id: null,
      canonical_entity_name: null,
      match_strategy: 'UNRESOLVED',
      confidence: 0.0,
      aliases_used: [],
      domains_used: [],
      resolver_version: RESOLVER_VERSION,
      timestamp: nowTs,
      unresolved_reason: 'NO_MATCHING_ENTITY_FOUND',
    };
  }
}
