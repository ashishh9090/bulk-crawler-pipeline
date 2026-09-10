# Multi-Tier LLM Extraction Engine (Phase III)

Production-grade, resilient Multi-Tier LLM Extraction Engine in TypeScript that converts noisy, long-form, or partially malformed source content (HTML or plain text) into strictly validated canonical JSON schemas.

---

## Architectural Overview

```
Input Source Content (HTML / Plain Text)
                  ↓
       1. HTML & Content Normalizer
 (Strips scripts, styles, boilerplate, banners; retains headings, tables, metadata)
                  ↓
       2. Semantic Boundary Chunker
 (Sections / Headings → Paragraphs → Lists/Tables → Sentences → Hard Split)
 (Estimates tokens, reserves prompt overhead & generation tokens)
                  ↓
       3. Multi-Provider Fallback Orchestrator
   ┌─────────────────────────────────────────────────────────┐
   │ Priority Chain:                                         │
   │ 1. Gemini Flash (Google REST API)                       │
   │ 2. Groq Llama 3 (Groq OpenAI-compatible API)            │
   │ 3. DeepSeek (DeepSeek API)                              │
   └─────────────────────────────────────────────────────────┘
         ├── 429 Rate Limit → Exponential Backoff + Full Jitter (Retry-After)
         ├── 413 Payload Too Large → Halve Chunk Size & Retry
         ├── Malformed JSON → Syntactic Healing + Bounded LLM Repair Prompt
         ├── Schema Validation Failure → Bounded Repair → Next Provider
         └── Retriable 5xx / 408 Timeout → Backoff Retry → Next Provider
                  ↓
       4. Candidate Consolidation & Merge
 (Deep merges partial chunk records, deduplicates arrays, resolves conflicts)
                  ↓
       5. Strict Ajv Schema Validation
 (Guarantees unvalidated data is NEVER returned)
                  ↓
 Canonical JSON Output + Detailed Execution Metadata
```

---

## Key Features

1. **Multi-Provider Fallback Chain**:
   - Provider adapters isolated behind a uniform `LLMProviderAdapter` interface.
   - Built-in adapters for **Gemini Flash**, **Groq Llama 3**, and **DeepSeek**.
   - Automatic failover on: timeout, rate limit exhaustion, 5xx server errors, unrecoverable malformed output, or schema validation failures.
   - Preserves complete failure context (provider, model, HTTP status, retry count, latency, error message, request ID).

2. **Canonical Schema Enforcement & Bounded Repair**:
   - Validates every response using strict Ajv schema validator with format checking.
   - Includes canonical JSON schemas matching Phase I schemas:
     - `STARTUP` (`StartupCanonicalSchema`)
     - `PRODUCT` (`ProductCanonicalSchema`)
     - `RESEARCH_PAPER` (`ResearchPaperCanonicalSchema`)
   - Fast local heuristic JSON healing (strips markdown fences, extracts objects, auto-closes braces, fixes trailing commas).
   - One bounded prompt-level JSON repair attempt sent to the *same* provider before failing over.
   - Unvalidated data is **never** returned as successful output.

3. **Intelligent Semantic Chunking & 413 Recovery**:
   - Strips noisy HTML (scripts, styles, noscript, svg, navigation, footer, cookie banners, hidden elements) while retaining document structure, headings, tables, lists, and metadata.
   - Safe token budgeting with prompt overhead and generation reservation.
   - Priority-ordered splitting at headings (`#`), paragraphs (`\n\n`), list/table items, sentences, and hard character limits as last resort.
   - Preserves document order and attaches `chunkId`, `index`, `startOffset`, and `endOffset`.
   - **413 Payload Too Large Recovery**: Halves chunk size dynamically, re-chunks, and retries once before failing over.

4. **Rate Limiting & Retries**:
   - Full jitter exponential backoff: `delay = Math.min(maxDelay, baseDelay * 2^attempt) * rng.random()`.
   - Full support for `Retry-After` header (both numeric seconds and RFC 7231 HTTP dates).
   - Only retries transient status codes: `408`, `409`, `413`, `429`, `500`, `502`, `503`, `504`.
   - Strict `AbortSignal` propagation to halt active retries and in-flight requests cleanly.

5. **Hierarchical Extraction & Consolidation**:
   - Oversized documents processed chunk-by-chunk to extract partial structured candidates.
   - Final consolidation pass deep merges records, unions lists (e.g. paper authors), selects higher-information fields, and strictly validates final output.

