import { describe, expect, it } from 'vitest';
import {
  buildRepairPrompt,
  healJsonString,
  parseJsonSafely,
} from '../src/utils/json_repair.js';
import { MalformedJsonError } from '../src/utils/errors.js';

describe('JSON Repair & Healing Utilities', () => {
  it('strips markdown code blocks and whitespace', () => {
    const raw = '```json\n{\n  "name": "Acme",\n  "employees": 42\n}\n```';
    const healed = healJsonString(raw);
    expect(JSON.parse(healed)).toEqual({ name: 'Acme', employees: 42 });
  });

  it('strips conversational preambles and postambles', () => {
    const raw = `Here is the structured JSON output you requested:
    {
      "entityName": "NovaTech",
      "data": { "employeeCount": 120 }
    }
    Hope this helps! Let me know if you need anything else.`;

    const healed = healJsonString(raw);
    expect(JSON.parse(healed)).toEqual({
      entityName: 'NovaTech',
      data: { employeeCount: 120 },
    });
  });

  it('removes trailing commas before closing braces and brackets', () => {
    const raw = '{"a": 1, "b": [2, 3, ], }';
    const healed = healJsonString(raw);
    expect(JSON.parse(healed)).toEqual({ a: 1, b: [2, 3] });
  });

  it('auto-closes unclosed braces', () => {
    const raw = '{"entityName": "Acme Corp", "pricing": "FREE"';
    const healed = healJsonString(raw);
    expect(JSON.parse(healed)).toEqual({ entityName: 'Acme Corp', pricing: 'FREE' });
  });

  it('parses valid JSON directly without modifying it', () => {
    const raw = '{"key": "value", "count": 10}';
    const parsed = parseJsonSafely(raw);
    expect(parsed).toEqual({ key: 'value', count: 10 });
  });

  it('throws MalformedJsonError when JSON is completely unparseable', () => {
    const raw = 'This is pure gibberish with no json { at all';
    expect(() => parseJsonSafely(raw, 'gemini', 'gemini-1.5-flash')).toThrow(
      MalformedJsonError
    );
  });

  it('builds a concise, schema-grounded repair prompt', () => {
    const prompt = buildRepairPrompt({
      brokenText: '{"entity": "Acme"',
      validationError: 'Unexpected end of JSON',
      schema: { type: 'object', required: ['entity'] },
    });

    expect(prompt).toContain('CRITICAL INSTRUCTION');
    expect(prompt).toContain('Unexpected end of JSON');
    expect(prompt).toContain('"entity": "Acme"');
    expect(prompt).toContain('"required": [');
  });
});
