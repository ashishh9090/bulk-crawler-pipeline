# High-Concurrency Bulk Data Acquisition Pipeline (Phase I)

Production-grade, asynchronous bulk crawler architecture in Python 3.11+ capable of scaling from 1,000 records to 500,000+ records purely through infrastructure scaling (worker concurrency, database pooling, distributed queues) without altering core code.

---

## Target Data Categories & Schemas

### 1. Startups (`recordType = "STARTUP"`)
Extracts verified corporate and startup entities from Wikidata Corporate Ontology and official SEC EDGAR directories. Unverified employee counts are strictly stored as `null`.
```json
{
  "schemaVersion": "1.0",
  "recordType": "STARTUP",
  "source": {
    "name": "Wikidata",
    "url": "https://about.google/"
  },
  "content": {
    "entityName": "Google",
    "data": {
      "employeeCount": 187000
    }
  },
  "collectedAt": "2026-09-10T04:39:50.773910+00:00"
}
```

### 2. Products (`recordType = "PRODUCT"`)
Extracts software products, maker/startup names, verified source URLs, and strictly classified pricing models (`FREE`, `FREEMIUM`, `PAID`, `ENTERPRISE`).
```json
{
  "schemaVersion": "1.0",
  "recordType": "PRODUCT",
  "source": {
    "name": "SaaSHub",
    "url": "https://resend.com/"
  },
  "content": {
    "startupName": "Resend",
    "pricingModel": "FREEMIUM"
  },
  "collectedAt": "2026-09-10T04:39:32.596702+00:00"
}
```

### 3. Research Papers (`recordType = "RESEARCH_PAPER"`)
Extracts peer-reviewed AI/ML research papers from the official arXiv Atom XML API. Extracts titles, authors, publication dates, and linked GitHub repository URLs. Fetches live GitHub star counts via the GitHub REST API (or public OpenGraph metadata fallback).
```json
{
  "schemaVersion": "1.0",
  "recordType": "RESEARCH_PAPER",
  "source": {
    "name": "arXiv",
    "url": "https://arxiv.org/abs/2609.10540v1"
  },
  "content": {
    "title": "Programmable World Model",
    "authors": ["Zheng-Hui Huang", "Guixu Lin", "Jiacheng Lin"],
    "paper_url": "https://arxiv.org/abs/2609.10540v1",
    "github_url": "https://github.com/AlayaLab/pwm",
    "github_stars": 56,
    "published_date": "2026-09-09T17:59:32Z"
  },
  "collectedAt": "2026-09-10T04:39:18.398478+00:00"
}
```

---

## Architectural Decisions

```
URL Discovery (Producers)
        ↓
Bounded Async Queue (asyncio.Queue)
        ↓
Crawler Workers (asyncio.Semaphore + Connection Pooling)
        ↓
Parser & Adapter (BeautifulSoup / lxml / JSON)
        ↓
Schema Validation (Pydantic v2)
        ↓
Deduplication Engine (In-memory Set + DB Uniqueness)
        ↓
Async Persistent Storage (SQLite WAL / PostgreSQL)
        ↓
Streaming Exporter (JSON, JSONL, CSV)
```

### 1. Producer-Consumer Queue Decoupling
- **Why**: Eliminates memory blowouts when crawling 500,000+ items. The `BoundedAsyncQueue` applies backpressure to producers if workers are busy.
- **Scaling to 500,000+**: The queue interface is decoupled from `asyncio.Queue`. For multi-process or distributed clusters, swap the in-memory queue with Redis Streams or RabbitMQ without touching worker or parser code.

### 2. Connection Pooling & Bounded Concurrency
- Uses `aiohttp.TCPConnector` configured with `limit=100`, `limit_per_host=5`, and `ttl_dns_cache=300`.
- Workers are bounded by an `asyncio.Semaphore` preventing socket exhaustion (FD limits) on the host machine.
- Playwright is isolated and launched lazily only for targets strictly requiring JavaScript rendering.

