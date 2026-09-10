import { describe, expect, it } from 'vitest';
import { redactSensitive } from '../src/utils/logger.js';

describe('Structured Logger & Redaction', () => {
  it('redacts Gemini, Groq, and standard secret keys from strings', () => {
    const input = {
      message: 'Calling with AIzaSyD98765432101234567890123456789012 and gsk_12345678901234567890123456789012 and sk-abcdef12345678901234567890123456',
      auth: 'Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xyz',
    };

    const sanitized = redactSensitive(input) as typeof input;
    expect(sanitized.message).toContain('[REDACTED_GEMINI_KEY]');
    expect(sanitized.message).toContain('[REDACTED_GROQ_KEY]');
    expect(sanitized.message).toContain('[REDACTED_SECRET_KEY]');
    expect(sanitized.auth).toBe('Bearer [REDACTED]');
  });

  it('redacts sensitive object keys completely', () => {
    const sensitivePayload = {
      apiKey: 'actual-super-secret-key',
      userToken: 'secret-token-1234',
      password: 'password123',
      normalField: 'hello world',
    };

    const sanitized = redactSensitive(sensitivePayload) as Record<string, unknown>;
    expect(sanitized['apiKey']).toBe('[REDACTED]');
    expect(sanitized['userToken']).toBe('[REDACTED]');
    expect(sanitized['password']).toBe('[REDACTED]');
    expect(sanitized['normalField']).toBe('hello world');
  });

  it('truncates excessively long text in logs', () => {
    const longString = 'A'.repeat(500);
    const sanitized = redactSensitive(longString, 100) as string;
    expect(sanitized.length).toBeLessThan(200);
    expect(sanitized).toContain('[TRUNCATED 500 chars]');
  });
});
