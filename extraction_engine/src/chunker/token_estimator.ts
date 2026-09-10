/**
 * Token and payload size estimation with safety buffer calculation.
 */

export interface TokenBudgetOptions {
  maxContextTokens?: number;
  reservedPromptTokens?: number;
  reservedOutputTokens?: number;
}

export const DEFAULT_RESERVED_PROMPT_TOKENS = 800;
export const DEFAULT_RESERVED_OUTPUT_TOKENS = 2500;

/**
 * Estimates token count based on character density and word boundaries.
 * In practice for mixed HTML/text and JSON schemas, 3.8 - 4.0 chars/token is reliable.
 */
export function estimateTokens(text: string): number {
  if (!text) return 0;
  const chars = text.length;
  // Word count estimation
  const words = text.trim().split(/\s+/).filter(Boolean).length;
  // Use hybrid upper bound to guarantee safety against token overflow
  const charEstimate = Math.ceil(chars / 3.7);
  const wordEstimate = Math.ceil(words * 1.35);
  return Math.max(charEstimate, wordEstimate, 1);
}

/**
 * Calculates maximum safe chunk tokens, reserving space for system instructions,
 * schema definitions, and model generation tokens.
 */
export function calculateSafeChunkLimit(
  maxTotalTokens: number,
  options: TokenBudgetOptions = {}
): {
  safeChunkTokens: number;
  reservedTokens: number;
} {
  const reservedPrompt =
    options.reservedPromptTokens ?? DEFAULT_RESERVED_PROMPT_TOKENS;
  const reservedOutput =
    options.reservedOutputTokens ?? DEFAULT_RESERVED_OUTPUT_TOKENS;
  const totalReserved = reservedPrompt + reservedOutput;

  const safeChunkTokens = Math.max(500, maxTotalTokens - totalReserved);
  return {
    safeChunkTokens,
    reservedTokens: totalReserved,
  };
}
