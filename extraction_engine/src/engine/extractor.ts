import { randomUUID } from 'node:crypto';
import {
  CanonicalJsonSchema,
  Clock,
  DocumentChunk,
  ExtractionDependencies,
  ExtractionInput,
  ExtractionMetadata,
  ExtractionOptions,
  ExtractionResult,
  ExtractionTimings,
  HttpClient,
  LLMProviderAdapter,
  Logger,
  ProviderFailureContext,
  RandomGenerator,
} from '../types/index.js';
import { defaultConfig, loadConfig } from '../config/index.js';
import {
  AllProvidersExhaustedError,
  ExtractionAbortedError,
  ExtractionError,
  MalformedJsonError,
  PayloadTooLargeError,
  ProviderError,
  RateLimitError,
  SchemaValidationError,
} from '../utils/errors.js';
import { defaultLogger } from '../utils/logger.js';
import {
  DefaultClock,
  DefaultRandomGenerator,
  calculateBackoffDelay,
  isRetriableStatusCode,
} from '../utils/backoff.js';
import { buildRepairPrompt, parseJsonSafely } from '../utils/json_repair.js';
import { normalizeHtml } from '../normalizer/html.js';
import { chunkDocument } from '../chunker/semantic.js';
import { calculateSafeChunkLimit } from '../chunker/token_estimator.js';
import { assertValidSchema, validateSchema } from '../schemas/validator.js';
import { ProviderRegistry } from '../providers/factory.js';
import { consolidateCandidates } from './consolidator.js';

export interface ExtractServiceParams {
  input: ExtractionInput;
  schema: CanonicalJsonSchema;
  options?: ExtractionOptions;
}

export class ExtractionEngine {
  private registry: ProviderRegistry;
  private clock: Clock;
  private rng: RandomGenerator;
  private logger: Logger;
  private httpClient?: HttpClient;

  constructor(dependencies: ExtractionDependencies = {}) {
    this.httpClient = dependencies.httpClient;
    this.clock = dependencies.clock ?? new DefaultClock();
    this.rng = dependencies.rng ?? new DefaultRandomGenerator();
    this.logger = dependencies.logger ?? defaultLogger;
    this.registry = new ProviderRegistry(defaultConfig, this.httpClient);
  }

  registerProvider(adapter: LLMProviderAdapter): void {
    this.registry.register(adapter);
  }

