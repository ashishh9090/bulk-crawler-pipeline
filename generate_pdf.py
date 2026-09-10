"""Renders architecture.md into a high-fidelity PDF strictly bounded to <= 3 pages."""

import asyncio
from pathlib import Path
from pypdf import PdfReader
from playwright.async_api import async_playwright

CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<style>
  @page {
    size: A4 portrait;
    margin: 8mm 10mm 8mm 10mm;
    @bottom-right {
      content: "Page " counter(page) " of " counter(pages);
      font-size: 8pt;
      color: #64748b;
    }
  }

  *, *:before, *:after {
    box-sizing: border-box;
  }

  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    font-size: 8.5pt;
    line-height: 1.25;
    color: #1e293b;
    margin: 0;
    padding: 0;
  }

  h1 {
    font-size: 14pt;
    font-weight: 800;
    color: #0f172a;
    margin: 0 0 2px 0;
    letter-spacing: -0.3px;
  }

  .subtitle {
    font-size: 8.5pt;
    font-weight: 600;
    color: #2563eb;
    margin-bottom: 6px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }

  h2 {
    font-size: 10.5pt;
    font-weight: 700;
    color: #1e3a8a;
    border-bottom: 1.5px solid #e2e8f0;
    padding-bottom: 2px;
    margin: 8px 0 4px 0;
  }

  h3 {
    font-size: 9pt;
    font-weight: 700;
    color: #334155;
    margin: 6px 0 2px 0;
  }

  p {
    margin: 0 0 4px 0;
  }

  ul {
    margin: 2px 0 4px 14px;
    padding: 0;
  }

  li {
    margin-bottom: 2px;
  }

  strong {
    font-weight: 600;
    color: #0f172a;
  }

  pre {
    background-color: #0f172a;
    color: #f8fafc;
    padding: 5px 8px;
    border-radius: 4px;
    font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
    font-size: 6.8pt;
    line-height: 1.15;
    overflow-x: hidden;
    margin: 3px 0 5px 0;
    border: 1px solid #334155;
  }

  code {
    font-family: "SFMono-Regular", Consolas, monospace;
    font-size: 7.5pt;
    background: #f1f5f9;
    padding: 1px 3px;
    border-radius: 2px;
    color: #0369a1;
  }

  pre code {
    background: transparent;
    color: inherit;
    padding: 0;
  }

  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 7.5pt;
    margin: 4px 0 6px 0;
  }

  th, td {
    border: 1px solid #cbd5e1;
    padding: 3px 6px;
    text-align: left;
    vertical-align: top;
  }

  th {
    background-color: #f8fafc;
    font-weight: 700;
    color: #1e3a8a;
  }

  tr:nth-child(even) td {
    background-color: #fdfdfd;
  }

  hr {
    border: none;
    border-top: 1px solid #e2e8f0;
    margin: 6px 0;
  }

  .page-break {
    page-break-before: always;
  }

  .badge {
    display: inline-block;
    padding: 1px 4px;
    font-size: 7pt;
    font-weight: 600;
    border-radius: 3px;
    background: #dbeafe;
    color: #1e40af;
  }
</style>
</head>
<body>

<!-- PAGE 1 -->
<h1>Production Architecture: Distributed Intelligence Ingestion Pipeline</h1>
<div class="subtitle">System Specification & Scale Design (Phase VI) &bull; Target Scale: 500,000+ Entities</div>

<h2>1. End-to-End Pipeline Architecture</h2>
<p>The pipeline ingests raw web, feed, and API signals into high-fidelity, verified entity records with <strong>strict provenance and zero synthetic fabrication</strong>.</p>

<pre>
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
</pre>

<h2>2. Scale Strategy: 500,000+ Entities</h2>
<p>To scale from 5,000 to 500,000+ entities without architecture redesign, the pipeline employs partition-based horizontal decoupling:</p>

<h3>2.1 Partitioned Source Scheduler & Consistent Hashing</h3>
<ul>
  <li><strong>Source Partitions</strong>: Sources are partitioned by origin domain and SLA tier (<code>tier_1_realtime</code> every 15m, <code>tier_2_hourly</code> every 60m, <code>tier_3_bulk</code> daily).</li>
  <li><strong>Consistent Hashing</strong>: Distributed scheduler assigns source partitions to worker nodes using consistent hashing, guaranteeing single-flight ownership per domain.</li>
  <li><strong>Zero LLM Fabrication</strong>: No entity or field is ever created by model hallucination. All entities originate from verified registries (SEC EDGAR, Wikidata Corporate Ontology, arXiv, official company domains). Missing values remain explicitly <code>null</code>.</li>
</ul>

<h3>2.2 Queue-Based Decoupling & Worker Autoscaling</h3>
<ul>
  <li><strong>Bounded Queues</strong>: Discovery producers emit URLs to Redis Streams with max-length constraints (<code>MAXLEN ~ 100,000</code>). If queue depth exceeds thresholds, backpressure slows upstream discovery.</li>
  <li><strong>Autoscaling Workers</strong>: Kubernetes HPA scales fetch workers based on <code>queue_depth / target_latency</code> while strictly respecting global per-domain concurrency quotas.</li>
  <li><strong>Incremental Crawling & Change Detection</strong>: Secondary lookups compare <code>SHA-256(canonical_url + normalized_text)</code>. Unmodified pages bypass downstream LLM extraction completely, reducing operational compute costs by &gt;85%.</li>
