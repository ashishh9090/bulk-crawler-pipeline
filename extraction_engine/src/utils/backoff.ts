import { Clock, RandomGenerator } from '../types/index.js';
import { ExtractionAbortedError } from './errors.js';

export class DefaultClock implements Clock {
  now(): number {
    return Date.now();
  }

  sleep(ms: number, signal?: AbortSignal): Promise<void> {
    if (signal?.aborted) {
      return Promise.reject(new ExtractionAbortedError());
    }
    if (ms <= 0) {
      return Promise.resolve();
    }

    return new Promise<void>((resolve, reject) => {
      let timer: NodeJS.Timeout | null = null;

      const onAbort = () => {
        if (timer) clearTimeout(timer);
        reject(new ExtractionAbortedError());
      };

      if (signal) {
        signal.addEventListener('abort', onAbort, { once: true });
      }

      timer = setTimeout(() => {
        if (signal) {
          signal.removeEventListener('abort', onAbort);
        }
        resolve();
      }, ms);
    });
  }
}

export class DefaultRandomGenerator implements RandomGenerator {
  random(): number {
    return Math.random();
  }
}

export function parseRetryAfter(
  headerValue: string | null | undefined,
  clock: Clock = new DefaultClock()
): number | null {
  if (!headerValue) return null;
  const trimmed = headerValue.trim();
  if (!trimmed) return null;

  // Case 1: Integer seconds (e.g. "120")
  const seconds = Number(trimmed);
  if (!Number.isNaN(seconds) && seconds >= 0) {
    return Math.round(seconds * 1000);
  }

  // Case 2: HTTP date (e.g. "Wed, 21 Oct 2026 07:28:00 GMT")
  const parsedDate = Date.parse(trimmed);
  if (!Number.isNaN(parsedDate)) {
    const diffMs = parsedDate - clock.now();
    return Math.max(0, diffMs);
  }

  return null;
}

export function calculateBackoffDelay(params: {
  attempt: number;
  baseDelayMs?: number;
  maxDelayMs?: number;
  retryAfterMs?: number | null;
  rng?: RandomGenerator;
}): number {
  const {
    attempt,
    baseDelayMs = 500,
    maxDelayMs = 10000,
    retryAfterMs = null,
    rng = new DefaultRandomGenerator(),
  } = params;

  if (retryAfterMs !== null && retryAfterMs !== undefined && retryAfterMs > 0) {
    // Respect Retry-After if provided, cap at maxDelayMs, add small jitter (up to 10%)
    const capped = Math.min(retryAfterMs, maxDelayMs);
    const jitter = capped * (0.1 * rng.random());
    return Math.round(capped + jitter);
  }

  // Full jitter exponential backoff:
  // ceiling = min(maxDelayMs, baseDelayMs * 2^attempt)
  // delay = ceiling * random(0, 1)
  const ceiling = Math.min(maxDelayMs, baseDelayMs * Math.pow(2, attempt));
  const fullJitter = ceiling * rng.random();
  return Math.round(fullJitter);
}

export const RETRIABLE_STATUS_CODES = new Set([
  408, // Request Timeout
  409, // Conflict (transient)
  413, // Payload Too Large (retried with reduced chunk)
  429, // Too Many Requests / Rate limit
  500, // Internal Server Error
  502, // Bad Gateway
  503, // Service Unavailable
  504, // Gateway Timeout
]);

export function isRetriableStatusCode(statusCode?: number): boolean {
  if (!statusCode) return false;
  return RETRIABLE_STATUS_CODES.has(statusCode);
}
