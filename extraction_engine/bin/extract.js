#!/usr/bin/env node

import fs from 'node:fs';
import {
  extract,
  CanonicalSchemas,
} from '../dist/index.js';

function printHelp() {
  console.log(`
Usage: extract [options]

Options:
  --file <path>        Path to HTML or text file to extract from
  --url <url>          URL to fetch and extract from
  --stdin              Read raw HTML/text from standard input
  --schema <name|path> Schema to enforce ('startup', 'product', 'paper', or path to JSON schema file)
  --providers <list>   Comma-separated provider chain (e.g. gemini-flash,groq-llama3,deepseek)
  --output <path>      Path to write extracted canonical JSON (default: stdout)
  --meta               Include execution metadata in output
  -h, --help           Show this help message
`);
}

async function main() {
  const args = process.argv.slice(2);
  if (args.length === 0 || args.includes('-h') || args.includes('--help')) {
    printHelp();
    process.exit(0);
  }

  let filePath;
  let url;
  let useStdin = false;
  let schemaArg = 'startup';
  let providers;
  let outputPath;
  let includeMeta = false;

  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    if (arg === '--file' && i + 1 < args.length) filePath = args[++i];
    else if (arg === '--url' && i + 1 < args.length) url = args[++i];
    else if (arg === '--stdin') useStdin = true;
    else if (arg === '--schema' && i + 1 < args.length) schemaArg = args[++i];
    else if (arg === '--providers' && i + 1 < args.length) providers = args[++i]?.split(',').map((s) => s.trim());
    else if (arg === '--output' && i + 1 < args.length) outputPath = args[++i];
    else if (arg === '--meta') includeMeta = true;
  }

  let content = '';
  let isHtml = false;

  if (useStdin) {
    content = fs.readFileSync(0, 'utf-8');
    isHtml = content.trim().startsWith('<');
  } else if (filePath) {
    content = fs.readFileSync(filePath, 'utf-8');
    isHtml = filePath.endsWith('.html') || filePath.endsWith('.htm') || content.trim().startsWith('<');
  } else if (url) {
    const res = await fetch(url);
    if (!res.ok) {
      console.error(`Failed to fetch URL ${url}: HTTP ${res.status}`);
      process.exit(1);
    }
    content = await res.text();
    const cType = res.headers.get('content-type') || '';
    isHtml = cType.includes('text/html') || content.trim().startsWith('<');
  } else {
    console.error('Error: Must specify --file, --url, or --stdin');
    printHelp();
    process.exit(1);
  }

  // Resolve schema
  let schema;
  const sLower = schemaArg.toLowerCase();
  if (sLower === 'startup' || sLower === 'startups') {
    schema = CanonicalSchemas.STARTUP;
  } else if (sLower === 'product' || sLower === 'products') {
    schema = CanonicalSchemas.PRODUCT;
  } else if (sLower === 'paper' || sLower === 'research_paper' || sLower === 'research-paper') {
    schema = CanonicalSchemas.RESEARCH_PAPER;
  } else {
    try {
      const fileData = fs.readFileSync(schemaArg, 'utf-8');
      schema = JSON.parse(fileData);
    } catch (err) {
      console.error(`Failed to load schema from ${schemaArg}:`, err instanceof Error ? err.message : err);
      process.exit(1);
    }
  }

  const result = await extract({
    input: isHtml ? { html: content, sourceUrl: url } : { text: content, sourceUrl: url },
    schema,
    options: {
      providers,
    },
  });

  const outputData = includeMeta ? result : result.data;
  const serialized = JSON.stringify(outputData, null, 2);

  if (outputPath) {
    fs.writeFileSync(outputPath, serialized, 'utf-8');
    console.log(`Saved canonical extraction to ${outputPath}`);
  } else {
    console.log(serialized);
  }
}

main().catch((err) => {
  console.error('Extraction failed:', err instanceof Error ? err.message : err);
  process.exit(1);
});
