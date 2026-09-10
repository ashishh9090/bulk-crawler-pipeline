import { describe, expect, it } from 'vitest';
import { ExtractionEngine } from '../src/engine/extractor.js';
import { StartupCanonicalSchema } from '../src/schemas/canonical.js';
import {
  CanonicalJsonSchema,
  CompletionRequestOptions,
  CompletionResult,
  LLMProviderAdapter,
} from '../src/types/index.js';

describe('Integration Tests: Multi-Chunk Hierarchical Extraction', () => {
  it('extracts and consolidates StartupRecord across a multi-chunk document', async () => {
    // A long document with separate sections that will be chunked
    const longHtml = `
      <html>
        <head><title>Stripe: Company Profile and Metrics</title></head>
        <body>
          <nav>Navigation links here</nav>
          <h1>Stripe, Inc.</h1>
          <section id="section-1">
            <h2>Overview</h2>
            <p>Stripe is an Irish-American financial services and SaaS company.</p>
          </section>
          <section id="section-2">
            <h2>Workforce and Team</h2>
            <p>As of late 2026, the company employs over 8,000 employees globally.</p>
          </section>
          <section id="section-3">
            <h2>Products and Services</h2>
            <p>Stripe provides payment processing APIs for e-commerce websites and mobile apps.</p>
          </section>
          <footer>Footer copyright info</footer>
        </body>
      </html>
    `;

    // Provider mock that extracts partial details based on what content is in each chunk
    let chunkCallCount = 0;
    const multiChunkAdapter: LLMProviderAdapter = {
      name: 'gemini-flash',
      defaultModel: 'gemini-1.5-flash',
      isAvailable: () => true,
      async complete(
        prompt: string,
        _schema: CanonicalJsonSchema,
        _opts: CompletionRequestOptions
      ): Promise<CompletionResult> {
        chunkCallCount++;

        if (prompt.includes('Workforce and Team') || prompt.includes('8,000 employees')) {
          const part2 = {
            schemaVersion: '1.0',
            recordType: 'STARTUP',
            source: { name: 'Stripe Profile', url: 'https://stripe.com' },
            content: {
              entityName: 'Stripe, Inc.',
              data: { employeeCount: 8000 },
            },
            collectedAt: '2026-09-10T15:00:00Z',
          };
          return {
            rawText: JSON.stringify(part2),
            parsedJson: part2,
            provider: 'gemini-flash',
            model: 'gemini-1.5-flash',
            latencyMs: 90,
          };
        }

        // Other chunk
        const part1 = {
          schemaVersion: '1.0',
          recordType: 'STARTUP',
          source: { name: 'Stripe Profile', url: 'https://stripe.com' },
          content: {
            entityName: 'Stripe, Inc.',
            data: { employeeCount: null },
          },
          collectedAt: '2026-09-10T15:00:00Z',
        };
        return {
          rawText: JSON.stringify(part1),
          parsedJson: part1,
          provider: 'gemini-flash',
          model: 'gemini-1.5-flash',
          latencyMs: 85,
        };
      },
    };

    const engine = new ExtractionEngine();
    engine.registerProvider(multiChunkAdapter);

    // Force maxCharsPerChunk small enough to create multiple chunks
    const result = await engine.extract({
      input: { html: longHtml, sourceUrl: 'https://stripe.com' },
      schema: StartupCanonicalSchema,
      options: {
        providers: ['gemini-flash'],
        maxPayloadBytes: 250, // creates ~3 chunks
      },
    });

    expect(result.metadata.chunksProcessed).toBeGreaterThan(1);
    expect(chunkCallCount).toBeGreaterThan(1);
    expect(result.data).toEqual({
      schemaVersion: '1.0',
      recordType: 'STARTUP',
      source: { name: 'Stripe Profile', url: 'https://stripe.com' },
      content: {
        entityName: 'Stripe, Inc.',
        data: { employeeCount: 8000 },
      },
      collectedAt: '2026-09-10T15:00:00Z',
    });
    expect(result.metadata.validationPassed).toBe(true);
  });
});
