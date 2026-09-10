import {
  CanonicalJsonSchema,
  CompletionRequestOptions,
  CompletionResult,
  HttpClient,
  LLMProviderAdapter,
  ProviderName,
} from '../types/index.js';
import {
  PayloadTooLargeError,
  ProviderError,
  RateLimitError,
} from '../utils/errors.js';
import { parseRetryAfter } from '../utils/backoff.js';

export class FetchHttpClient implements HttpClient {
  fetch(input: string | URL, init?: RequestInit): Promise<Response> {
    return fetch(input, init);
  }
}

export abstract class BaseProviderAdapter implements LLMProviderAdapter {
  abstract readonly name: ProviderName;
  abstract readonly defaultModel: string;

  protected httpClient: HttpClient;
  protected apiKey?: string;
  protected baseUrl: string;

  constructor(params: {
    apiKey?: string;
    baseUrl: string;
    httpClient?: HttpClient;
  }) {
    this.apiKey = params.apiKey;
    this.baseUrl = params.baseUrl.replace(/\/$/, '');
    this.httpClient = params.httpClient ?? new FetchHttpClient();
  }

  isAvailable(): boolean {
    return Boolean(this.apiKey && this.apiKey.trim().length > 0);
  }

  abstract complete(
    prompt: string,
    schema: CanonicalJsonSchema,
    options: CompletionRequestOptions
  ): Promise<CompletionResult>;

  /**
   * Helper to inspect response status and throw typed errors with full context.
   */
  protected async handleHttpResponseErrors(
    res: Response,
    model: string,
    requestId?: string,
    latencyMs = 0
  ): Promise<void> {
    if (res.ok) return;

    let errorBody = '';
    try {
      errorBody = await res.text();
    } catch {
      errorBody = '(failed to read response body)';
    }

    if (res.status === 429) {
      const retryAfterHeader = res.headers.get('retry-after');
      const retryAfterMs = parseRetryAfter(retryAfterHeader) ?? undefined;
      throw new RateLimitError({
        message: `Rate limited by ${this.name}: ${errorBody.slice(0, 300)}`,
        provider: this.name,
        model,
        statusCode: 429,
        latencyMs,
        requestId,
        retryAfterMs,
      });
    }

    if (res.status === 413) {
      throw new PayloadTooLargeError({
        message: `Payload too large for ${this.name}: ${errorBody.slice(0, 300)}`,
        provider: this.name,
        model,
        latencyMs,
        requestId,
      });
    }

    throw new ProviderError({
      message: `HTTP ${res.status} error from ${this.name}: ${errorBody.slice(0, 300)}`,
      provider: this.name,
      model,
      statusCode: res.status,
      latencyMs,
      requestId,
      responseBody: errorBody,
    });
  }

  /**
   * Constructs strict prompt demanding pure JSON without markdown or explanations.
   */
  protected buildSystemPrompt(schema: CanonicalJsonSchema): string {
    return [
      'You are a high-precision structured data extraction engine.',
      'Extract data from the user input that strictly conforms to the following JSON Schema.',
      'CRITICAL RULES:',
      '1. Return ONLY valid, parseable JSON conforming to the schema.',
      '2. Do NOT wrap output in markdown code fences like ```json or ```.',
      '3. Do NOT include any explanations, greetings, comments, or trailing text.',
      '4. If a field cannot be verified or found, use null or default specified in schema.',
      '',
      'TARGET JSON SCHEMA:',
      JSON.stringify(schema, null, 2),
    ].join('\n');
  }
}
