import { describe, it, expect } from 'vitest';
import { DeterministicEntityResolver } from '../src/entity_resolution/resolver.js';
import { normalizeEntityName, normalizeDomain } from '../src/entity_resolution/normalizer.js';

describe('Deterministic Entity Resolution (Phase IV - TypeScript)', () => {
  const resolver = new DeterministicEntityResolver();

  it('normalizes corporate suffixes and AI spacing correctly', () => {
    expect(normalizeEntityName('OpenAI, Inc.')).toBe('openai');
    expect(normalizeEntityName('Open AI')).toBe('openai');
    expect(normalizeEntityName('OpenAI LLC')).toBe('openai');
    expect(normalizeEntityName('Cohere Inc.')).toBe('cohere');
    expect(normalizeEntityName('DeepL GmbH')).toBe('deepl');
    expect(normalizeEntityName('Synthesia Limited')).toBe('synthesia');
    expect(normalizeEntityName('Weaviate B.V.')).toBe('weaviate');
    expect(normalizeEntityName('Qdrant Solutions GmbH')).toBe('qdrant solutions');
    expect(resolver.resolve('Qdrant Solutions GmbH').canonical_entity_id).toBe('qdrant');
  });

  it('normalizes domains accurately', () => {
    expect(normalizeDomain('https://www.openai.com/research?id=123')).toBe('openai.com');
    expect(normalizeDomain('ANTHROPIC.COM/')).toBe('anthropic.com');
    expect(normalizeDomain('http://blog.weaviate.io:8080/post')).toBe('blog.weaviate.io');
  });

  it('resolves OpenAI naming variants to canonical OpenAI with high confidence', () => {
    const variants = [
      'OpenAI',
      'OpenAI, Inc.',
      'Open AI',
      'OpenAI Inc',
      'OpenAI LLC',
      'OpenAI OpCo LLC',
    ];

    for (const v of variants) {
      const result = resolver.resolve(v, 'test-rec-1');
      expect(result.canonical_entity_id).toBe('openai');
      expect(result.canonical_entity_name).toBe('OpenAI');
      expect(result.confidence).toBeGreaterThanOrEqual(0.98);
      expect(result.raw_entity_name).toBe(v);
      expect(result.resolver_version).toBe('1.0.0');
    }
  });

  it('resolves official domains safely', () => {
    const result = resolver.resolve('Something Unknown', 'test-rec-2', 'https://openai.com/about');
    expect(result.canonical_entity_id).toBe('openai');
    expect(result.canonical_entity_name).toBe('OpenAI');
    expect(result.match_strategy).toBe('OFFICIAL_DOMAIN');
    expect(result.confidence).toBe(1.0);
  });

  it('leaves ambiguous names unresolved and provides detailed reasons', () => {
    // Both Cohere and Cohere Health exist in seed data.
    // If input is purely "Cohere", it maps to Cohere exact.
    // But if input has ambiguous matching across distinct canonical entities, it must not guess.
    const customSeed = [
      {
        canonical_id: 'alpha_labs',
        canonical_name: 'Alpha Labs',
        verified_aliases: ['Alpha', 'Alpha Systems'],
        normalized_aliases: ['alpha', 'alpha systems'],
        official_domains: ['alpha.ai'],
      },
      {
        canonical_id: 'alpha_ai',
        canonical_name: 'Alpha AI',
        verified_aliases: ['Alpha', 'Alpha Technologies'],
        normalized_aliases: ['alpha', 'alpha technologies'],
        official_domains: ['alpha-ai.com'],
      },
    ];

    const ambigResolver = new DeterministicEntityResolver(customSeed);
    const result = ambigResolver.resolve('Alpha', 'test-ambig');
    expect(result.canonical_entity_id).toBeNull();
    expect(result.match_strategy).toBe('AMBIGUOUS_MULTI_CANDIDATE');
    expect(result.confidence).toBe(0.0);
    expect(result.unresolved_reason).toContain('Ambiguous');
  });

  it('prevents false positives on generic AI noise words', () => {
    const noiseWords = ['AI', 'Artificial Intelligence', 'Lab', 'Systems', 'Cloud', 'Data'];
    for (const noise of noiseWords) {
      const result = resolver.resolve(noise, 'test-noise');
      expect(result.canonical_entity_id).toBeNull();
      expect(result.confidence).toBe(0.0);
    }
  });

  it('produces deterministic identical results on repeated calls', () => {
    const r1 = resolver.resolve('Anthropic, PBC', 'rep-1');
    const r2 = resolver.resolve('Anthropic, PBC', 'rep-1');
    expect(r1.canonical_entity_id).toBe(r2.canonical_entity_id);
    expect(r1.match_strategy).toBe(r2.match_strategy);
    expect(r1.confidence).toBe(r2.confidence);
    expect(r1.normalized_entity_name).toBe(r2.normalized_entity_name);
  });
});
