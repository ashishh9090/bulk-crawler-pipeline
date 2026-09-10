# Production Architecture: Distributed Intelligence Ingestion Pipeline

**System Specification & Scale Design (Phase VI)**  
*Target Scale: 500,000+ Verified Entities | High Concurrency | Strict Provenance & Zero Fabrication*

---

## 1. End-to-End Pipeline Architecture

The pipeline ingests raw web, feed, and API signals into high-fidelity, verified entity graphs with zero synthetic fabrication.

```
+---------------------------------------------------------------------------------------------------+
| SOURCES: Official APIs (arXiv, SEC, GitHub) | RSS/Atom Feeds (10+ Outlets) | Permitted HTML/Sitemaps |
+---------------------------------------------------------------------------------------------------+
                                                  |
                                                  v
+---------------------------------------------------------------------------------------------------+
| DISCOVERY QUEUE: Distributed Partition Queues (Redis Streams / RabbitMQ) with Domain Backpressure  |
+---------------------------------------------------------------------------------------------------+
                                                  |
                                                  v
+---------------------------------------------------------------------------------------------------+
| ASYNC FETCHERS: aiohttp Worker Pool + Isolated Playwright Headless Browser (Asset & Route Blocked) |
+---------------------------------------------------------------------------------------------------+
                                                  |
                                                  v
+---------------------------------------------------------------------------------------------------+
| CONTENT & DATE VALIDATION: Multi-Tier Date Normalizer + Strict 24h Verified/Inferred Freshness Gate|
+---------------------------------------------------------------------------------------------------+
                                                  |
                                                  v
+---------------------------------------------------------------------------------------------------+
| LLM EXTRACTION ENGINE: Multi-Provider Fallback (Gemini -> Groq -> DeepSeek) + Bounded JSON Repair  |
+---------------------------------------------------------------------------------------------------+
                                                  |
                                                  v
+---------------------------------------------------------------------------------------------------+
| STRICT SCHEMA VALIDATION: Ajv / Pydantic v2 Enforcing STARTUP, PRODUCT, PAPER, and JOB Schemas    |
+---------------------------------------------------------------------------------------------------+
                                                  |
                                                  v
+---------------------------------------------------------------------------------------------------+
| DETERMINISTIC ENTITY RESOLUTION: 5-Tier Matcher (Canonical -> Configured Alias -> Domain -> Tokens)|
+---------------------------------------------------------------------------------------------------+
                                                  |
                                                  v
+---------------------------------------------------------------------------------------------------+
| POLYGLOT STORAGE: PostgreSQL (Transactions) | S3 (Raw Artifacts) | OpenSearch | Neo4j Graph Edges  |
+---------------------------------------------------------------------------------------------------+
                                                  |
                                                  v
+---------------------------------------------------------------------------------------------------+
| EXPORT & CONSUMPTION: 6-Tab Multi-Sheet XLSX Workbook | Streaming CSVs | Google Sheets API Sync   |
+---------------------------------------------------------------------------------------------------+
```

---

## 2. Scale Strategy: 500,000+ Entities

To scale from 5,000 to 500,000+ entities without architecture redesign, the pipeline uses partition-based horizontal decoupling:

### 2.1 Partitioned Source Scheduler & Discovery
- **Source Partitions**: Sources are partitioned by origin domain and SLA tier (`tier_1_realtime` every 15m, `tier_2_hourly` every 60m, `tier_3_bulk` daily).
- **Consistent Hashing**: A distributed scheduler assigns source partitions to worker nodes using consistent hashing, guaranteeing single-flight ownership per domain.
- **Strict Evidence & Zero LLM Fabrication**: No entity or field is ever created by model hallucination. All entities originate from verified registries (SEC EDGAR, Wikidata Corporate Ontology, arXiv, official company domains). Missing values remain explicitly `null`.

