import { CanonicalJsonSchema } from '../types/index.js';
import { assertValidSchema } from '../schemas/validator.js';

/**
 * Checks if a value is considered "empty" or low-information.
 */
function isLowInformation(val: unknown): boolean {
  if (val === null || val === undefined) return true;
  if (typeof val === 'string' && val.trim().length === 0) return true;
  if (Array.isArray(val) && val.length === 0) return true;
  if (typeof val === 'object' && Object.keys(val as object).length === 0) return true;
  return false;
}

/**
 * Chooses the higher-information value between existing and incoming fields.
 */
function resolveValue(existing: unknown, incoming: unknown): unknown {
  if (isLowInformation(incoming)) return existing;
  if (isLowInformation(existing)) return incoming;

  // If both are arrays, combine and deduplicate
  if (Array.isArray(existing) && Array.isArray(incoming)) {
    const combined = [...existing, ...incoming];
    // Deduplicate primitives or JSON strings
    const seen = new Set<string>();
    const deduplicated: unknown[] = [];
    for (const item of combined) {
      const key = typeof item === 'object' ? JSON.stringify(item) : String(item);
      if (!seen.has(key)) {
        seen.add(key);
        deduplicated.push(item);
      }
    }
    return deduplicated;
  }

  // If both are objects, merge recursively
  if (
    typeof existing === 'object' &&
    typeof incoming === 'object' &&
    existing !== null &&
    incoming !== null
  ) {
    return mergeObjects(
      existing as Record<string, unknown>,
      incoming as Record<string, unknown>
    );
  }

  // If both are numbers, prefer greater number if non-zero (e.g. stars, employees)
  if (typeof existing === 'number' && typeof incoming === 'number') {
    if (existing === 0 && incoming > 0) return incoming;
    if (incoming === 0 && existing > 0) return existing;
    return Math.max(existing, incoming);
  }

  // If both are strings, prefer longer, more descriptive string
  if (typeof existing === 'string' && typeof incoming === 'string') {
    return incoming.trim().length > existing.trim().length ? incoming : existing;
  }

  return incoming ?? existing;
}

/**
 * Deep merges two record objects prioritizing non-empty and richer fields.
 */
export function mergeObjects(
  target: Record<string, unknown>,
  source: Record<string, unknown>
): Record<string, unknown> {
  const result: Record<string, unknown> = { ...target };

  for (const [key, value] of Object.entries(source)) {
    if (result[key] === undefined) {
      result[key] = value;
    } else {
      result[key] = resolveValue(result[key], value);
    }
  }

  return result;
}

/**
 * Consolidates multiple partial candidate objects extracted across document chunks.
 */
export function consolidateCandidates<T = unknown>(
  candidates: unknown[],
  schema: CanonicalJsonSchema
): T {
  if (!candidates || candidates.length === 0) {
    throw new Error('Cannot consolidate empty candidates list');
  }

  if (candidates.length === 1) {
    return assertValidSchema<T>(schema, candidates[0]);
  }

  // Filter out completely null/empty candidates
  const validObjects = candidates.filter(
    (c): c is Record<string, unknown> =>
      typeof c === 'object' && c !== null && !Array.isArray(c)
  );

  if (validObjects.length === 0) {
    throw new Error('No valid candidate objects found to consolidate');
  }

  // Accumulate and merge in document order
  let merged: Record<string, unknown> = { ...validObjects[0] };
  for (let i = 1; i < validObjects.length; i++) {
    merged = mergeObjects(merged, validObjects[i]!);
  }

  // Ensure canonical schema validation passes on consolidated result
  return assertValidSchema<T>(schema, merged);
}