### 3. Rate Limiting with `Retry-After` Support
- Implements a domain-aware token bucket / sliding delay rate limiter.
- If a server responds with HTTP 429, the `Retry-After` header is honored across all workers targeting that domain.

### 4. Exponential Backoff with Full Jitter
- Handles transient network failures and HTTP 5xx / 429 with exponential backoff ($factor^{attempt}$) combined with full decorrelated jitter ($0.5 \times delay$ to $1.5 \times delay$) to eliminate thundering herd synchronization.
- Fails fast on terminal HTTP client errors (400, 404).

### 5. Multi-Tier Deduplication
1. **Tier 1 (In-Memory)**: Sub-millisecond $O(1)$ set lookup of SHA-256 fingerprints to filter 99% of repeated tasks before database roundtrips.
2. **Tier 2 (Database Layer)**: SQLite / PostgreSQL unique constraints on `content_hash` guaranteeing transactional idempotency even across multiple worker processes.

### 6. Persistence in SQLite WAL Mode
- Configures `PRAGMA journal_mode=WAL;` (Write-Ahead Logging), `PRAGMA synchronous=NORMAL;`, and `PRAGMA busy_timeout=30000;`.
- WAL mode allows concurrent readers while writes execute, preventing database lock contention under heavy concurrency.

### 7. Streaming Exporters
- Avoids loading all 500,000+ records into RAM. Uses SQLAlchemy's async cursor streaming (`yield_per(1000)`) to pipe records directly to JSON, JSONL, and CSV files in constant memory.

---

## Project Folder Structure

```
bulk_crawler_pipeline/
├── .env                          # Local environment variables
├── .env.example                  # Environment configuration template
├── README.md                     # Documentation and architecture guide
├── requirements.txt              # Core dependencies
├── pyproject.toml                # Project metadata
├── data/                         # SQLite database storage (WAL mode)
│   └── crawler_data.db
├── exports/                      # Streamed export files
│   ├── startup.json / .csv / .jsonl
│   ├── product.json / .csv / .jsonl
│   └── research_paper.json / .csv / .jsonl
├── crawler/
│   ├── __init__.py
│   ├── config.py                 # Pydantic Settings env configuration
│   ├── logging.py                # Structured JSON logging formatter
│   ├── pipeline.py               # Orchestrator & graceful shutdown lifecycle
│   ├── queue.py                  # Bounded async queue interface
│   ├── rate_limiter.py           # Per-domain rate limiter with Retry-After
│   ├── retry.py                  # Exponential backoff with decorrelated jitter
│   ├── url_normalizer.py         # RFC-compliant URL canonicalization & query sorting
│   ├── deduplication.py          # Two-tier deduplication engine
│   ├── checkpoint.py             # Persistent crawl state & pagination resume
│   ├── http_client.py            # aiohttp session pooling & Playwright manager
│   ├── models/
│   │   ├── __init__.py
│   │   ├── schemas.py            # Pydantic v2 models (STARTUP, PRODUCT, RESEARCH_PAPER)
│   │   └── db.py                 # SQLAlchemy async engine & tables
│   ├── adapters/
│   │   ├── __init__.py           # Adapter registry
│   │   ├── base.py               # Abstract BaseAdapter contract
│   │   ├── arxiv_papers.py       # arXiv XML/Atom adapter + GitHub repo locator
│   │   ├── wikidata_startups.py  # Wikidata & SEC EDGAR enterprise adapter
│   │   ├── saashub_products.py   # SaaSHub software & pricing model adapter
│   │   └── github_stars.py       # Live GitHub REST API & metadata extractor
│   └── export/
│       ├── __init__.py
│       └── exporter.py           # Constant-memory streaming cursor exporter
└── tests/
    ├── __init__.py
    ├── conftest.py               # In-memory async database fixtures
    ├── test_url_normalizer.py    # URL normalization unit tests
    ├── test_deduplication.py     # Deduplication atomicity tests
    ├── test_schemas.py           # Pydantic schema validation tests
    ├── test_adapters.py          # Adapter parser tests
    └── test_retry_and_rate_limiter.py # Network resilience tests
```