### 2.2 Queue-Based Discovery, Fetch, and Extract Decoupling
- **Bounded Queues**: Discovery producers emit URLs to Redis Streams with max-length constraints (`MAXLEN ~ 100,000`). If queue depth exceeds thresholds, backpressure slows upstream discovery.
- **Worker Autoscaling**: Kubernetes HPA scales fetch workers based on `queue_depth / target_latency` while respecting global domain concurrency quotas.
- **Incremental Crawling & Change Detection**: Secondary lookups compare `SHA-256(canonical_url + normalized_text)`. Unmodified pages bypass downstream LLM extraction completely, reducing operational compute costs by >85%.

### 2.3 Human-in-the-Loop Review for Unresolved Entities
- Ambiguous entity matches (`AMBIGUOUS_MULTI_CANDIDATE`) and unresolved low-confidence candidates (`confidence < 0.80`) are written to an isolated dead-letter queue (`dlq:entity_resolution`).
- Data stewards review flagged mappings via an internal triage dashboard. Confirmed mappings append verified aliases to `seed_data.json` with immediate zero-downtime hot-reloading.

---

## 3. Exact 413 & 429 Resilience Strategy

### 3.1 HTTP 413 (Payload Too Large) Mitigation & Recovery
1. **Pre-Extraction Cleansing**: `ContentCleaner` removes scripts, styles, SVGs, base64 data, and navigational chrome before measuring payload size.
2. **Byte & Token Budgeting**: Payloads are measured against strict token budgets (max 8,000 tokens per chunk) with a 25% safety margin reserved for structured system instructions and schema specifications.
3. **Semantic Hierarchy Chunking**: Large documents are recursively split along structural markdown boundaries:
   $$\text{Headings (\#\#\#, \#\#, \#)} \longrightarrow \text{Paragraphs (\textbackslash n\textbackslash n)} \longrightarrow \text{Lists \& Tables} \longrightarrow \text{Sentence Split} \longrightarrow \text{Hard Token Bound}$$
4. **Dynamic Recovery**: Upon receiving an HTTP 413 or payload rejection, the chunker dynamically halves target chunk size ($N_{\text{chunk}} \leftarrow N_{\text{chunk}} / 2$), clears prompt cache, and re-executes with a single retry before failing over to the secondary provider.
5. **Deterministic Consolidation**: Extracted partial entity records are consolidated across chunks using deterministic primary keys (canonical URL, company name, normalized title).

### 3.2 HTTP 429 (Rate Limiting) & Thundering Herd Prevention
- **Per-Provider & Per-Domain Token Buckets**: Each domain is throttled via leaky/token buckets with independent refill rates ($r$) and burst capacities ($c$).
- **Strict `Retry-After` Compliance**: When an origin responds with HTTP 429, the parser extracts `Retry-After` (integer seconds or HTTP-date). The domain bucket is immediately paused until $t_{\text{now}} + \Delta t_{\text{retry}}$.
- **Exponential Backoff with Full Decorrelated Jitter**:
  $$t_{\text{sleep}} = \min\left(t_{\text{max}}, \; \text{random}(0, \; t_{\text{base}} \times 2^{\text{attempt}})\right)$$
  Full randomized jitter prevents synchronized thundering herd retries across distributed worker pods.
- **Circuit Breakers & Fallback Routing**: Consecutive errors (3 failures in 60s) trip the provider circuit breaker (`OPEN`), routing requests to the next fallback provider (Gemini Flash $\rightarrow$ Groq Llama 3 $\rightarrow$ DeepSeek) without retry storms.

---

## 4. Freshness & Distributed Deduplication

### 4.1 Idempotency & Multi-Tier Deduplication Keys
1. **Tier 1 (In-Memory Bloom Filter / LRU Cache)**: Sub-millisecond lookup on `SHA-256(canonical_url)` filters 99% of repeated tasks before any database overhead.
2. **Tier 2 (PostgreSQL Unique Constraints)**: Strict uniqueness constraints on `content_hash` and `(source_id, canonical_url_hash)` guarantee database-level idempotency under concurrent inserts (`ON CONFLICT DO NOTHING`).

### 4.2 Distributed Partition Locks & Watermarks
- **Distributed Leases**: Workers acquire a distributed lease (`SET lock:source:<id> NX EX 300`) in Redis before initiating crawls, preventing overlapping crawls.
- **Stateful Watermark Advancement**: A source's `last_successful_crawl_at` advances **only upon 100% clean crawl completion** (`status == SUCCESS`). Partial or failed crawls record attempt telemetry but **never** advance the watermark.
- **Verified vs. Inferred Freshness Integrity**:
  - `accepted_verified`: Explicit publication timestamp parsed within $[t_{\text{ref}} - 24\text{h}, t_{\text{ref}} + 15\text{m}]$.
  - `accepted_inferred`: Undated item meeting stateful heuristic (new since last successful crawl, position $\le 25$). Marked with confidence $0.65$ and `publishedAt = null` to maintain analytical honesty.

---

## 5. Storage Strategy & Data Lineage

```
+-------------------+---------------------------------------------------------+-------------------------+
| Storage Layer     | Technology & Schema Role                                | Retention & SLA         |
+-------------------+---------------------------------------------------------+-------------------------+
| Relational OLTP   | PostgreSQL 16 (WAL mode / connection pooled via PgBouncer)| Hot storage, 90-day     |
|                   | Records, crawl state, checkpoints, audit logs, mappings  | partition rotation      |
+-------------------+---------------------------------------------------------+-------------------------+
| Raw Snapshot Store| S3-Compatible Object Store (AWS S3 / Cloudflare R2 / GCS)| 30-day raw retention    |
|                   | Raw HTML, clean text snapshots, and LLM payloads         | Infrequent Access tier  |
+-------------------+---------------------------------------------------------+-------------------------+
| Search & Indexing | OpenSearch / Elasticsearch 8.x                          | 1-year indexed search   |
|                   | Full-text token search, BM25 keyword matching, facets   | Read-replica cluster    |
+-------------------+---------------------------------------------------------+-------------------------+
| Graph / Relations | PostgreSQL Graph Edge Table / Neo4j 5.x                 | Persistent topology     |
|                   | Entity links: Startup -[MAKES]-> Product                | Multi-hop traversals    |
|                   | Startup -[PUBLISHED]-> Paper, Startup -[HIRES]-> Job     |                         |
+-------------------+---------------------------------------------------------+-------------------------+
```

### 5.1 Storage Tradeoffs & Partitioning
- **PostgreSQL vs NoSQL**: PostgreSQL provides strict relational uniqueness constraints, ACID transactions for crawl watermarks, and JSONB schema validation. Partitioned by `record_type` and `collected_at` (monthly partitions) to sustain 500k+ rows with sub-10ms index lookups.
- **Vector Search Boundary**: pgvector is utilized purely for semantic candidate exploration—**never as the source of truth**. All truth claims require relational row provenance.
- **Complete Audit Trail**: Every entity attribute retains provenance metadata: origin URL, DOM selector or API field key, extraction timestamp, confidence score, and transformation flag (`is_direct_source_data`).

---

## 6. Multi-Sheet Export & Google Sheets Integration

- **6 Canonical Datasets**: Generated in constant memory via cursor streaming:
  1. `Startups`: $\ge 1,000$ verified rows (Wikidata / SEC) with canonical resolution IDs.
  2. `Products`: $\ge 1,000$ verified rows (SaaSHub) with canonical maker mapping and pricing models.
  3. `Research Papers`: $\ge 1,000$ verified rows (arXiv) with timestamped GitHub stargazers.
  4. `Jobs`: Verified fresh AI job postings within 24h freshness window.
  5. `News`: Verified fresh AI news items within 24h freshness window.
  6. `Entity Mapping Log`: Complete raw-to-canonical resolution outcomes and audit trail.
- **Zero Hallucination Guarantee**: If external sources yield fewer than 1,000 rows, actual counts are exported and reported transparently.
- **Multi-Format Distribution**: Delivered as an enterprise multi-tab styled `.xlsx` workbook, 6 individual RFC-4180 CSV files, and authenticated Google Sheets API sync.
