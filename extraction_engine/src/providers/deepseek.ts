import {
  CanonicalJsonSchema,
  CompletionRequestOptions,
  CompletionResult,
  HttpClient,
} from '../types/index.js';
import { BaseProviderAdapter } from './adapter.js';
import { ProviderError } from '../utils/errors.js';
import { parseJsonSafely } from '../utils/json_repair.js';

export class DeepSeekAdapter extends BaseProviderAdapter {
  readonly name = 'deepseek';
  readonly defaultModel = 'deepseek-chat';

  constructor(params: {
    apiKey?: string;
    baseUrl?: string;
    httpClient?: HttpClient;
  } = {}) {
    super({
      apiKey: params.apiKey,
      baseUrl: params.baseUrl || 'https://api.deepseek.com',
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
        message: 'Missing DEEPSEEK_API_KEY for deepseek adapter',
        provider: this.name,
        model: options.model || this.defaultModel,
        requestId: options.requestId,
      });
    }

    const model = options.model || this.defaultModel;
    const url = `${this.baseUrl}/chat/completions`;
    const systemPrompt = this.buildSystemPrompt(schema);

    const body = {
      model,
      messages: [
        { role: 'system', content: systemPrompt },
        { role: 'user', content: prompt },
      ],
      response_format: { type: 'json_object' },
      temperature: options.temperature ?? 0.1,
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
          Authorization: `Bearer ${this.apiKey}`,
          'X-Request-Id': options.requestId,
        },
        body: JSON.stringify(body),
        signal: controller.signal,
      });

      const latencyMs = Date.now() - startTime;
      await this.handleHttpResponseErrors(res, model, options.requestId, latencyMs);

      const jsonResponse = (await res.json()) as {
        choices?: Array<{
          message?: {
            content?: string;
          };
        }>;
      };

      const messageContent =
        jsonResponse.choices?.[0]?.message?.content?.trim() || '';

      if (!messageContent) {
        throw new ProviderError({
          message: 'DeepSeek returned empty choices response',
          provider: this.name,
          model,
          latencyMs,
          requestId: options.requestId,
        });
      }

      const parsedJson = parseJsonSafely(messageContent, this.name, model);

      return {
        rawText: messageContent,
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
