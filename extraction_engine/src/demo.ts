import {
  CanonicalSchemas,
  ExtractionEngine,
  normalizeHtml,
  chunkDocument,
  RateLimitError,
} from './index.js';
import {
  CompletionResult,
  LLMProviderAdapter,
} from './types/index.js';

// Pretty color helpers for ANSI console output
const colors = {
  reset: '\x1b[0m',
  bold: '\x1b[1m',
  dim: '\x1b[2m',
  green: '\x1b[32m',
  cyan: '\x1b[36m',
  yellow: '\x1b[33m',
  red: '\x1b[31m',
  magenta: '\x1b[35m',
  blue: '\x1b[34m',
};

function banner(title: string) {
  console.log('\n' + colors.bold + colors.cyan + '='.repeat(70) + colors.reset);
  console.log(colors.bold + colors.cyan + `  🚀 ${title}` + colors.reset);
  console.log(colors.bold + colors.cyan + '='.repeat(70) + colors.reset + '\n');
}

function subhead(title: string) {
  console.log(colors.bold + colors.yellow + `\n▶ ${title}` + colors.reset);
}

async function runDemo() {
  banner('PHASE III: MULTI-TIER LLM EXTRACTION ENGINE DEMO');

  // ============================================================================
  // SCENARIO 1: Raw Noisy HTML Extraction into Canonical STARTUP Record
  // ============================================================================
  subhead('SCENARIO 1: Noisy HTML Extraction (Cookie banners, scripts, navigation, table)');
  const messyHtml = `
    <!DOCTYPE html>
    <html lang="en">
      <head>
        <title>Stripe, Inc. - Corporate Directory & Metrics</title>
        <meta name="description" content="Financial infrastructure platform for the internet.">
        <script>window.__TRACKER_DATA__ = { session: "xyz123", ping: true };</script>
        <style>.cookie-banner { background: #000; color: #fff; }</style>
      </head>
      <body>
        <nav>
          <a href="/">Home</a> | <a href="/pricing">Pricing</a> | <a href="/careers">Jobs</a>
        </nav>
        <div id="consent-modal" class="cookie-banner">
          This site uses cookies. <button>Accept All</button>
        </div>
        <header>
          <h1>Stripe, Inc.</h1>
          <p class="subtitle">Global economic infrastructure</p>
        </header>
        <main>
          <section id="details">
            <h2>Company Overview</h2>
            <p>Stripe is an Irish-American multinational financial services and software company.</p>
            <div style="display:none">Hidden internal crawler token 0x992837</div>
            <table class="metrics-table">
              <tr><th>Metric</th><th>Value</th></tr>
              <tr><td>Founded</td><td>2010</td></tr>
              <tr><td>Global Headcount</td><td>8,200 verified employees</td></tr>
              <tr><td>Headquarters</td><td>San Francisco, CA & Dublin, Ireland</td></tr>
            </table>
          </section>
        </main>
        <footer>
          <p>© 2026 Stripe, Inc. All rights reserved. <a href="/privacy">Privacy Notice</a></p>
        </footer>
      </body>
    </html>
  `;

  console.log(colors.dim + 'Original Raw HTML Size:' + colors.reset, messyHtml.length, 'bytes');
  const normalized = normalizeHtml(messyHtml);
  console.log(colors.dim + 'Normalized Clean Text Size:' + colors.reset, normalized.normalizedLength, 'bytes');
  console.log(colors.dim + '--- Normalized Document Preview ---' + colors.reset);
  console.log(colors.dim + normalized.normalizedText.split('\n').slice(0, 8).join('\n') + '\n...' + colors.reset);

  const startupRecord = {
    schemaVersion: '1.0',
    recordType: 'STARTUP',
    source: {
      name: 'Stripe Corporate Directory',
      url: 'https://stripe.com/about',
    },
    content: {
      entityName: 'Stripe, Inc.',
      data: {
        employeeCount: 8200,
      },
    },
    collectedAt: new Date().toISOString(),
  };

  const startupMockAdapter: LLMProviderAdapter = {
    name: 'gemini-flash',
    defaultModel: 'gemini-1.5-flash',
    isAvailable: () => true,
    async complete(): Promise<CompletionResult> {
      await new Promise((r) => setTimeout(r, 150));
      return {
        rawText: JSON.stringify(startupRecord),
        parsedJson: startupRecord,
        provider: 'gemini-flash',
        model: 'gemini-1.5-flash',
        latencyMs: 145,
      };
    },
  };

  const engine1 = new ExtractionEngine();
  engine1.registerProvider(startupMockAdapter);

  const res1 = await engine1.extract({
    input: { html: messyHtml, sourceUrl: 'https://stripe.com/about' },
    schema: CanonicalSchemas.STARTUP,
    options: { providers: ['gemini-flash'] },
  });

  console.log(colors.green + '✔ Extraction Successful!' + colors.reset);
  console.log(colors.bold + 'Canonical STARTUP Payload:' + colors.reset);
  console.log(JSON.stringify(res1.data, null, 2));
  console.log(colors.bold + 'Metadata & Timings:' + colors.reset);
  console.log(JSON.stringify(res1.metadata, null, 2));

  // ============================================================================
  // SCENARIO 2: Multi-Tier Fallback Chain with Rate Limit, Timeout & Bounded Repair
  // ============================================================================
  subhead('SCENARIO 2: Multi-Tier Fallback Chain (Gemini 429 → Groq Repair → Success)');
  console.log(colors.dim + 'Simulating chain: Tier 1 (gemini-flash) ──[429 RateLimit]──> Tier 2 (groq-llama3) ──[Malformed JSON Repair]──> Valid Output' + colors.reset);

  let geminiAttempts = 0;
  const simulatedGemini: LLMProviderAdapter = {
    name: 'gemini-flash',
    defaultModel: 'gemini-1.5-flash',
    isAvailable: () => true,
    async complete(): Promise<CompletionResult> {
      geminiAttempts++;
      await new Promise((r) => setTimeout(r, 60));
      // Simulating persistent 429 quota exhaustion
      throw new RateLimitError({
        message: 'Resource exhausted: rate limit exceeded for model gemini-1.5-flash',
        provider: 'gemini-flash',
        model: 'gemini-1.5-flash',
        retryAfterMs: 80,
      });
    },
  };

  let groqCalls = 0;
  const validProductRecord = {
    schemaVersion: '1.0',
    recordType: 'PRODUCT',
    source: {
      name: 'Developer Tools Index',
      url: 'https://resend.com',
    },
    content: {
      startupName: 'Resend',
      pricingModel: 'FREEMIUM',
    },
    collectedAt: new Date().toISOString(),
  };

  const simulatedGroq: LLMProviderAdapter = {
    name: 'groq-llama3',
    defaultModel: 'llama-3.3-70b-versatile',
    isAvailable: () => true,
    async complete(_prompt): Promise<CompletionResult> {
      groqCalls++;
      await new Promise((r) => setTimeout(r, 110));

      if (groqCalls === 1) {
        // First Groq response returns broken JSON with conversational intro and unquoted keys
        console.log(colors.yellow + '   [Groq] Returned malformed JSON with markdown fences & unquoted syntax...' + colors.reset);
        return {
          rawText: 'Here is your result:\n```json\n{ startupName: "Resend", pricingModel: "FREEMIUM"\n',
          provider: 'groq-llama3',
          model: 'llama-3.3-70b-versatile',
          latencyMs: 110,
        };
      }

      // Repair prompt received! Return strictly conforming JSON
      console.log(colors.cyan + '   [Groq] Received bounded JSON repair prompt with schema error. Correcting...' + colors.reset);
      return {
        rawText: JSON.stringify(validProductRecord),
        parsedJson: validProductRecord,
        provider: 'groq-llama3',
        model: 'llama-3.3-70b-versatile',
        latencyMs: 95,
      };
    },
  };

  const engine2 = new ExtractionEngine();
  engine2.registerProvider(simulatedGemini);
  engine2.registerProvider(simulatedGroq);

  const res2 = await engine2.extract({
    input: {
      text: 'Resend is the email API for developers. Generous free tier up to 3,000 emails/month, scaling to paid tiers (FREEMIUM).',
      sourceUrl: 'https://resend.com',
    },
    schema: CanonicalSchemas.PRODUCT,
    options: {
      providers: ['gemini-flash', 'groq-llama3'],
      maxRetries: 1,
      repairAttempts: 1,
      baseDelayMs: 50,
      maxDelayMs: 200,
    },
  });

  console.log(colors.green + '✔ Fallback & Repair Succeeded!' + colors.reset);
  console.log(colors.bold + 'Canonical PRODUCT Payload:' + colors.reset);
  console.log(JSON.stringify(res2.data, null, 2));
  console.log(colors.bold + 'Execution Metadata:' + colors.reset);
  console.log(JSON.stringify(res2.metadata, null, 2));

  // ============================================================================
  // SCENARIO 3: Semantic Chunking & Multi-Chunk Hierarchical Consolidation
  // ============================================================================
  subhead('SCENARIO 3: Semantic Chunking & Multi-Chunk Consolidation (Research Paper)');

  const longResearchDocument = `
    # Programmable World Model for Autonomous Agents

    ## Abstract
    We introduce the Programmable World Model (PWM), a unified neuro-symbolic framework for autonomous simulation.

    ## Authors and Affiliations
    The research was led by Zheng-Hui Huang and Guixu Lin from the Alaya Laboratory, in collaboration with Jiacheng Lin.

    ## Repository and Code Release
    The official source code has been open-sourced at https://github.com/AlayaLab/pwm with 142 GitHub stargazers.

    ## Publication Details
    Presented at the Global AI Systems Conference. Published date: 2026-09-09T17:59:32Z. Official paper URL: https://arxiv.org/abs/2609.10540v1.
  `;

  const chunkingResult = chunkDocument(longResearchDocument, {
    maxCharsPerChunk: 180, // Force split into semantic units
  });

  console.log(colors.dim + `Document split into ${chunkingResult.chunks.length} semantic chunks along section boundaries:` + colors.reset);
  for (const c of chunkingResult.chunks) {
    console.log(colors.dim + `  - [${c.chunkId}] offset ${c.startOffset}..${c.endOffset} (${c.charCount} chars, ~${c.estimatedTokens} tokens): "${c.content.slice(0, 45).replace(/\n/g, ' ')}..."` + colors.reset);
  }

  // Simulated provider that extracts partial candidates from each chunk
  const partialPaperAdapter: LLMProviderAdapter = {
    name: 'gemini-flash',
    defaultModel: 'gemini-1.5-flash',
    isAvailable: () => true,
    async complete(prompt): Promise<CompletionResult> {
      await new Promise((r) => setTimeout(r, 40));

      if (prompt.includes('Authors')) {
        const part = {
          schemaVersion: '1.0',
          recordType: 'RESEARCH_PAPER',
          source: { name: 'arXiv', url: 'https://arxiv.org/abs/2609.10540v1' },
          content: {
            title: 'Programmable World Model',
            authors: ['Zheng-Hui Huang', 'Guixu Lin', 'Jiacheng Lin'],
            paper_url: 'https://arxiv.org/abs/2609.10540v1',
            github_url: null,
            github_stars: 0,
            published_date: '2026-09-09T17:59:32Z',
          },
          collectedAt: new Date().toISOString(),
        };
        return {
          rawText: JSON.stringify(part),
          parsedJson: part,
          provider: 'gemini-flash',
          model: 'gemini-1.5-flash',
          latencyMs: 40,
        };
      }

      if (prompt.includes('Repository')) {
        const part = {
          schemaVersion: '1.0',
          recordType: 'RESEARCH_PAPER',
          source: { name: 'arXiv', url: 'https://arxiv.org/abs/2609.10540v1' },
          content: {
            title: 'Programmable World Model for Autonomous Agents',
            authors: ['Zheng-Hui Huang'],
            paper_url: 'https://arxiv.org/abs/2609.10540v1',
            github_url: 'https://github.com/AlayaLab/pwm',
            github_stars: 142,
            published_date: '2026-09-09T17:59:32Z',
          },
          collectedAt: new Date().toISOString(),
        };
        return {
          rawText: JSON.stringify(part),
          parsedJson: part,
          provider: 'gemini-flash',
          model: 'gemini-1.5-flash',
          latencyMs: 40,
        };
      }

      // Default chunk
      const part = {
        schemaVersion: '1.0',
        recordType: 'RESEARCH_PAPER',
        source: { name: 'arXiv', url: 'https://arxiv.org/abs/2609.10540v1' },
        content: {
          title: 'Programmable World Model for Autonomous Agents',
          authors: [],
          paper_url: 'https://arxiv.org/abs/2609.10540v1',
          github_url: null,
          github_stars: 0,
          published_date: '2026-09-09T17:59:32Z',
        },
        collectedAt: new Date().toISOString(),
      };
      return {
        rawText: JSON.stringify(part),
        parsedJson: part,
        provider: 'gemini-flash',
        model: 'gemini-1.5-flash',
        latencyMs: 40,
      };
    },
  };

  const engine3 = new ExtractionEngine();
  engine3.registerProvider(partialPaperAdapter);

  const res3 = await engine3.extract({
    input: { text: longResearchDocument, sourceUrl: 'https://arxiv.org/abs/2609.10540v1' },
    schema: CanonicalSchemas.RESEARCH_PAPER,
    options: {
      providers: ['gemini-flash'],
      maxPayloadBytes: 180,
    },
  });

  console.log(colors.green + `✔ Multi-Chunk Extraction & Consolidation Complete! (${res3.metadata.chunksProcessed} chunks consolidated)` + colors.reset);
  console.log(colors.bold + 'Consolidated Canonical RESEARCH_PAPER Payload:' + colors.reset);
  console.log(JSON.stringify(res3.data, null, 2));
  console.log(colors.bold + 'Metadata & Consolidation Timings:' + colors.reset);
  console.log(JSON.stringify(res3.metadata, null, 2));

  banner('ALL DEMONSTRATION SCENARIOS COMPLETED SUCCESSFULLY!');
}

runDemo().catch((err) => {
  console.error(colors.red + 'Demo failed:' + colors.reset, err);
  process.exit(1);
});