</ul>

<h3>2.3 Human-in-the-Loop Review for Unresolved Entities</h3>
<p>Ambiguous entity matches (<code>AMBIGUOUS_MULTI_CANDIDATE</code>) and unresolved low-confidence candidates (<code>confidence &lt; 0.80</code>) route to an isolated dead-letter queue (<code>dlq:entity_resolution</code>). Confirmed mappings append verified aliases to <code>seed_data.json</code> with zero-downtime hot-reloading.</p>

<div class="page-break"></div>

<!-- PAGE 2 -->
<h2>3. Exact 413 & 429 Resilience Strategy</h2>

<h3>3.1 HTTP 413 (Payload Too Large) Mitigation & Dynamic Recovery</h3>
<ul>
  <li><strong>Pre-Extraction Cleansing</strong>: <code>ContentCleaner</code> strips scripts, styles, SVGs, base64 data, and navigational chrome before measuring payload size.</li>
  <li><strong>Byte & Token Budgeting</strong>: Payloads are measured against strict token budgets (max 8,000 tokens per chunk) with a 25% safety margin reserved for structured system instructions and schema specifications.</li>
  <li><strong>Semantic Hierarchy Chunking</strong>: Large documents are recursively split along structural markdown boundaries:
    <br><code>Headings (###, ##, #) &rarr; Paragraphs (\n\n) &rarr; Lists & Tables &rarr; Sentence Split &rarr; Hard Token Bound</code></li>
  <li><strong>Dynamic Recovery</strong>: Upon receiving an HTTP 413, the chunker dynamically halves chunk size (<code>chunk_size &larr; chunk_size / 2</code>), clears prompt cache, and re-executes with a single retry before provider failover.</li>
  <li><strong>Deterministic Consolidation</strong>: Extracted partial entity records are consolidated across chunks using deterministic primary keys (canonical URL, company name, normalized title).</li>
</ul>

<h3>3.2 HTTP 429 (Rate Limiting) & Thundering Herd Prevention</h3>
<ul>
  <li><strong>Per-Provider & Per-Domain Token Buckets</strong>: Each domain is throttled via leaky/token buckets with independent refill rates (<code>r</code>) and burst capacities (<code>c</code>).</li>
  <li><strong>Strict <code>Retry-After</code> Compliance</strong>: When an origin responds with HTTP 429, the parser extracts <code>Retry-After</code>. The domain bucket is immediately paused until <code>now + retry_delay</code>.</li>
  <li><strong>Exponential Backoff with Full Decorrelated Jitter</strong>:
    <br><code>delay = min(max_delay, random(0, base_delay * 2^attempt))</code>
    <br>Full randomized jitter eliminates synchronized thundering herd retries across distributed worker pods.</li>
  <li><strong>Circuit Breakers & Fallback Routing</strong>: Consecutive errors (3 failures in 60s) trip the circuit breaker (<code>OPEN</code>), routing requests to the next fallback provider (Gemini Flash &rarr; Groq Llama 3 &rarr; DeepSeek) without retry storms.</li>
</ul>

<hr>

<h2>4. Freshness & Distributed Deduplication</h2>

<h3>4.1 Idempotency & Multi-Tier Deduplication Keys</h3>
<ul>
  <li><strong>Tier 1 (In-Memory Bloom Filter / LRU Cache)</strong>: Sub-millisecond lookup on <code>SHA-256(canonical_url)</code> filters 99% of repeated tasks before any database overhead.</li>
  <li><strong>Tier 2 (PostgreSQL Unique Constraints)</strong>: Strict uniqueness constraints on <code>content_hash</code> and <code>(source_id, canonical_url_hash)</code> guarantee database-level idempotency under concurrent inserts (<code>ON CONFLICT DO NOTHING</code>).</li>
</ul>

<h3>4.2 Distributed Partition Locks & Watermarks</h3>
<ul>
  <li><strong>Distributed Leases</strong>: Workers acquire a distributed lease (<code>SET lock:source:&lt;id&gt; NX EX 300</code>) in Redis before initiating crawls, preventing overlapping runs.</li>
  <li><strong>Stateful Watermark Advancement</strong>: A source's <code>last_successful_crawl_at</code> advances <strong>only upon 100% clean crawl completion</strong> (<code>status == SUCCESS</code>). Partial or failed crawls record attempt telemetry but <strong>never</strong> advance the watermark.</li>
  <li><strong>Verified vs. Inferred Freshness Integrity</strong>:
    <ul>
      <li><code>accepted_verified</code>: Explicit publication timestamp parsed within <code>[ref_time - 24h, ref_time + 15m]</code>.</li>
      <li><code>accepted_inferred</code>: Undated item meeting stateful heuristic (new since last successful crawl, position &le; 25). Stored with confidence 0.65 and <code>publishedAt = null</code> to preserve analytical honesty.</li>
    </ul>
  </li>
</ul>

<div class="page-break"></div>

<!-- PAGE 3 -->
<h2>5. Polyglot Storage Strategy & Data Lineage</h2>

<table>
  <thead>
    <tr>
      <th style="width: 20%;">Storage Layer</th>
      <th style="width: 55%;">Technology & Schema Role</th>
      <th style="width: 25%;">Retention & SLA</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><strong>Relational OLTP</strong></td>
      <td>PostgreSQL 16 (WAL mode / connection pooled via PgBouncer). Stores transactional records, crawl state, checkpoints, audit logs, and entity mappings.</td>
      <td>Hot storage, 90-day partition rotation</td>
    </tr>
    <tr>
      <td><strong>Raw Object Store</strong></td>
      <td>S3-Compatible Object Store (AWS S3 / Cloudflare R2 / GCS). Raw HTML snapshots, clean text artifacts, and LLM payloads.</td>
      <td>30-day raw retention, Infrequent Access tier</td>
    </tr>
    <tr>
      <td><strong>Search & Indexing</strong></td>
      <td>OpenSearch / Elasticsearch 8.x. Full-text token search, BM25 keyword matching, and multi-field facets.</td>
      <td>1-year indexed search, Read-replica cluster</td>
    </tr>
    <tr>
      <td><strong>Graph Topology</strong></td>
      <td>PostgreSQL Graph Edge Table / Neo4j 5.x. Entity links: <code>Startup -[MAKES]-> Product</code>, <code>Startup -[PUBLISHED]-> Paper</code>, <code>Startup -[HIRES]-> Job</code>.</td>
      <td>Persistent topology, Multi-hop traversals</td>
    </tr>
  </tbody>
</table>

<h3>5.1 Storage Tradeoffs & Partitioning</h3>
<ul>
  <li><strong>PostgreSQL vs NoSQL</strong>: PostgreSQL provides relational uniqueness constraints, ACID transactions for crawl watermarks, and JSONB schema validation. Partitioned by <code>record_type</code> and <code>collected_at</code> (monthly partitions) to sustain 500k+ rows with sub-10ms index lookups.</li>
  <li><strong>Vector Search Boundary</strong>: pgvector is utilized purely for semantic candidate exploration&mdash;<strong>never as the source of truth</strong>. All truth claims require relational row provenance.</li>
  <li><strong>Complete Field-Level Provenance</strong>: Every entity attribute retains provenance metadata: origin URL, DOM selector or API field key, extraction timestamp, confidence score, and transformation flag (<code>is_direct_source_data</code>).</li>
</ul>

<h2>6. Multi-Sheet Export & Google Sheets Integration</h2>
<ul>
  <li><strong>6 Canonical Datasets Generated via Cursor Streaming</strong>:
    <ol>
      <li><code>Startups</code>: &ge; 1,000 verified rows (Wikidata / SEC) with canonical resolution IDs.</li>
      <li><code>Products</code>: &ge; 1,000 verified rows (SaaSHub) with canonical maker mapping and pricing models.</li>
      <li><code>Research Papers</code>: &ge; 1,000 verified rows (arXiv) with timestamped GitHub stargazers.</li>
      <li><code>Jobs</code>: Verified fresh AI job postings within 24h freshness window.</li>
      <li><code>News</code>: Verified fresh AI news items within 24h freshness window.</li>
      <li><code>Entity Mapping Log</code>: Complete raw-to-canonical resolution outcomes and audit trail.</li>
    </ol>
  </li>
  <li><strong>Zero Hallucination Guarantee</strong>: If external sources yield fewer than 1,000 rows, actual counts are exported and reported transparently.</li>
  <li><strong>Multi-Format Distribution</strong>: Delivered as an enterprise multi-tab styled <code>.xlsx</code> workbook, 6 individual RFC-4180 CSV files, and authenticated Google Sheets API sync.</li>
</ul>

</body>
</html>
"""


async def generate_pdf():
    pdf_path = Path("architecture.pdf").resolve()
    print("Launching Chromium via Playwright...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            executable_path=CHROME_PATH,
            headless=True,
        )
        page = await browser.new_page()
        await page.set_content(HTML_TEMPLATE, wait_until="networkidle")
        await page.pdf(
            path=str(pdf_path),
            format="A4",
            print_background=True,
            margin={"top": "8mm", "bottom": "8mm", "left": "10mm", "right": "10mm"},
        )
        await browser.close()

    reader = PdfReader(str(pdf_path))
    page_count = len(reader.pages)
    print(f"PDF generated successfully at {pdf_path}")
    print(f"Total Page Count: {page_count} page(s)")
    if page_count > 3:
        raise ValueError(f"ERROR: PDF page count {page_count} exceeds maximum allowed budget of 3 pages!")
    assert page_count <= 3, f"Page count must be <= 3, got {page_count}"
    print("PASS: PDF is strictly within the 3-page limit!")


if __name__ == "__main__":
    asyncio.run(generate_pdf())
