import { describe, expect, it } from 'vitest';
import {
  ProductCanonicalSchema,
  ResearchPaperCanonicalSchema,
  StartupCanonicalSchema,
} from '../src/schemas/canonical.js';
import { assertValidSchema, validateSchema } from '../src/schemas/validator.js';
import { SchemaValidationError } from '../src/utils/errors.js';

describe('Canonical Schema Validation', () => {
  it('validates a correct StartupRecord', () => {
    const startup = {
      schemaVersion: '1.0',
      recordType: 'STARTUP',
      source: {
        name: 'Wikidata',
        url: 'https://about.google/',
      },
      content: {
        entityName: 'Google',
        data: {
          employeeCount: 187000,
        },
      },
      collectedAt: '2026-09-10T04:39:50.773910+00:00',
    };

    const res = validateSchema(StartupCanonicalSchema, startup);
    expect(res.valid).toBe(true);
    expect(res.errors.length).toBe(0);
  });

  it('allows null employeeCount in StartupRecord', () => {
    const startup = {
      schemaVersion: '1.0',
      recordType: 'STARTUP',
      source: { name: 'AngelList', url: 'https://angel.co/stealth' },
      content: {
        entityName: 'StealthStartup',
        data: { employeeCount: null },
      },
      collectedAt: '2026-09-10T04:39:50.773910+00:00',
    };

    const validated = assertValidSchema(StartupCanonicalSchema, startup);
    expect(validated).toEqual(startup);
  });

  it('rejects StartupRecord with negative employee count or missing entityName', () => {
    const invalid = {
      schemaVersion: '1.0',
      recordType: 'STARTUP',
      source: { name: 'Crunchbase', url: 'https://example.com' },
      content: {
        data: { employeeCount: -5 }, // missing entityName, negative count
      },
      collectedAt: '2026-09-10T04:39:50.773910+00:00',
    };

    const res = validateSchema(StartupCanonicalSchema, invalid);
    expect(res.valid).toBe(false);
    expect(res.formattedError).toContain('entityName');

    expect(() =>
      assertValidSchema(StartupCanonicalSchema, invalid)
    ).toThrow(SchemaValidationError);
  });

  it('validates a correct ProductRecord with strictly classified pricingModel', () => {
    const product = {
      schemaVersion: '1.0',
      recordType: 'PRODUCT',
      source: { name: 'SaaSHub', url: 'https://resend.com/' },
      content: {
        startupName: 'Resend',
        pricingModel: 'FREEMIUM',
      },
      collectedAt: '2026-09-10T04:39:32.596702+00:00',
    };

    const res = validateSchema(ProductCanonicalSchema, product);
    expect(res.valid).toBe(true);
  });

  it('rejects ProductRecord with invalid pricingModel', () => {
    const product = {
      schemaVersion: '1.0',
      recordType: 'PRODUCT',
      source: { name: 'SaaSHub', url: 'https://resend.com/' },
      content: {
        startupName: 'Resend',
        pricingModel: 'SOME_UNKNOWN_PRICE',
      },
      collectedAt: '2026-09-10T04:39:32.596702+00:00',
    };

    const res = validateSchema(ProductCanonicalSchema, product);
    expect(res.valid).toBe(false);
    expect(res.formattedError).toContain('pricingModel');
  });

  it('validates a correct ResearchPaperRecord', () => {
    const paper = {
      schemaVersion: '1.0',
      recordType: 'RESEARCH_PAPER',
      source: { name: 'arXiv', url: 'https://arxiv.org/abs/2609.10540v1' },
      content: {
        title: 'Programmable World Model',
        authors: ['Zheng-Hui Huang', 'Guixu Lin', 'Jiacheng Lin'],
        paper_url: 'https://arxiv.org/abs/2609.10540v1',
        github_url: 'https://github.com/AlayaLab/pwm',
        github_stars: 56,
        published_date: '2026-09-09T17:59:32Z',
      },
      collectedAt: '2026-09-10T04:39:18.398478+00:00',
    };

    const res = validateSchema(ResearchPaperCanonicalSchema, paper);
    expect(res.valid).toBe(true);
  });
});