  async extract<T = unknown>(params: ExtractServiceParams): Promise<ExtractionResult<T>> {
    const startTime = this.clock.now();
    const requestId = randomUUID();
    const timings: ExtractionTimings = {
      totalMs: 0,
      normalizationMs: 0,
      chunkingMs: 0,
      llmMs: 0,
      repairMs: 0,
      consolidationMs: 0,
      validationMs: 0,
    };

    this.logger.info('Extraction request started', { requestId });

    // Check cancellation before starting
    if (params.options?.signal?.aborted) {
      throw new ExtractionAbortedError();
    }

    // 1. Normalization phase
    const normStart = this.clock.now();
    let textContent = '';
    if (params.input.html) {
      const normResult = normalizeHtml(params.input.html);
      textContent = normResult.normalizedText;
    } else if (params.input.text) {
      textContent = params.input.text.trim();
    } else {
      throw new ExtractionError('Extraction input must provide either html or text');
    }

    if (!textContent) {
      throw new ExtractionError('Normalized text content is empty; cannot perform extraction');
    }

    timings.normalizationMs = this.clock.now() - normStart;

    // 2. Initial Chunking phase
    const chunkStart = this.clock.now();
    const config = loadConfig();
    const maxInputTokens =
      params.options?.maxInputTokens ?? config.maxInputTokens;
    const maxPayloadBytes =
      params.options?.maxPayloadBytes ?? config.maxPayloadBytes;

    const { safeChunkTokens } = calculateSafeChunkLimit(maxInputTokens);
    let chunkResult = chunkDocument(textContent, {
      maxTokensPerChunk: safeChunkTokens,
      maxCharsPerChunk: maxPayloadBytes,
    });

    timings.chunkingMs = this.clock.now() - chunkStart;

    if (chunkResult.truncated) {
      this.logger.warn('Document was truncated during semantic chunking', {
        requestId,
        data: {
          omittedChars: chunkResult.omittedChars,
          omittedRange: chunkResult.omittedRange,
        },
      });
    }

    // 3. Fallback chain resolution
    const providerChain = this.registry.resolveChain(
      params.options?.providers,
      config.providerChain
    );

    if (providerChain.length === 0) {
      throw new ExtractionError('No LLM providers available or configured');
    }

    const fallbacksUsed: string[] = [];
    const chainFailures: ProviderFailureContext[] = [];
    let successfulResult: T | null = null;
    let successfulProvider = '';
    let successfulModel = '';
    let repairAttemptsUsed = 0;
    let totalRetries = 0;

    // Iterate through provider fallback chain
    for (let pIdx = 0; pIdx < providerChain.length; pIdx++) {
      const provider = providerChain[pIdx]!;
      const model = provider.defaultModel;

      this.logger.info(`Attempting extraction with provider ${provider.name}`, {
        requestId,
        provider: provider.name,
        model,
      });

      try {
        const extractionOutcome = await this.extractWithProvider<T>({
          provider,
          chunks: chunkResult.chunks,
          schema: params.schema,
          options: params.options,
          requestId,
          timings,
          on413PayloadTooLarge: async (offendingChunk) => {
            // 413 Payload Too Large recovery: reduce chunk size by 50%
            this.logger.warn('413 Payload Too Large encountered; reducing chunk size and re-chunking', {
              requestId,
              provider: provider.name,
              chunkIndex: offendingChunk.index,
            });
            const reducedChunkResult = chunkDocument(offendingChunk.content, {
              maxTokensPerChunk: Math.floor(safeChunkTokens / 2),
              maxCharsPerChunk: Math.floor(maxPayloadBytes / 2),
            });
            return reducedChunkResult.chunks;
          },
        });

        successfulResult = extractionOutcome.data;
        successfulProvider = provider.name;
        successfulModel = model;
        repairAttemptsUsed = extractionOutcome.repairAttemptsUsed;
        totalRetries += extractionOutcome.retriesCount;
        break; // Successfully extracted!
      } catch (err: unknown) {
        const failureContext =
          err instanceof ProviderError
            ? err.toFailureContext()
            : {
                provider: provider.name,
                model,
                retryCount: 0,
                latencyMs: 0,
                errorMessage: err instanceof Error ? err.message : String(err),
                requestId,
                timestamp: new Date().toISOString(),
              };

        chainFailures.push(failureContext);
        fallbacksUsed.push(provider.name);

        this.logger.warn(`Provider ${provider.name} failed; triggering fallback`, {
          requestId,
          provider: provider.name,
          error: failureContext.errorMessage,
        });
      }
    }

    if (!successfulResult) {
      throw new AllProvidersExhaustedError(requestId, chainFailures);
    }

    timings.totalMs = this.clock.now() - startTime;

    const metadata: ExtractionMetadata = {
      requestId,
      provider: successfulProvider,
      model: successfulModel,
      chunksProcessed: chunkResult.chunks.length,
      fallbacksUsed,
      truncated: chunkResult.truncated,
      validationPassed: true,
      timings,
      retriesCount: totalRetries,
      repairAttemptsUsed,
    };

    return {
      data: successfulResult,
      metadata,
    };
  }

