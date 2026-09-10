import { describe, expect, it } from 'vitest';
import { chunkDocument } from '../src/chunker/semantic.js';
import {
  calculateSafeChunkLimit,
  estimateTokens,
} from '../src/chunker/token_estimator.js';

describe('Token Estimator & Safe Limit', () => {
  it('estimates tokens reliably based on character and word density', () => {
    const text = 'Artificial Intelligence and machine learning algorithms are advancing rapidly.';
    const tokens = estimateTokens(text);
    expect(tokens).toBeGreaterThan(10);
    expect(tokens).toBeLessThan(35);
  });

  it('calculates safe chunk limits reserving prompt and output tokens', () => {
    const { safeChunkTokens, reservedTokens } = calculateSafeChunkLimit(8000, {
      reservedPromptTokens: 800,
      reservedOutputTokens: 2000,
    });
    expect(reservedTokens).toBe(2800);
    expect(safeChunkTokens).toBe(5200);
  });
});

describe('Semantic Chunker', () => {
  it('chunks at document headings before paragraphs', () => {
    const doc = [
      '# Section 1: Overview',
      'This is the first paragraph describing the startup overview.',
      '',
      '# Section 2: Financials',
      'This is the second section detailing employee count and funding.',
      '',
      '# Section 3: Technology',
      'Details on technical architecture and open source libraries.',
    ].join('\n');

    // Force chunk size small enough to split sections
    const result = chunkDocument(doc, { maxCharsPerChunk: 120 });
    expect(result.chunks.length).toBeGreaterThanOrEqual(3);
    expect(result.chunks[0]?.content).toContain('# Section 1: Overview');
    expect(result.chunks[0]?.chunkId).toBe('chunk-001');
    expect(result.chunks[0]?.startOffset).toBe(0);
    expect(result.chunks[0]?.endOffset).toBe(result.chunks[0]?.content.length);
  });

  it('preserves document order and accurate offsets', () => {
    const text = [
      'Paragraph one with some information.',
      '',
      'Paragraph two with additional details.',
      '',
      'Paragraph three with the conclusion.',
    ].join('\n');

    const result = chunkDocument(text, { maxCharsPerChunk: 50 });
    expect(result.chunks.length).toBe(3);
    for (let i = 0; i < result.chunks.length; i++) {
      expect(result.chunks[i]?.index).toBe(i);
      expect(result.chunks[i]?.chunkId).toBe(`chunk-${String(i + 1).padStart(3, '0')}`);
    }
  });

  it('handles sentence level fallback for long paragraphs', () => {
    const longPara =
      'Sentence one is here. Sentence two contains more words. Sentence three concludes the paragraph.';
    const result = chunkDocument(longPara, { maxCharsPerChunk: 40 });
    expect(result.chunks.length).toBeGreaterThanOrEqual(2);
  });

  it('handles hard character splitting as last resort for long unbroken tokens', () => {
    const longUnbroken = 'A'.repeat(150);
    const result = chunkDocument(longUnbroken, { maxCharsPerChunk: 50 });
    expect(result.chunks.length).toBe(3);
    expect(result.chunks[0]?.content.length).toBe(50);
  });

  it('tracks truncation and identifies omitted portions when exceeding limits', () => {
    const huge = 'Word '.repeat(5000);
    const result = chunkDocument(huge, {
      maxCharsPerChunk: 200,
      maxTotalChunks: 3,
    });

    expect(result.truncated).toBe(true);
    expect(result.chunks.length).toBe(3);
    expect(result.omittedChars).toBeGreaterThan(0);
    expect(result.omittedRange).toBeDefined();
    expect(result.omittedRange?.start).toBeGreaterThan(0);
  });
});
