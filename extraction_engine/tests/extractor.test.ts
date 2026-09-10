import { describe, expect, it } from 'vitest';
import { ExtractionEngine } from '../src/engine/extractor.js';
import {
  CanonicalJsonSchema,
  CompletionRequestOptions,
  CompletionResult,
  LLMProviderAdapter,
} from '../src/types/index.js';
import {
  ProductCanonicalSchema,
  ResearchPaperCanonicalSchema,
  StartupCanonicalSchema,
} from '../src/schemas/canonical.js';
import {
  AllProvidersExhaustedError,
  ExtractionAbortedError,
  PayloadTooLargeError,
  ProviderError,
  RateLimitError,
} from '../src/utils/errors.js';

class MockAdapter implements LLMProviderAdapter {
  constructor(
    public readonly name: string,
    public readonly defaultModel: string,
    public handler: (
      prompt: string,
      schema: CanonicalJsonSchema,
      opts: CompletionRequestOptions
    ) => Promise<CompletionResult>
  ) {}

  isAvailable(): boolean {
    return true;
  }

  complete(
    prompt: string,
    schema: CanonicalJsonSchema,
    options: CompletionRequestOptions
  ): Promise<CompletionResult> {
    return this.handler(prompt, schema, options);
  }
}

describe('Extraction Engine Orchestrator', () => {
  const mockClock = {
    now: () => Date.now(),
    sleep: () => Promise.resolve(),
  };

  const fixedRng = { random: () => 0.5 };

  it('successfully extracts StartupRecord from clean HTML', async () => {
    const htmlInput = `
      <html>
        <body>
          <h1>Databricks</h1>
          <p>Enterprise data and AI company with 7500 employees.</p>
        </body>
      </html>
    `;

    const expectedRecord = {
      schemaVersion: '1.0',
      recordType: 'STARTUP',
      source: { name: 'Web', url: 'https://databricks.com' },
      content: {
        entityName: 'Databricks',
        data: { employeeCount: 7500 },
      },
      collectedAt: '2026-09-10T12:00:00Z',
    };

    const geminiMock = new MockAdapter(
      'gemini-flash',
      'gemini-1.5-flash',
      async () => ({
        rawText: JSON.stringify(expectedRecord),
        parsedJson: expectedRecord,
        provider: 'gemini-flash',
        model: 'gemini-1.5-flash',
        latencyMs: 120,
      })
    );

    const engine = new ExtractionEngine({ clock: mockClock, rng: fixedRng });
    engine.registerProvider(geminiMock);

    const result = await engine.extract({
      input: { html: htmlInput, sourceUrl: 'https://databricks.com' },
      schema: StartupCanonicalSchema,
      options: { providers: ['gemini-flash'] },
    });

    expect(result.data).toEqual(expectedRecord);
    expect(result.metadata.provider).toBe('gemini-flash');
    expect(result.metadata.validationPassed).toBe(true);
    expect(result.metadata.chunksProcessed).toBe(1);
    expect(result.metadata.fallbacksUsed).toEqual([]);
  });

  it('successfully extracts ProductRecord from plain text', async () => {
    const textInput =
      'Resend is an email platform for developers with a FREEMIUM pricing model.';

    const expectedRecord = {
      schemaVersion: '1.0',
      recordType: 'PRODUCT',
      source: { name: 'Direct', url: 'https://resend.com' },
      content: {
        startupName: 'Resend',
        pricingModel: 'FREEMIUM',
      },
      collectedAt: '2026-09-10T12:00:00Z',
    };

    const groqMock = new MockAdapter(
      'groq-llama3',
      'llama-3.3-70b-versatile',
      async () => ({
        rawText: JSON.stringify(expectedRecord),
        parsedJson: expectedRecord,
        provider: 'groq-llama3',
        model: 'llama-3.3-70b-versatile',
        latencyMs: 80,
      })
    );

    const engine = new ExtractionEngine({ clock: mockClock, rng: fixedRng });
    engine.registerProvider(groqMock);

    const result = await engine.extract({
      input: { text: textInput, sourceUrl: 'https://resend.com' },
      schema: ProductCanonicalSchema,
      options: { providers: ['groq-llama3'] },
    });

    expect(result.data).toEqual(expectedRecord);
    expect(result.metadata.provider).toBe('groq-llama3');
  });

  it('falls over from primary provider on timeout to secondary provider', async () => {
    // Gemini times out (408)
    const geminiMock = new MockAdapter(
      'gemini-flash',
      'gemini-1.5-flash',
      async () => {
        throw new ProviderError({
          message: 'Request timed out after 30000ms',
          provider: 'gemini-flash',
          model: 'gemini-1.5-flash',
          statusCode: 408,
          retryCount: 0,
        });
      }
    );

    const expectedRecord = {
      schemaVersion: '1.0',
      recordType: 'PRODUCT',
      source: { name: 'Directory', url: 'https://app.com' },
      content: { startupName: 'App', pricingModel: 'PAID' },
      collectedAt: '2026-09-10T12:00:00Z',
    };

    // Groq succeeds
    const groqMock = new MockAdapter(
      'groq-llama3',
      'llama-3.3-70b-versatile',
      async () => ({
        rawText: JSON.stringify(expectedRecord),
        parsedJson: expectedRecord,
        provider: 'groq-llama3',
        model: 'llama-3.3-70b-versatile',
        latencyMs: 95,
      })
    );

    const engine = new ExtractionEngine({ clock: mockClock, rng: fixedRng });
    engine.registerProvider(geminiMock);
    engine.registerProvider(groqMock);

    const result = await engine.extract({
      input: { text: 'App is paid subscription.' },
      schema: ProductCanonicalSchema,
      options: {
        providers: ['gemini-flash', 'groq-llama3'],
        maxRetries: 0,
      },
    });

    expect(result.data).toEqual(expectedRecord);
    expect(result.metadata.provider).toBe('groq-llama3');
    expect(result.metadata.fallbacksUsed).toEqual(['gemini-flash']);
  });

  it('handles 429 rate limit with Retry-After and retries successfully', async () => {
    let callCount = 0;
    const expectedRecord = {
      schemaVersion: '1.0',
      recordType: 'STARTUP',
      source: { name: 'Wiki', url: 'https://example.com' },
      content: { entityName: 'Example', data: { employeeCount: 10 } },
      collectedAt: '2026-09-10T12:00:00Z',
    };

    const geminiMock = new MockAdapter(
      'gemini-flash',
      'gemini-1.5-flash',
      async () => {
        callCount++;
        if (callCount === 1) {
          throw new RateLimitError({
            message: 'Rate limit exceeded',
            provider: 'gemini-flash',
            model: 'gemini-1.5-flash',
            retryAfterMs: 1500,
          });
        }
        return {
          rawText: JSON.stringify(expectedRecord),
          parsedJson: expectedRecord,
          provider: 'gemini-flash',
          model: 'gemini-1.5-flash',
          latencyMs: 100,
        };
      }
    );

    const engine = new ExtractionEngine({ clock: mockClock, rng: fixedRng });
    engine.registerProvider(geminiMock);

    const result = await engine.extract({
      input: { text: 'Example startup with 10 employees.' },
      schema: StartupCanonicalSchema,
      options: { providers: ['gemini-flash'], maxRetries: 2 },
    });

    expect(callCount).toBe(2);
    expect(result.data).toEqual(expectedRecord);
    expect(result.metadata.retriesCount).toBe(1);
  });

  it('recovers from 413 Payload Too Large by reducing chunk size and re-chunking', async () => {
    let callCount = 0;
    const expectedRecord = {
      schemaVersion: '1.0',
      recordType: 'STARTUP',
      source: { name: 'Docs', url: 'https://bigdoc.com' },
      content: { entityName: 'BigDoc Corp', data: { employeeCount: 300 } },
      collectedAt: '2026-09-10T12:00:00Z',
    };

    const docText = [
      '# Section 1: Overview',
      'BigDoc Corp is an enterprise company with 300 employees.',
      '',
      '# Section 2: Products',
      'BigDoc produces enterprise analytics software.',
    ].join('\n');

    const geminiMock = new MockAdapter(
      'gemini-flash',
      'gemini-1.5-flash',
      async () => {
        callCount++;
        if (callCount === 1) {
          // First attempt fails with 413
          throw new PayloadTooLargeError({
            message: 'Payload Too Large',
            provider: 'gemini-flash',
            model: 'gemini-1.5-flash',
          });
        }
        // Subsequent attempts with halved chunks succeed
        return {
          rawText: JSON.stringify(expectedRecord),
          parsedJson: expectedRecord,
          provider: 'gemini-flash',
          model: 'gemini-1.5-flash',
          latencyMs: 110,
        };
      }
    );

    const engine = new ExtractionEngine({ clock: mockClock, rng: fixedRng });
    engine.registerProvider(geminiMock);

    const result = await engine.extract({
      input: { text: docText },
      schema: StartupCanonicalSchema,
      options: { providers: ['gemini-flash'], maxRetries: 1 },
    });

    expect(callCount).toBeGreaterThanOrEqual(2);
    expect(result.data).toEqual(expectedRecord);
    expect(result.metadata.provider).toBe('gemini-flash');
  });

  it('executes bounded JSON repair when model output has syntax errors', async () => {
    let attemptCount = 0;
    const validRecord = {
      schemaVersion: '1.0',
      recordType: 'STARTUP',
      source: { name: 'Tech', url: 'https://tech.com' },
      content: { entityName: 'RepairCo', data: { employeeCount: 25 } },
      collectedAt: '2026-09-10T12:00:00Z',
    };

    const geminiMock = new MockAdapter(
      'gemini-flash',
      'gemini-1.5-flash',
      async (prompt) => {
        attemptCount++;
        if (attemptCount === 1) {
          // Return broken JSON that cannot even be healed locally
          return {
            rawText: 'Here is the result: { invalid_key_without_quotes: ',
            provider: 'gemini-flash',
            model: 'gemini-1.5-flash',
            latencyMs: 50,
          };
        }

        // Repair attempt prompt received
        expect(prompt).toContain('CRITICAL INSTRUCTION: Your previous response was invalid');
        return {
          rawText: JSON.stringify(validRecord),
          parsedJson: validRecord,
          provider: 'gemini-flash',
          model: 'gemini-1.5-flash',
          latencyMs: 60,
        };
      }
    );

    const engine = new ExtractionEngine({ clock: mockClock, rng: fixedRng });
    engine.registerProvider(geminiMock);

    const result = await engine.extract({
      input: { text: 'RepairCo has 25 employees.' },
      schema: StartupCanonicalSchema,
      options: { providers: ['gemini-flash'], repairAttempts: 1 },
    });

    expect(attemptCount).toBe(2);
    expect(result.data).toEqual(validRecord);
    expect(result.metadata.repairAttemptsUsed).toBe(1);
  });

  it('falls over when provider returns schema-invalid JSON even after repair attempt', async () => {
    const invalidRecord = {
      schemaVersion: '1.0',
      recordType: 'STARTUP',
      // Missing required 'source' and 'content.entityName'
      content: { data: { employeeCount: 10 } },
    };

    const expectedRecord = {
      schemaVersion: '1.0',
      recordType: 'STARTUP',
      source: { name: 'ValidSource', url: 'https://valid.com' },
      content: { entityName: 'ValidCo', data: { employeeCount: 10 } },
      collectedAt: '2026-09-10T12:00:00Z',
    };

    const geminiMock = new MockAdapter(
      'gemini-flash',
      'gemini-1.5-flash',
      async () => ({
        rawText: JSON.stringify(invalidRecord),
        parsedJson: invalidRecord,
        provider: 'gemini-flash',
        model: 'gemini-1.5-flash',
        latencyMs: 50,
      })
    );

    const groqMock = new MockAdapter(
      'groq-llama3',
      'llama-3.3-70b-versatile',
      async () => ({
        rawText: JSON.stringify(expectedRecord),
        parsedJson: expectedRecord,
        provider: 'groq-llama3',
        model: 'llama-3.3-70b-versatile',
        latencyMs: 55,
      })
    );

    const engine = new ExtractionEngine({ clock: mockClock, rng: fixedRng });
    engine.registerProvider(geminiMock);
    engine.registerProvider(groqMock);

    const result = await engine.extract({
      input: { text: 'Some startup info' },
      schema: StartupCanonicalSchema,
      options: {
        providers: ['gemini-flash', 'groq-llama3'],
        repairAttempts: 1, // Gemini will try 1 repair, fail again, then fail over to Groq
      },
    });

    expect(result.data).toEqual(expectedRecord);
    expect(result.metadata.provider).toBe('groq-llama3');
    expect(result.metadata.fallbacksUsed).toContain('gemini-flash');
  });

  it('throws AllProvidersExhaustedError with complete failure context when all fail', async () => {
    const geminiMock = new MockAdapter(
      'gemini-flash',
      'gemini-1.5-flash',
      async () => {
        throw new ProviderError({
          message: 'Gemini server error',
          provider: 'gemini-flash',
          model: 'gemini-1.5-flash',
          statusCode: 500,
        });
      }
    );

    const groqMock = new MockAdapter(
      'groq-llama3',
      'llama-3.3-70b-versatile',
      async () => {
        throw new ProviderError({
          message: 'Groq connection refused',
          provider: 'groq-llama3',
          model: 'llama-3.3-70b-versatile',
          statusCode: 503,
        });
      }
    );

    const engine = new ExtractionEngine({ clock: mockClock, rng: fixedRng });
    engine.registerProvider(geminiMock);
    engine.registerProvider(groqMock);

    await expect(
      engine.extract({
        input: { text: 'Some text' },
        schema: StartupCanonicalSchema,
        options: {
          providers: ['gemini-flash', 'groq-llama3'],
          maxRetries: 0,
        },
      })
    ).rejects.toThrow(AllProvidersExhaustedError);

    try {
      await engine.extract({
        input: { text: 'Some text' },
        schema: StartupCanonicalSchema,
        options: {
          providers: ['gemini-flash', 'groq-llama3'],
          maxRetries: 0,
        },
      });
    } catch (err) {
      const allErr = err as AllProvidersExhaustedError;
      expect(allErr.chainFailures.length).toBe(2);
      expect(allErr.chainFailures[0]?.provider).toBe('gemini-flash');
      expect(allErr.chainFailures[1]?.provider).toBe('groq-llama3');
    }
  });

  it('aborts extraction promptly when AbortSignal fires', async () => {
    const controller = new AbortController();
    controller.abort(); // already aborted

    const geminiMock = new MockAdapter(
      'gemini-flash',
      'gemini-1.5-flash',
      async () => ({
        rawText: '{}',
        provider: 'gemini-flash',
        model: 'gemini-1.5-flash',
        latencyMs: 10,
      })
    );

    const engine = new ExtractionEngine({ clock: mockClock, rng: fixedRng });
    engine.registerProvider(geminiMock);

    await expect(
      engine.extract({
        input: { text: 'Content' },
        schema: StartupCanonicalSchema,
        options: { signal: controller.signal },
      })
    ).rejects.toThrow(ExtractionAbortedError);
  });
});