  /**
   * Executes extraction across all chunks using a single provider adapter,
   * applying retries, backoff, 413 reduction, bounded repair, and candidate consolidation.
   */
  private async extractWithProvider<T>(params: {
    provider: LLMProviderAdapter;
    chunks: DocumentChunk[];
    schema: CanonicalJsonSchema;
    options?: ExtractionOptions;
    requestId: string;
    timings: ExtractionTimings;
    on413PayloadTooLarge: (chunk: DocumentChunk) => Promise<DocumentChunk[]>;
  }): Promise<{
    data: T;
    repairAttemptsUsed: number;
    retriesCount: number;
  }> {
    const { provider, schema, options, requestId, timings } = params;
    const maxRetries = options?.maxRetries ?? defaultConfig.defaultMaxRetries;
    const timeoutMs = options?.timeoutMs ?? defaultConfig.defaultTimeoutMs;
    const baseDelayMs = options?.baseDelayMs ?? defaultConfig.baseDelayMs;
    const maxDelayMs = options?.maxDelayMs ?? defaultConfig.maxDelayMs;
    const repairAttemptsAllowed =
      options?.repairAttempts ?? defaultConfig.repairAttempts;

    const partialCandidates: unknown[] = [];
    let repairAttemptsUsed = 0;
    let totalRetries = 0;

    let chunkQueue = [...params.chunks];

    for (let cIdx = 0; cIdx < chunkQueue.length; cIdx++) {
      const chunk = chunkQueue[cIdx]!;
      let candidate: unknown = null;
      let attempt = 0;
      let recoveredFrom413 = false;

      while (attempt <= maxRetries) {
        if (options?.signal?.aborted) {
          throw new ExtractionAbortedError();
        }

        const llmStart = this.clock.now();
        try {
          const completion = await provider.complete(chunk.content, schema, {
            requestId,
            model: provider.defaultModel,
            timeoutMs,
            signal: options?.signal,
          });

          timings.llmMs += this.clock.now() - llmStart;

          let parsed: unknown = completion.parsedJson;
          let parseError: string | null = null;
          if (!parsed) {
            try {
              parsed = parseJsonSafely(
                completion.rawText,
                provider.name,
                provider.defaultModel
              );
            } catch (pErr) {
              parseError = pErr instanceof Error ? pErr.message : String(pErr);
            }
          }

          // Validate candidate against schema if parsing succeeded
          let validation = parsed ? validateSchema(schema, parsed) : null;
          if (validation && validation.valid) {
            candidate = validation.data;
            break; // Chunk succeeded
          }

          // Bounded JSON Repair attempt (triggered by either parse error or schema failure)
          if (repairAttemptsUsed < repairAttemptsAllowed) {
            repairAttemptsUsed++;
            const errorDesc =
              parseError ||
              validation?.formattedError ||
              'Model returned invalid JSON format';

            this.logger.info(
              `Attempting bounded JSON repair for chunk ${chunk.index}`,
              {
                requestId,
                provider: provider.name,
                data: { error: errorDesc },
              }
            );

            const repairStart = this.clock.now();
            const repairPrompt = buildRepairPrompt({
              brokenText: completion.rawText,
              validationError: errorDesc,
              schema,
            });

            const repairCompletion = await provider.complete(repairPrompt, schema, {
              requestId,
              model: provider.defaultModel,
              timeoutMs,
              signal: options?.signal,
            });
            timings.repairMs += this.clock.now() - repairStart;

            try {
              const healedParsed =
                repairCompletion.parsedJson ||
                parseJsonSafely(
                  repairCompletion.rawText,
                  provider.name,
                  provider.defaultModel
                );
              const secondVal = validateSchema(schema, healedParsed);
              if (secondVal.valid) {
                candidate = secondVal.data;
                break; // Repaired successfully
              }
            } catch {
              // Repair attempt failed to parse valid JSON
            }
          }

          // If still invalid after repair attempts exhausted, throw appropriate typed error
          if (parseError) {
            throw new MalformedJsonError({
              message: parseError,
              rawText: completion.rawText,
              provider: provider.name,
              model: provider.defaultModel,
            });
          }

          throw new SchemaValidationError({
            message: `Chunk validation failed: ${validation?.formattedError}`,
            validationErrors: validation?.errors || [],
            invalidData: parsed,
            provider: provider.name,
            model: provider.defaultModel,
          });
        } catch (err: unknown) {
          // Check for 413 Payload Too Large chunk recovery
          if (err instanceof PayloadTooLargeError && !recoveredFrom413) {
            recoveredFrom413 = true;
            const smallerChunks = await params.on413PayloadTooLarge(chunk);
            if (smallerChunks.length > 1) {
              // Replace current chunk with smaller sub-chunks
              chunkQueue.splice(cIdx, 1, ...smallerChunks);
              cIdx--; // Re-evaluate at current index
              break;
            }
          }

          // Check if error is retriable
          const isRetriable =
            err instanceof RateLimitError ||
            (err instanceof ProviderError &&
              isRetriableStatusCode(err.statusCode));

          if (!isRetriable || attempt >= maxRetries) {
            throw err;
          }

          attempt++;
          totalRetries++;

          const retryAfterMs =
            err instanceof RateLimitError ? err.retryAfterMs : null;
          const delay = calculateBackoffDelay({
            attempt,
            baseDelayMs,
            maxDelayMs,
            retryAfterMs,
            rng: this.rng,
          });

          this.logger.warn(`Retrying request after error in ${delay}ms`, {
            requestId,
            provider: provider.name,
            retryCount: attempt,
            error: err instanceof Error ? err.message : String(err),
          });

          await this.clock.sleep(delay, options?.signal);
        }
      }

      if (candidate) {
        partialCandidates.push(candidate);
      }
    }

    // Consolidation phase for multi-chunk documents
    const consolidStart = this.clock.now();
    let finalData: T;
    if (partialCandidates.length === 1) {
      finalData = assertValidSchema<T>(
        schema,
        partialCandidates[0],
        provider.name,
        provider.defaultModel
      );
    } else {
      finalData = consolidateCandidates<T>(partialCandidates, schema);
    }
    timings.consolidationMs += this.clock.now() - consolidStart;

    return {
      data: finalData,
      repairAttemptsUsed,
      retriesCount: totalRetries,
    };
  }
}

/**
 * Top-level convenience service function.
 */
export async function extract<T = unknown>(
  params: ExtractServiceParams,
  dependencies?: ExtractionDependencies
): Promise<ExtractionResult<T>> {
  const engine = new ExtractionEngine(dependencies);
  return engine.extract<T>(params);
}