---

## Setup & Execution Instructions

### 1. Prerequisites
- Python 3.11+ (Python 3.13 tested)
- `uv` or `pip`

### 2. Environment Setup
```bash
cd bulk_crawler_pipeline
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Configuration (`.env`)
Copy `.env.example` to `.env` and tune parameters if desired:
```ini
CONCURRENCY_LIMIT=50
PER_DOMAIN_CONCURRENCY=5
REQUEST_TIMEOUT_SECONDS=30
RATE_LIMIT_DELAY_SECONDS=0.2
MAX_RETRIES=5
BACKOFF_FACTOR=1.5
DATABASE_URL=sqlite+aiosqlite:///data/crawler_data.db
TARGET_RECORDS_PER_TYPE=1000
GITHUB_TOKEN=
LOG_LEVEL=INFO
LOG_FORMAT=json
```

### 4. Running the Tests
```bash
pytest -v tests/
```

### 5. Running the Pipeline

#### Crawl All Categories:
```bash
python -m crawler.pipeline --type all --limit 1000 --export all
```

#### Crawl Specific Category:
```bash
# Research Papers (arXiv + GitHub live stars)
python -m crawler.pipeline --type paper --limit 1000 --export all

# Startups (Wikidata + SEC EDGAR)
python -m crawler.pipeline --type startup --limit 1000 --export all

# Products (SaaSHub + Developer Tools with pricing models)
python -m crawler.pipeline --type product --limit 1000 --export all
```

#### CLI Options:
- `--type`: `all`, `paper`, `startup`, `product` (default: `all`)
- `--limit`: Target number of records per category (default: `1000`)
- `--workers`: Number of concurrent async workers (default: `50`)
- `--export`: Export formats (`json`, `csv`, `jsonl`, `all`)
- `--log-format`: `json` for production monitoring, `console` for human-readable output

---

## Phase II: High-Fidelity Signal Ingestion (`crawler/signals/`)

Production-ready signal ingestion pipeline that monitors exactly 5 configurable AI-news sources and 5 configurable AI-job boards. Discovers, fetches, normalizes, deduplicates, and persists only items verified—or conservatively inferred—to be fresh within the previous 24 hours.

```
Config-Driven Sources (`sources.json`)
                ↓
Discovery Adapters (RSS / Atom / JSON API / HTML Listing)
                ↓
URL Canonicalizer & Politeness Check (Robots.txt + Domain Concurrency)
                ↓
Detail Page Extraction & Noisy Chrome Cleaner (Headings, Markdown, Metadata)
                ↓
Multi-Tier Publication Date Parser (Structured → Visible → Relative → URL)
                ↓
Strict 24-Hour Freshness Gate & Stateful Heuristic
  ├─ [accepted_verified] (Published within 24h of run reference UTC)
  ├─ [accepted_inferred] (Undated, new since last run baseline, top ranking)
  ├─ [rejected_stale]    (Published > 24h ago or future > 15m clock skew)
  └─ [rejected_unknown]  (Missing date without reliable freshness signals)
                ↓
Two-Tier Deduplication & Idempotent Persistence (SQLite WAL / PostgreSQL)
                ↓
