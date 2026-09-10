import { describe, expect, it } from 'vitest';
import { GeminiFlashAdapter } from '../src/providers/gemini.js';
import { GroqLlamaAdapter } from '../src/providers/groq.js';
import { DeepSeekAdapter } from '../src/providers/deepseek.js';
import { HttpClient } from '../src/types/index.js';
import {
  PayloadTooLargeError,
  ProviderError,
  RateLimitError,
} from '../src/utils/errors.js';

describe('Provider Adapters', () => {
  const dummySchema = { type: 'object', properties: { name: { type: 'string' } } };

  it('GeminiFlashAdapter formats request and parses candidate response', async () => {
    let capturedUrl = '';
    let capturedBody: unknown = null;

    const mockHttpClient: HttpClient = {
      async fetch(url, init) {
        capturedUrl = String(url);
        capturedBody = JSON.parse(init?.body as string);
        return new Response(
          JSON.stringify({
            candidates: [
              {
                content: {
                  parts: [{ text: '{"name": "Gemini Startup"}' }],
                },
              },
            ],
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } }
        );
      },
    };

    const adapter = new GeminiFlashAdapter({
      apiKey: 'test-gemini-key',
      httpClient: mockHttpClient,
    });

    const result = await adapter.complete('Extract startup', dummySchema, {
      requestId: 'req-123',
      model: 'gemini-1.5-flash',
      timeoutMs: 5000,
    });

    expect(capturedUrl).toContain('models/gemini-1.5-flash:generateContent?key=test-gemini-key');
    expect(capturedBody).toHaveProperty('generationConfig');
    expect(result.rawText).toBe('{"name": "Gemini Startup"}');
    expect(result.parsedJson).toEqual({ name: 'Gemini Startup' });
    expect(result.provider).toBe('gemini-flash');
  });

  it('GroqLlamaAdapter translates 429 with Retry-After into RateLimitError', async () => {
    const mockHttpClient: HttpClient = {
      async fetch() {
        return new Response('Rate limit reached', {
          status: 429,
          headers: { 'retry-after': '3' },
        });
      },
    };

    const adapter = new GroqLlamaAdapter({
      apiKey: 'test-groq-key',
      httpClient: mockHttpClient,
    });

    await expect(
      adapter.complete('prompt', dummySchema, {
        requestId: 'req-429',
        model: 'llama-3.3-70b-versatile',
        timeoutMs: 5000,
      })
    ).rejects.toThrow(RateLimitError);

    try {
      await adapter.complete('prompt', dummySchema, {
        requestId: 'req-429',
        model: 'llama-3.3-70b-versatile',
        timeoutMs: 5000,
      });
    } catch (err) {
      const rateErr = err as RateLimitError;
      expect(rateErr.statusCode).toBe(429);
      expect(rateErr.retryAfterMs).toBe(3000);
      expect(rateErr.provider).toBe('groq-llama3');
    }
  });

  it('DeepSeekAdapter translates 413 into PayloadTooLargeError', async () => {
    const mockHttpClient: HttpClient = {
      async fetch() {
        return new Response('Payload Too Large', { status: 413 });
      },
    };

    const adapter = new DeepSeekAdapter({
      apiKey: 'test-deepseek-key',
      httpClient: mockHttpClient,
    });

    await expect(
      adapter.complete('prompt', dummySchema, {
        requestId: 'req-413',
        model: 'deepseek-chat',
        timeoutMs: 5000,
      })
    ).rejects.toThrow(PayloadTooLargeError);
  });

  it('handles server 500 errors as ProviderError', async () => {
    const mockHttpClient: HttpClient = {
      async fetch() {
        return new Response('Internal Server Error', { status: 500 });
      },
    };

    const adapter = new DeepSeekAdapter({
      apiKey: 'test-key',
      httpClient: mockHttpClient,
    });

    await expect(
      adapter.complete('prompt', dummySchema, {
        requestId: 'req-500',
        model: 'deepseek-chat',
        timeoutMs: 5000,
      })
    ).rejects.toThrow(ProviderError);
  });
});
