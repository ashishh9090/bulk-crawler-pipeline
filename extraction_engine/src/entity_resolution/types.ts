/**
 * Types for deterministic entity resolution.
 */

export type MatchStrategy =
  | 'EXACT_CANONICAL_NAME'
  | 'EXACT_CONFIGURED_ALIAS'
  | 'EXACT_NORMALIZED_ALIAS'
  | 'OFFICIAL_DOMAIN'
  | 'CONSERVATIVE_TOKEN_MATCH'
  | 'UNRESOLVED'
  | 'AMBIGUOUS_MULTI_CANDIDATE';

export interface EntitySeedRecord {
  canonical_id: string;
  canonical_name: string;
  verified_aliases: string[];
  normalized_aliases: string[];
  official_domains: string[];
  verification_url?: string;
}

export interface EntityResolutionResult {
  source_record_id: string;
  raw_entity_name: string;
  normalized_entity_name: string;
  canonical_entity_id: string | null;
  canonical_entity_name: string | null;
  match_strategy: MatchStrategy;
  confidence: number;
  aliases_used: string[];
  domains_used: string[];
  resolver_version: string;
  timestamp: string;
  unresolved_reason?: string | null;
}
