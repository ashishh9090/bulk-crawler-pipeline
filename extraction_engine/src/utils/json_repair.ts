import { CanonicalJsonSchema } from '../types/index.js';
import { MalformedJsonError } from './errors.js';

/**
 * Heuristic JSON cleaner that strips markdown code blocks, conversational text,
 * trailing commas, and unclosed delimiters.
 */
export function healJsonString(raw: string): string {
  if (!raw) return '';

  let text = raw.trim();

  // 1. Remove markdown code block fences (e.g. ```json ... ``` or ``` ...)
  const fenceRegex = /```(?:json)?\s*([\s\S]*?)\s*```/i;
  const matchFence = text.match(fenceRegex);
  if (matchFence && matchFence[1]) {
    text = matchFence[1].trim();
  }

  // 2. Extract substring between first '{' or '[' and last '}' or ']'
  const firstCurly = text.indexOf('{');
  const firstSquare = text.indexOf('[');
  let startIdx = -1;

  if (firstCurly !== -1 && firstSquare !== -1) {
    startIdx = Math.min(firstCurly, firstSquare);
  } else if (firstCurly !== -1) {
    startIdx = firstCurly;
  } else if (firstSquare !== -1) {
    startIdx = firstSquare;
  }

  if (startIdx !== -1) {
    const isObject = text[startIdx] === '{';
    const lastDelim = isObject ? text.lastIndexOf('}') : text.lastIndexOf(']');
    if (lastDelim > startIdx) {
      text = text.slice(startIdx, lastDelim + 1);
    } else {
      // Unclosed delimiter: slice from start and auto-close
      text = text.slice(startIdx);
      text = text + (isObject ? '}' : ']');
    }
  }

  // 3. Remove trailing commas before closing braces/brackets
  text = text.replace(/,\s*([}\]])/g, '$1');

  // 4. Normalize single-quoted keys if present: {'key': -> {"key":
  text = text.replace(/([{,]\s*)'([^'\n\r]+)'\s*:/g, '$1"$2":');

  return text;
}

/**
 * Safely parse JSON from raw LLM output, applying local heuristics if initial parse fails.
 */
export function parseJsonSafely(
  raw: string,
  provider?: string,
  model?: string
): unknown {
  if (!raw || typeof raw !== 'string') {
    throw new MalformedJsonError({
      message: 'LLM returned empty or non-string response',
      rawText: raw ?? '',
      provider,
      model,
    });
  }

  // Try direct parse first
  try {
    return JSON.parse(raw);
  } catch {
    // Attempt local healing
    const healed = healJsonString(raw);
    try {
      return JSON.parse(healed);
    } catch (healErr) {
      const originalErr = healErr instanceof Error ? healErr.message : String(healErr);
      throw new MalformedJsonError({
        message: `Failed to parse JSON even after healing: ${originalErr}`,
        rawText: raw,
        provider,
        model,
      });
    }
  }
}

/**
 * Constructs a bounded repair prompt instructing the model to fix malformed or invalid JSON.
 */
export function buildRepairPrompt(params: {
  brokenText: string;
  validationError: string;
  schema: CanonicalJsonSchema;
}): string {
  return [
    'CRITICAL INSTRUCTION: Your previous response was invalid. Return ONLY a single raw JSON object that strictly adheres to the requested schema. Do NOT include markdown formatting, code fences (```json), or any commentary.',
    '',
    'VALIDATION / PARSE ERROR:',
    params.validationError,
    '',
    'EXPECTED JSON SCHEMA:',
    JSON.stringify(params.schema, null, 2),
    '',
    'PREVIOUS FAULTY OUTPUT TO FIX:',
    params.brokenText,
  ].join('\n');
}
