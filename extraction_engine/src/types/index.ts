/**
 * Core type definitions for the Multi-Tier LLM Extraction Engine.
 */

export type ProviderName = 'gemini-flash' | 'groq-llama3' | 'deepseek' | string;

export type CanonicalJsonSchema = Record<string, unknown>;

export interface ExtractionInput {
  html?: string;
  text?: string;
  sourceUrl?: string;
}

export interface ExtractionOptions {
  /** Ordered list of provider adapters to try. Defaults to configured chain. */
  providers?: ProviderName[];
  /** Maximum retry attempts per provider before failover. Defaults to 3. */
  maxRetries?: number;
  /** Maximum safe payload size in bytes per chunk. */
  maxPayloadBytes?: number;
  /** Maximum token limit per chunk sent to LLM. */
  maxInputTokens?: number;
  /** Optional cancellation signal. */
  signal?: AbortSignal;
  /** Maximum timeout per provider request in milliseconds. */
  timeoutMs?: number;
  /** Base delay for exponential backoff in milliseconds. Defaults to 500ms. */
  baseDelayMs?: number;
  /** Maximum delay cap for exponential backoff in milliseconds. Defaults to 10000ms. */
  maxDelayMs?: number;
  /** Number of bounded JSON repair attempts per provider before failing over. Defaults to 1. */
  repairAttempts?: number;
  /** Whether to enable multi-chunk hierarchical consolidation. Defaults to true. */
  enableConsolidation?: boolean;
}

export interface ExtractionTimings extends Record<string, number> {
  totalMs: number;
  normalizationMs: number;
  chunkingMs: number;
  llmMs: number;
  repairMs: number;
  consolidationMs: number;
  validationMs: number;
}

export interface ExtractionMetadata {
  requestId: string;
  provider: string;
  model: string;
  chunksProcessed: number;
  fallbacksUsed: string[];
  truncated: boolean;
  validationPassed: true;
  timings: ExtractionTimings;
  retriesCount?: number;
  repairAttemptsUsed?: number;
  estimatedTokens?: number;
}

export interface ExtractionResult<T = unknown> {
  data: T;
  metadata: ExtractionMetadata;
}

export interface DocumentChunk {
  chunkId: string;
  index: number;
  content: string;
  charCount: number;
  estimatedTokens: number;
  startOffset: number;
  endOffset: number;
}

export interface ProviderFailureContext {
  provider: string;
  model: string;
  statusCode?: number;
  retryCount: number;
  latencyMs: number;
  errorMessage: string;
  requestId?: string;
  timestamp: string;
}

export interface CompletionRequestOptions {
  requestId: string;
  model: string;
  timeoutMs: number;
  signal?: AbortSignal;
  temperature?: number;
}

export interface CompletionResult {
  rawText: string;
  parsedJson?: unknown;
  provider: string;
  model: string;
  latencyMs: number;
  requestId?: string;
}

export interface LLMProviderAdapter {
  readonly name: ProviderName;
  readonly defaultModel: string;
  isAvailable(): boolean;
  complete(
    prompt: string,
    schema: CanonicalJsonSchema,
    options: CompletionRequestOptions
  ): Promise<CompletionResult>;
}

export interface Clock {
  now(): number;
  sleep(ms: number, signal?: AbortSignal): Promise<void>;
}

export interface RandomGenerator {
  random(): number;
}

export interface HttpClient {
  fetch(input: string | URL, init?: RequestInit): Promise<Response>;
}

export interface ExtractionDependencies {
  httpClient?: HttpClient;
  clock?: Clock;
  rng?: RandomGenerator;
  logger?: Logger;
}

export type LogLevel = 'debug' | 'info' | 'warn' | 'error';

export interface LogEntry {
  timestamp: string;
  level: LogLevel;
  requestId?: string;
  provider?: string;
  model?: string;
  event: string;
  latencyMs?: number;
  retryCount?: number;
  chunkIndex?: number;
  error?: string;
  data?: Record<string, unknown>;
}

export interface Logger {
  debug(event: string, meta?: Partial<LogEntry>): void;
  info(event: string, meta?: Partial<LogEntry>): void;
  warn(event: string, meta?: Partial<LogEntry>): void;
  error(event: string, meta?: Partial<LogEntry>): void;
}

// =============================================================================
// Output Record Entities & Strict Provenance Models
// =============================================================================

export interface StartupEntity {
  schemaVersion: '1.0';
  recordType: 'STARTUP';
  source: { name: string; url: string };
  content: {
    entityName: string;
    data: { employeeCount?: number | null };
  };
  collectedAt: string;
}

export interface ProductEntity {
  schemaVersion: '1.0';
  recordType: 'PRODUCT';
  source: { name: string; url: string };
  content: {
    startupName: string;
    pricingModel: 'FREE' | 'FREEMIUM' | 'PAID' | 'ENTERPRISE' | null;
  };
  collectedAt: string;
}

export interface ResearchPaperEntity {
  schemaVersion: '1.0';
  recordType: 'RESEARCH_PAPER';
  content: {
    title: string;
    authors: string[];
    paper_url: string;
    github_url?: string | null;
    github_stars?: number | null;
    published_date: string;
  };
}

export interface JobEntity {
  schemaVersion: '1.0';
  recordType: 'JOB';
  content: {
    company: string;
    date: string;
    is_remote: boolean;
    role_family: string;
  };
}

export type AnyOutputEntity = StartupEntity | ProductEntity | ResearchPaperEntity | JobEntity;

export interface FieldProvenance {
  sourceUrl: string;
  sourceFieldOrSelector: string;
  extractionTimestamp: string;
  confidence: number;
  isDirectSourceData: boolean;
}

export interface RecordAuditProvenance {
  recordId: string;
  recordType: string;
  sourceUrl: string;
  fields: Record<string, FieldProvenance>;
  collectedAt: string;
}

export * from '../entity_resolution/types.js';