Stateful Watermark Advancement & Observability Logs
```

### 1. 10 Configured Sources

All source metadata is isolated in `crawler/signals/sources.json` (no hard-coded crawler logic):

#### 5 AI News Sources:
1. **TechCrunch AI** (`techcrunch_ai`): Official RSS feed (`/category/artificial-intelligence/feed/`) with full-text article extraction and bylines.
2. **VentureBeat AI** (`venturebeat_ai`): RSS feed (`/category/ai/feed/`) with full-article extraction.
3. **The Verge AI** (`the_verge_ai`): Atom feed (`/rss/ai-artificial-intelligence/index.xml`) with article body extraction and byline metadata.
4. **MIT Technology Review AI** (`mit_tech_review_ai`): RSS/Atom feed (`/topic/artificial-intelligence/feed/`) with clean journalism extraction.
5. **Hugging Face Blog** (`huggingface_blog`): Official Atom feed (`/blog/feed.xml`) with community & research posts.

#### 5 AI Job Boards:
6. **AI-Jobs.net** (`ai_jobs_net`): Dedicated AI/ML RSS feed (`/?format=rss`) with compensation, location, and role descriptions.
7. **RemoteOK AI** (`remoteok_ai`): Official JSON API (`/api?tag=ai`) with structured titles, salaries, locations, and tags.
8. **We Work Remotely AI/ML** (`weworkremotely_ai`): Targeted RSS feed with AI keyword filtering.
9. **Hugging Face Jobs** (`huggingface_jobs`): HTML listing scraper (`/jobs`) with CSS selectors and full detail page crawling.
10. **Work at a Startup AI (YC)** (`yc_workatastartup_ai`): HTML listing scraper for YC AI portfolio companies with compensation and role details.

### 2. Configuration & Environment Variables

Tune the ingestion pipeline via `.env` or system environment variables:

| Variable | Default | Description |
|---|---|---|
| `FRESHNESS_WINDOW_HOURS` | `24` | Maximum age in hours for publication freshness |
| `CLOCK_SKEW_TOLERANCE_MINUTES` | `15` | Clock-skew tolerance before rejecting future dates |
| `SIGNAL_USER_AGENT` | `Mozilla/5.0 ... AI-Intelligence-Signal-Bot/2.0` | Polite User-Agent identifying the crawler |
| `SIGNAL_REQUEST_TIMEOUT` | `20.0` | HTTP request timeout in seconds |
| `SIGNAL_MAX_RETRIES` | `3` | Max retries with exponential backoff & jitter |
| `SIGNAL_BACKOFF_FACTOR` | `1.5` | Exponential backoff multiplication factor |
| `HONOR_ROBOTS_TXT` | `true` | Asynchronously checks and respects `robots.txt` per domain |
| `SOURCES_CONFIG_PATH` | `None` (uses `sources.json`) | Path override for external sources configuration file |

### 3. Date Normalization Precedence

Dates are extracted using a strict 4-tier prioritized strategy:
1. **Structured Metadata** (Confidence: `0.88 - 0.98`):
   - JSON-LD Schema: `datePublished` (and optional `dateModified` if configured)
   - Open Graph: `article:published_time`, `og:published_time`
   - Standard HTML Meta Tags: `pubdate`, `timestamp`, `dc.date`, `parsely-pub-date`
   - RSS/Atom Header: `<pubDate>`, `<published>`, `<updated>`, `<dc:date>`
2. **Visible Page Content** (Confidence: `0.80 - 0.85`):
   - `<time datetime="...">` tags and inner text
   - Configured source-specific CSS selectors (`time.wp-block-post-date`, `.byline time`, etc.)
3. **Relative Dates** (Confidence: `0.75 - 0.80`):
   - Phrases: *"2 hours ago"*, *"15 minutes ago"*, *"yesterday"*, *"today"*, *"posted 1 day ago"*
   - Resolved against the run's UTC reference timestamp in the source's configured `timezone`, then normalized to ISO 8601 UTC.
4. **URL and Context Fallbacks** (Confidence: `0.50 - 0.70`):
   - Configured URL date pattern regex (e.g. `/(?P<year>\d{4})/(?P<month>\d{2})/(?P<day>\d{2})/`)
   - Sitemap `lastmod` only when passed as an explicit low-confidence fallback.
- **Ambiguous Numeric Dates**: Disambiguated by configured source `locale` (`en_US` = MM/DD/YYYY, `en_GB` = DD/MM/YYYY).
- **Future Dates**: Dates beyond the `CLOCK_SKEW_TOLERANCE_MINUTES` are rejected.

### 4. Freshness Gate & Missing-Date Heuristic

- **Single UTC Reference Timestamp**: Every run uses a single UTC reference timestamp (`reference_time`) for all freshness comparisons.
- **Explicit Decisions**:
  - `accepted_verified`: Record has a verified date within `[reference_time - 24h, reference_time + clock_skew]`.
  - `accepted_inferred`: Record lacks an explicit publication date but passes the stateful heuristic.
  - `rejected_stale`: Record's publication timestamp is older than 24h or in the future beyond clock skew.
  - `rejected_unknown`: Record lacks date and fails stateful heuristic verification.
- **Stateful "New Since Last Run" Heuristic**:
  - An undated record is accepted **only** if:
    1. A prior successful crawl state exists for the source.
    2. The item is absent from the prior snapshot of observed canonical URLs and content hashes.
    3. The item was first seen after the previous successful crawl.
    4. The item's listing position indicates top recency (`position <= 25`).
  - Constraint: **Never infers an exact `publishedAt` timestamp**; `publishedAt` remains `null` while `firstSeenAt` tracks discovery.
  - Invariant: **Failed or partial crawls NEVER advance the successful-run watermark.**

### 5. Running Locally & Scheduling Ingestion

#### Run All Sources:
```bash
python -m crawler.signals.cli --sources all --limit 20
```

#### Run Specific Sources or Categories:
```bash
# Ingest only AI news
python -m crawler.signals.cli --type news --limit 20

