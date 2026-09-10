import { ProviderFailureContext } from '../types/index.js';

export class ExtractionError extends Error {
  constructor(message: string) {
    super(message);
    this.name = this.constructor.name;
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

export class ProviderError extends ExtractionError {
  public readonly provider: string;
  public readonly model: string;
  public readonly statusCode?: number;
  public readonly retryCount: number;
  public readonly latencyMs: number;
  public readonly requestId?: string;
  public readonly responseBody?: string;

  constructor(params: {
    message: string;
    provider: string;
    model: string;
    statusCode?: number;
    retryCount?: number;
    latencyMs?: number;
    requestId?: string;
    responseBody?: string;
  }) {
    super(
      `[${params.provider}/${params.model}] ${params.message}` +
        (params.statusCode ? ` (HTTP ${params.statusCode})` : '')
    );
    this.provider = params.provider;
    this.model = params.model;
    this.statusCode = params.statusCode;
    this.retryCount = params.retryCount ?? 0;
    this.latencyMs = params.latencyMs ?? 0;
    this.requestId = params.requestId;
    this.responseBody = params.responseBody;
  }

  toFailureContext(): ProviderFailureContext {
    return {
      provider: this.provider,
      model: this.model,
      statusCode: this.statusCode,
      retryCount: this.retryCount,
      latencyMs: this.latencyMs,
      errorMessage: this.message,
      requestId: this.requestId,
      timestamp: new Date().toISOString(),
    };
  }
}

export class RateLimitError extends ProviderError {
  public readonly retryAfterMs?: number;

  constructor(params: {
    message: string;
    provider: string;
    model: string;
    statusCode?: number;
    retryCount?: number;
    latencyMs?: number;
    requestId?: string;
    retryAfterMs?: number;
  }) {
    super({
      ...params,
      statusCode: params.statusCode ?? 429,
    });
    this.retryAfterMs = params.retryAfterMs;
  }
}

export class PayloadTooLargeError extends ProviderError {
  constructor(params: {
    message: string;
    provider: string;
    model: string;
    retryCount?: number;
    latencyMs?: number;
    requestId?: string;
  }) {
    super({
      ...params,
      statusCode: 413,
    });
  }
}

export class SchemaValidationError extends ExtractionError {
  public readonly validationErrors: unknown[];
  public readonly invalidData: unknown;
  public readonly provider?: string;
  public readonly model?: string;

  constructor(params: {
    message: string;
    validationErrors: unknown[];
    invalidData: unknown;
    provider?: string;
    model?: string;
  }) {
    super(params.message);
    this.validationErrors = params.validationErrors;
    this.invalidData = params.invalidData;
    this.provider = params.provider;
    this.model = params.model;
  }
}

export class MalformedJsonError extends ExtractionError {
  public readonly rawText: string;
  public readonly provider?: string;
  public readonly model?: string;

  constructor(params: {
    message: string;
    rawText: string;
    provider?: string;
    model?: string;
  }) {
    super(params.message);
    this.rawText = params.rawText;
    this.provider = params.provider;
    this.model = params.model;
  }
}

export class ExtractionAbortedError extends ExtractionError {
  constructor(message = 'Extraction was aborted by signal') {
    super(message);
  }
}

export class AllProvidersExhaustedError extends ExtractionError {
  public readonly chainFailures: ProviderFailureContext[];
  public readonly requestId: string;

  constructor(requestId: string, chainFailures: ProviderFailureContext[]) {
    const summary = chainFailures
      .map(
        (f) =>
          `  - ${f.provider} (${f.model}): ${f.errorMessage}${
            f.statusCode ? ` [HTTP ${f.statusCode}]` : ''
          } (retries: ${f.retryCount})`
      )
      .join('\n');

    super(
      `All providers in fallback chain failed for request ${requestId}:\n${summary}`
    );
    this.requestId = requestId;
    this.chainFailures = chainFailures;
  }
}