6. **Observability & Sensitive Data Protection**:
   - Redacting structured JSON logger.
   - Automatic sanitization of API keys (Gemini, Groq, DeepSeek), Bearer tokens, secrets, and passwords.
   - Payload strings safely truncated in logs to avoid data leakage.

---

## Configuration Variables

Environment variables can be specified in `.env` or passed at runtime:

| Variable | Description | Default |
|---|---|---|
| `EXTRACTION_PROVIDER_CHAIN` | Comma-separated provider chain order | `gemini-flash,groq-llama3,deepseek` |
| `GEMINI_API_KEY` | Google Gemini API Key | *(optional)* |
| `GEMINI_MODEL` | Gemini model name | `gemini-1.5-flash` |
| `GEMINI_BASE_URL` | Gemini endpoint URL | `https://generativelanguage.googleapis.com/v1beta` |
| `GROQ_API_KEY` | Groq Cloud API Key | *(optional)* |
| `GROQ_MODEL` | Groq model name | `llama-3.3-70b-versatile` |
| `GROQ_BASE_URL` | Groq API endpoint URL | `https://api.groq.com/openai/v1` |
| `DEEPSEEK_API_KEY` | DeepSeek API Key | *(optional)* |
| `DEEPSEEK_MODEL` | DeepSeek model name | `deepseek-chat` |
| `DEEPSEEK_BASE_URL` | DeepSeek API endpoint URL | `https://api.deepseek.com` |
| `EXTRACTION_MAX_RETRIES` | Max retry attempts per provider | `3` |
| `EXTRACTION_TIMEOUT_MS` | Request timeout per attempt | `30000` (30s) |
| `EXTRACTION_BASE_DELAY_MS` | Base delay for backoff | `500` (500ms) |
| `EXTRACTION_MAX_DELAY_MS` | Maximum backoff delay cap | `10000` (10s) |
| `EXTRACTION_MAX_PAYLOAD_BYTES` | Max payload bytes per chunk | `250000` |
| `EXTRACTION_MAX_INPUT_TOKENS` | Max input tokens per chunk | `12000` |
| `EXTRACTION_REPAIR_ATTEMPTS` | Max bounded repair attempts | `1` |
| `LOG_LEVEL` | Log level (`debug`, `info`, `warn`, `error`) | `info` |

---

## Example Usage

### Programmatic TypeScript API

```typescript
import {
  extract,
  StartupCanonicalSchema,
  ProductCanonicalSchema,
  ResearchPaperCanonicalSchema
} from '@crawler/extraction-engine';

// 1. Extract a Startup record from HTML
const result = await extract({
  input: {
    html: '<html><body><h1>Acme AI</h1><p>Aerospace startup with 120 employees.</p></body></html>',
    sourceUrl: 'https://acme.ai'
  },
  schema: StartupCanonicalSchema,
  options: {
    providers: ['gemini-flash', 'groq-llama3', 'deepseek'],
    maxRetries: 3,
    repairAttempts: 1,
  }
});

console.log('Extracted Data:', result.data);
/*
{
  schemaVersion: "1.0",
  recordType: "STARTUP",
  source: { name: "Web", url: "https://acme.ai" },
  content: {
    entityName: "Acme AI",
    data: { employeeCount: 120 }
  },
  collectedAt: "2026-09-10T12:00:00Z"
}
*/

console.log('Metadata:', result.metadata);
/*
{
  requestId: "a8e92f1b-...",
  provider: "gemini-flash",
  model: "gemini-1.5-flash",
  chunksProcessed: 1,
  fallbacksUsed: [],
  truncated: false,
  validationPassed: true,
  timings: {
    totalMs: 245,
    normalizationMs: 12,
    chunkingMs: 4,
    llmMs: 210,
    repairMs: 0,
    consolidationMs: 0,
    validationMs: 19
  }
}
*/
```

### With Dependency Injection (for unit/integration testing)

```typescript
import { ExtractionEngine } from '@crawler/extraction-engine';

const engine = new ExtractionEngine({
  httpClient: customMockHttpClient,
  clock: customMockClock,
  rng: seededRng,
  logger: customLogger
});

const result = await engine.extract({
  input: { text: 'Some unstructured notes' },
  schema: customJsonSchema,
});
```

---

## Test Suite Execution

To run the complete automated test suite:

```bash
npm test
```

To run with code coverage:

```bash
npm run test:coverage
```

To build production bundle:

```bash
npm run build
```