# Ingest only AI job boards
python -m crawler.signals.cli --type job --limit 20

# Ingest specific sources
python -m crawler.signals.cli --sources techcrunch_ai,huggingface_blog,remoteok_ai --limit 10
```

#### Scheduled Execution:
To run on a recurring hourly schedule, use standard cron:
```cron
# Run signal ingestion hourly at minute 0
0 * * * * cd /path/to/bulk_crawler_pipeline && /path/to/.venv/bin/python -m crawler.signals.cli --sources all --log-format json >> /var/log/signals_cron.log 2>&1
```

Overlapping runs for the same source are automatically prevented via in-memory execution locks.

### 6. Known Limitations & Compliance Considerations

- **Respectful Crawling**: The pipeline queries and honors `robots.txt` per domain, limits concurrency per source, applies configurable delays (`rate_limit_delay`), and redacts authorization tokens, cookies, and sensitive headers from structured logs.
- **JavaScript Rendering**: Sources are crawled via HTTP/feed APIs by default. For single-page applications requiring heavy client-side hydration, Playwright can be enabled via `ENABLE_PLAYWRIGHT=true`.
- **Heuristic Integrity**: Inferred freshness is clearly marked with `accepted_inferred` and lower confidence (`0.65`) to prevent false claims of verified timeliness in downstream intelligence analytics.

---

## Phase III: Multi-Tier LLM Extraction Engine (`extraction_engine/`)

Production-grade, highly resilient extraction engine in TypeScript designed to reliably extract structured entities from unstructured, noisy, or malformed web pages and raw text into strict canonical JSON schemas (`STARTUP`, `PRODUCT`, `RESEARCH_PAPER`).

### Architecture Highlights:
- **Multi-Provider Fallback Chain**: Default order `Gemini Flash` → `Groq Llama 3` → `DeepSeek`. Fails over on timeout, 429 rate limit exhaustion, 5xx server errors, or validation rejection.
- **Strict Canonical Schema Enforcement**: Powered by Ajv. Output is strictly validated before being returned.
- **Bounded JSON Repair**: Syntactic healing plus 1 bounded repair prompt with the same provider before failover.
- **Semantic Boundary Chunking**: Splits large documents along headings, paragraphs, lists, and sentences.
- **Payload Safety & 413 Recovery**: Halves chunk size dynamically and retries upon 413 Payload Too Large.
- **Exponential Backoff with Full Jitter**: Respects `Retry-After` header with randomized jitter and abort cancellation.
- **Hierarchical Extraction & Consolidation**: Consolidates and deduplicates partial candidates across multi-chunk documents.
- **Sensitive Data Protection**: Redacting structured logger ensuring API keys and secrets are never logged.

### Quick Start:
```bash
cd extraction_engine
npm install
npm test
npm run build
```

