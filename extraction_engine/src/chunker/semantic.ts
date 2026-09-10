import { DocumentChunk } from '../types/index.js';
import { estimateTokens } from './token_estimator.js';

export interface ChunkingOptions {
  maxTokensPerChunk?: number;
  maxCharsPerChunk?: number;
  maxTotalChunks?: number;
  maxTotalChars?: number;
}

export interface ChunkingResult {
  chunks: DocumentChunk[];
  truncated: boolean;
  omittedChars?: number;
  omittedRange?: { start: number; end: number };
}

/**
 * Splits text into semantic units along a prioritized set of boundary markers:
 * 1. Headings / Sections (# , ## , ### )
 * 2. Paragraphs (\n\n)
 * 3. List and table rows (\n-, \n*, \n|)
 * 4. Sentences ([.?!]\s+)
 * 5. Hard character slice
 */
function splitUnits(text: string): string[] {
  // If text has markdown headings, split by heading boundaries while keeping heading with following text
  const headingRegex = /(?=(?:\r?\n|^)#{1,4}\s+)/g;
  const sections = text.split(headingRegex).map((s) => s.trim()).filter(Boolean);
  if (sections.length > 1) {
    return sections;
  }

  // Fallback to paragraphs
  const paragraphs = text.split(/\n{2,}/).map((p) => p.trim()).filter(Boolean);
  if (paragraphs.length > 1) {
    return paragraphs;
  }

  // Fallback to list/table rows
  const listOrTable = text.split(/\n(?=[-*\d.]\s+|\|)/).map((l) => l.trim()).filter(Boolean);
  if (listOrTable.length > 1) {
    return listOrTable;
  }

  // Fallback to sentences
  const sentences = text
    .split(/(?<=[.?!])\s+(?=[A-Z0-9])/g)
    .map((s) => s.trim())
    .filter(Boolean);
  if (sentences.length > 1) {
    return sentences;
  }

  return [text];
}

/**
 * Recursively divides a large text block into chunks smaller than maxChars.
 */
function breakDownBlock(block: string, maxChars: number): string[] {
  if (block.length <= maxChars) {
    return [block];
  }

  const units = splitUnits(block);
  if (units.length > 1 && units[0] !== block) {
    const result: string[] = [];
    let current = '';

    for (const unit of units) {
      if ((current + '\n\n' + unit).trim().length <= maxChars) {
        current = current ? `${current}\n\n${unit}` : unit;
      } else {
        if (current) {
          result.push(current);
          current = '';
        }
        if (unit.length <= maxChars) {
          current = unit;
        } else {
          // Break down this sub-unit further
          result.push(...breakDownBlock(unit, maxChars));
        }
      }
    }
    if (current) {
      result.push(current);
    }
    return result;
  }

  // Hard character split as last resort
  const slices: string[] = [];
  let remaining = block;
  while (remaining.length > 0) {
    if (remaining.length <= maxChars) {
      slices.push(remaining);
      break;
    }
    // Attempt to break at the last whitespace before maxChars
    let sliceEnd = remaining.lastIndexOf(' ', maxChars);
    if (sliceEnd <= 0) {
      sliceEnd = maxChars;
    }
    slices.push(remaining.slice(0, sliceEnd).trim());
    remaining = remaining.slice(sliceEnd).trim();
  }
  return slices;
}

export function chunkDocument(
  sourceText: string,
  options: ChunkingOptions = {}
): ChunkingResult {
  if (!sourceText || !sourceText.trim()) {
    return {
      chunks: [],
      truncated: false,
    };
  }

  const maxTokens = options.maxTokensPerChunk ?? 8000;
  // Use character limit corresponding to ~3.5 chars/token or user provided maxCharsPerChunk
  const maxChars = options.maxCharsPerChunk ?? Math.floor(maxTokens * 3.5);
  const maxTotalChunks = options.maxTotalChunks ?? 25;
  const maxTotalChars = options.maxTotalChars ?? 500000;

  let workingText = sourceText;
  let truncated = false;
  let omittedChars: number | undefined;
  let omittedRange: { start: number; end: number } | undefined;

  if (workingText.length > maxTotalChars) {
    truncated = true;
    omittedChars = workingText.length - maxTotalChars;
    omittedRange = { start: maxTotalChars, end: workingText.length };
    workingText = workingText.slice(0, maxTotalChars);
  }

  const rawBlocks = breakDownBlock(workingText, maxChars);
  const chunks: DocumentChunk[] = [];
  let currentOffset = 0;

  for (let i = 0; i < rawBlocks.length; i++) {
    if (i >= maxTotalChunks) {
      truncated = true;
      const startOmitted = currentOffset;
      const endOmitted = workingText.length;
      omittedChars = (omittedChars ?? 0) + (endOmitted - startOmitted);
      omittedRange = { start: startOmitted, end: endOmitted };
      break;
    }

    const content = rawBlocks[i]!;
    const charCount = content.length;
    const estimatedTokens = estimateTokens(content);
    const startOffset = currentOffset;
    const endOffset = currentOffset + charCount;

    chunks.push({
      chunkId: `chunk-${String(i + 1).padStart(3, '0')}`,
      index: i,
      content,
      charCount,
      estimatedTokens,
      startOffset,
      endOffset,
    });

    currentOffset = endOffset + 2; // account for inter-block spacing
  }

  return {
    chunks,
    truncated,
    omittedChars,
    omittedRange,
  };
}
