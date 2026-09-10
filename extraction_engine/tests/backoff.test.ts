import { describe, expect, it } from 'vitest';
import {
  DefaultClock,
  calculateBackoffDelay,
  isRetriableStatusCode,
  parseRetryAfter,
} from '../src/utils/backoff.js';
import { ExtractionAbortedError } from '../src/utils/errors.js';

describe('Exponential Backoff & Full Jitter', () => {
  it('calculates deterministic delay with a fixed RNG', () => {
    const fixedRng = { random: () => 0.5 };

    // attempt 0: ceiling = min(10000, 500 * 2^0) = 500 => delay = 250
    const delay0 = calculateBackoffDelay({
      attempt: 0,
      baseDelayMs: 500,
      maxDelayMs: 10000,
      rng: fixedRng,
    });
    expect(delay0).toBe(250);

    // attempt 1: ceiling = min(10000, 500 * 2^1) = 1000 => delay = 500
    const delay1 = calculateBackoffDelay({
      attempt: 1,
      baseDelayMs: 500,
      maxDelayMs: 10000,
      rng: fixedRng,
    });
    expect(delay1).toBe(500);

    // attempt 2: ceiling = min(10000, 500 * 2^2) = 2000 => delay = 1000
    const delay2 = calculateBackoffDelay({
      attempt: 2,
      baseDelayMs: 500,
      maxDelayMs: 10000,
      rng: fixedRng,
    });
    expect(delay2).toBe(1000);

    // High attempt capped at maxDelay: ceiling = 10000 => delay = 5000
    const delayHigh = calculateBackoffDelay({
      attempt: 10,
      baseDelayMs: 500,
      maxDelayMs: 10000,
      rng: fixedRng,
    });
    expect(delayHigh).toBe(5000);
  });

  it('respects Retry-After header with small jitter', () => {
    const fixedRng = { random: () => 0.5 };
    const delay = calculateBackoffDelay({
      attempt: 1,
      baseDelayMs: 500,
      maxDelayMs: 10000,
      retryAfterMs: 4000,
      rng: fixedRng,
    });
    // 4000 + 4000 * 0.1 * 0.5 = 4200
    expect(delay).toBe(4200);
  });

  it('parses numeric seconds and HTTP dates for Retry-After', () => {
    // Numeric seconds
    expect(parseRetryAfter('15')).toBe(15000);
    expect(parseRetryAfter('0')).toBe(0);
    expect(parseRetryAfter(null)).toBeNull();
    expect(parseRetryAfter('invalid')).toBeNull();

    // HTTP date
    const mockClock = {
      now: () => 1700000000000,
      sleep: () => Promise.resolve(),
    };
    const targetDate = new Date(1700000005000).toUTCString();
    const parsedDateMs = parseRetryAfter(targetDate, mockClock);
    expect(parsedDateMs).toBe(5000);
  });

  it('correctly categorizes retriable vs non-retriable HTTP status codes', () => {
    expect(isRetriableStatusCode(408)).toBe(true);
    expect(isRetriableStatusCode(409)).toBe(true);
    expect(isRetriableStatusCode(413)).toBe(true);
    expect(isRetriableStatusCode(429)).toBe(true);
    expect(isRetriableStatusCode(500)).toBe(true);
    expect(isRetriableStatusCode(502)).toBe(true);
    expect(isRetriableStatusCode(503)).toBe(true);
    expect(isRetriableStatusCode(504)).toBe(true);

    // Non-retriable (failover immediately)
    expect(isRetriableStatusCode(400)).toBe(false);
    expect(isRetriableStatusCode(401)).toBe(false);
    expect(isRetriableStatusCode(403)).toBe(false);
    expect(isRetriableStatusCode(404)).toBe(false);
    expect(isRetriableStatusCode(422)).toBe(false);
  });

  it('aborts sleep promptly when AbortSignal fires', async () => {
    const clock = new DefaultClock();
    const controller = new AbortController();

    const sleepPromise = clock.sleep(5000, controller.signal);
    // Abort after 50ms
    setTimeout(() => controller.abort(), 50);

    await expect(sleepPromise).rejects.toThrow(ExtractionAbortedError);
  });
});
