import {
  CanonicalJsonSchema,
  CompletionRequestOptions,
  CompletionResult,
  HttpClient,
} from '../types/index.js';
import { BaseProviderAdapter } from './adapter.js';
import { ProviderError } from '../utils/errors.js';
import { parseJsonSafely } from '../utils/json_repair.js';

export class GeminiFlashAdapter extends BaseProviderAdapter {
  readonly name = 'gemini-flash';
  readonly defaultModel = 'gemini-1.5-flash';

  constructor(params: {
    apiKey?: string;
    baseUrl?: string;
    httpClient?: HttpClient;
  } = {}) {
    super({
      apiKey: params.apiKey,
      baseUrl:
        params.baseUrl ||
        'https://generativelanguage.googleapis.com/v1beta',
      httpClient: params.httpClient,
    });
  }

  async complete(
    prompt: string,
    schema: CanonicalJsonSchema,
    options: CompletionRequestOptions
  ): Promise<CompletionResult> {
    if (!this.apiKey) {
      throw new ProviderError({
        message: 'Missing GEMINI_API_KEY for gemini-flash adapter',
        provider: this.name,
        model: options.model || this.defaultModel,
        requestId: options.requestId,
      });
    }

    const model = options.model || this.defaultModel;
    const url = `${this.baseUrl}/models/${encodeURIComponent(model)}:generateContent?key=${encodeURIComponent(this.apiKey)}`;
    const systemPrompt = this.buildSystemPrompt(schema);

    const body = {
      contents: [
        {
          role: 'user',
          parts: [
            {
              text: `${systemPrompt}\n\nINPUT CONTENT TO EXTRACT FROM:\n${prompt}`,
            },
          ],
        },
      ],
      generationConfig: {
        responseMimeType: 'application/json',
        temperature: options.temperature ?? 0.1,
      },
    };

    const startTime = Date.now();
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), options.timeoutMs);

    const abortHandler = () => controller.abort();
    if (options.signal) {
      options.signal.addEventListener('abort', abortHandler, { once: true });
    }

    try {
      const res = await this.httpClient.fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Request-Id': options.requestId,
        },
        body: JSON.stringify(body),
        signal: controller.signal,
      });

      const latencyMs = Date.now() - startTime;
      await this.handleHttpResponseErrors(res, model, options.requestId, latencyMs);

      const jsonResponse = (await res.json()) as {
        candidates?: Array<{
          content?: {
            parts?: Array<{ text?: string }>;
          };
        }>;
      };

      const candidateText =
        jsonResponse.candidates?.[0]?.content?.parts?.[0]?.text?.trim() || '';

      if (!candidateText) {
        throw new ProviderError({
          message: 'Gemini returned empty candidate response',
          provider: this.name,
          model,
          latencyMs,
          requestId: options.requestId,
        });
      }

      const parsedJson = parseJsonSafely(candidateText, this.name, model);

      return {
        rawText: candidateText,
        parsedJson,
        provider: this.name,
        model,
        latencyMs,
        requestId: options.requestId,
      };
    } catch (err: unknown) {
      const latencyMs = Date.now() - startTime;
      if (err instanceof ProviderError) {
        throw err;
      }
      if (
        (err as { name?: string }).name === 'AbortError' ||
        controller.signal.aborted
      ) {
        if (options.signal?.aborted) {
          throw err;
        }
        throw new ProviderError({
          message: `Request timed out after ${options.timeoutMs}ms`,
          provider: this.name,
          model,
          statusCode: 408,
          latencyMs,
          requestId: options.requestId,
        });
      }
      throw new ProviderError({
        message: err instanceof Error ? err.message : String(err),
        provider: this.name,
        model,
        latencyMs,
        requestId: options.requestId,
      });
    } finally {
      clearTimeout(timeoutId);
      if (options.signal) {
        options.signal.removeEventListener('abort', abortHandler);
      }
    }
  }
}
