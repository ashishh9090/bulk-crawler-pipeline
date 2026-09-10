import { describe, expect, it } from 'vitest';
import {
  consolidateCandidates,
  mergeObjects,
} from '../src/engine/consolidator.js';
import {
  ProductCanonicalSchema,
  ResearchPaperCanonicalSchema,
  StartupCanonicalSchema,
} from '../src/schemas/canonical.js';

describe('Candidate Consolidation', () => {
  it('deep merges objects preferring richer and non-null values', () => {
    const objA = {
      name: 'Startup',
      count: 0,
      description: 'Short',
      tags: ['ai'],
    };
    const objB = {
      count: 50,
      description: 'Longer description with more detail',
      tags: ['ai', 'ml'],
    };

    const merged = mergeObjects(objA, objB);
    expect(merged['name']).toBe('Startup');
    expect(merged['count']).toBe(50);
    expect(merged['description']).toBe('Longer description with more detail');
    expect(merged['tags']).toEqual(['ai', 'ml']);
  });

  it('consolidates partial StartupRecord candidates from multiple chunks', () => {
    // Chunk 1 extracted basic identity
    const candidate1 = {
      schemaVersion: '1.0',
      recordType: 'STARTUP',
      source: { name: 'TechCrunch', url: 'https://techcrunch.com/article' },
      content: {
        entityName: 'Anthropic',
        data: { employeeCount: null },
      },
      collectedAt: '2026-09-10T12:00:00Z',
    };

    // Chunk 2 extracted verified employee count
    const candidate2 = {
      schemaVersion: '1.0',
      recordType: 'STARTUP',
      source: { name: 'TechCrunch', url: 'https://techcrunch.com/article' },
      content: {
        entityName: 'Anthropic PBC',
        data: { employeeCount: 500 },
      },
      collectedAt: '2026-09-10T12:00:00Z',
    };

    const consolidated = consolidateCandidates<typeof candidate2>(
      [candidate1, candidate2],
      StartupCanonicalSchema
    );

    expect(consolidated.content.entityName).toBe('Anthropic PBC');
    expect(consolidated.content.data.employeeCount).toBe(500);
    expect(consolidated.schemaVersion).toBe('1.0');
  });

  it('consolidates ResearchPaperRecord and deduplicates author lists', () => {
    const candidate1 = {
      schemaVersion: '1.0',
      recordType: 'RESEARCH_PAPER',
      source: { name: 'arXiv', url: 'https://arxiv.org/abs/2609.9999' },
      content: {
        title: 'Advances in Transformers',
        authors: ['Alice Smith', 'Bob Jones'],
        paper_url: 'https://arxiv.org/abs/2609.9999',
        github_url: null,
        github_stars: 0,
        published_date: '2026-09-01T00:00:00Z',
      },
      collectedAt: '2026-09-10T12:00:00Z',
    };

    const candidate2 = {
      schemaVersion: '1.0',
      recordType: 'RESEARCH_PAPER',
      source: { name: 'arXiv', url: 'https://arxiv.org/abs/2609.9999' },
      content: {
        title: 'Advances in Transformers: A Modern Survey',
        authors: ['Bob Jones', 'Charlie Brown'],
        paper_url: 'https://arxiv.org/abs/2609.9999',
        github_url: 'https://github.com/org/repo',
        github_stars: 120,
        published_date: '2026-09-01T00:00:00Z',
      },
      collectedAt: '2026-09-10T12:00:00Z',
    };

    const consolidated = consolidateCandidates<typeof candidate2>(
      [candidate1, candidate2],
      ResearchPaperCanonicalSchema
    );

    expect(consolidated.content.authors).toEqual([
      'Alice Smith',
      'Bob Jones',
      'Charlie Brown',
    ]);
    expect(consolidated.content.github_stars).toBe(120);
    expect(consolidated.content.github_url).toBe('https://github.com/org/repo');
  });
});
