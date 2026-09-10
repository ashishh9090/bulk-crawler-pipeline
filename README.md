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

