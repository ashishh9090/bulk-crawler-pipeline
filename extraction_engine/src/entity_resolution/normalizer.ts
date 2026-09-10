/**
 * Deterministic entity name and domain normalizer in TypeScript.
 */

const CORPORATE_SUFFIXES_REGEX = /\b(inc(\.|\b)|incorporated\b|llc(\.|\b)|l\.l\.c\.?|ltd(\.|\b)|limited\b|corp(\.|\b)|corporation\b|gmbh\b|co(\.|\b)|company\b|pbc\b|sas\b|se\b|ag\b|s\.a\.?|b\.v\.?|bv\b|k\.k\.?|kk\b|pte(\.|\s)+ltd(\.|\b)|pvt(\.|\s)+ltd(\.|\b)|opco(\s+llc)?\b)/gi;

const AI_SPACING_REPLACEMENTS: Array<[RegExp, string]> = [
  [/\bopen\s+ai\b/gi, 'openai'],
  [/\bmistral\s+ai\b/gi, 'mistral ai'],
  [/\bperplexity\s+ai\b/gi, 'perplexity ai'],
  [/\bscale\s+ai\b/gi, 'scale ai'],
  [/\bstability\s+ai\b/gi, 'stability ai'],
  [/\binflection\s+ai\b/gi, 'inflection ai'],
  [/\beleven\s+labs\b/gi, 'elevenlabs'],
  [/\bcursor\s+ai\b/gi, 'cursor'],
  [/\bhugging\s+face\b/gi, 'hugging face'],
  [/\bhuggingface\b/gi, 'hugging face'],
  [/\brunway\s*ml\b/gi, 'runway'],
  [/\bw\s*&\s*b\b/gi, 'weights and biases'],
  [/\bwandb\b/gi, 'weights and biases'],
];

export function normalizeEntityName(rawName?: string | null): string {
  if (!rawName || typeof rawName !== 'string') {
    return '';
  }

  // Unicode normalize NFKD, strip diacritical marks, then NFC
  let normalized = rawName
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .normalize('NFC')
    .toLowerCase();

  // Known AI spacing replacements
  for (const [pattern, replacement] of AI_SPACING_REPLACEMENTS) {
    normalized = normalized.replace(pattern, replacement);
  }

  // Corporate suffix removal
  normalized = normalized.replace(/[\s,]+$/, '');
  normalized = normalized.replace(CORPORATE_SUFFIXES_REGEX, ' ');

  // Non-alphanumeric to space
  normalized = normalized.replace(/[^\w\s]/g, ' ');

  // Collapse spaces
  return normalized.replace(/\s+/g, ' ').trim();
}

export function normalizeDomain(urlOrDomain?: string | null): string {
  if (!urlOrDomain || typeof urlOrDomain !== 'string') {
    return '';
  }

  let raw = urlOrDomain.trim().toLowerCase();
  if (!raw.startsWith('http://') && !raw.startsWith('https://')) {
    raw = 'https://' + raw;
  }

  try {
    const url = new URL(raw);
    let host = url.hostname;
    if (host.startsWith('www.')) {
      host = host.slice(4);
    }
    return host.trim();
  } catch {
    return '';
  }
}
