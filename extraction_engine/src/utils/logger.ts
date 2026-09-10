import { LogEntry, LogLevel, Logger } from '../types/index.js';

const SENSITIVE_KEY_PATTERNS = [
  /api[-_]?key/i,
  /authorization/i,
  /token/i,
  /secret/i,
  /password/i,
  /bearer/i,
];

export function redactSensitive(obj: unknown, maxStringLength = 200): unknown {
  if (obj === null || obj === undefined) return obj;
  if (typeof obj === 'string') {
    // Redact potential Bearer tokens or API keys matching common key signatures
    let sanitized = obj
      .replace(/AIza[0-9A-Za-z-_]{35}/g, '[REDACTED_GEMINI_KEY]')
      .replace(/gsk_[a-zA-Z0-9]{32,}/g, '[REDACTED_GROQ_KEY]')
      .replace(/sk-[a-zA-Z0-9]{32,}/g, '[REDACTED_SECRET_KEY]')
      .replace(/Bearer\s+[A-Za-z0-9._~+/-]+=*/gi, 'Bearer [REDACTED]');

    if (sanitized.length > maxStringLength) {
      return sanitized.slice(0, maxStringLength) + `... [TRUNCATED ${sanitized.length} chars]`;
    }
    return sanitized;
  }
  if (Array.isArray(obj)) {
    return obj.map((item) => redactSensitive(item, maxStringLength));
  }
  if (typeof obj === 'object') {
    const result: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(obj as Record<string, unknown>)) {
      if (SENSITIVE_KEY_PATTERNS.some((p) => p.test(k))) {
        result[k] = '[REDACTED]';
      } else {
        result[k] = redactSensitive(v, maxStringLength);
      }
    }
    return result;
  }
  return obj;
}

export class StructuredLogger implements Logger {
  private minLevel: LogLevel;
  private readonly levels: Record<LogLevel, number> = {
    debug: 0,
    info: 1,
    warn: 2,
    error: 3,
  };

  constructor(minLevel: LogLevel = 'info') {
    this.minLevel = minLevel;
  }

  setLevel(level: LogLevel): void {
    this.minLevel = level;
  }

  private shouldLog(level: LogLevel): boolean {
    return this.levels[level] >= this.levels[this.minLevel];
  }

  private emit(level: LogLevel, event: string, meta?: Partial<LogEntry>): void {
    if (!this.shouldLog(level)) return;

    const entry: LogEntry = {
      timestamp: new Date().toISOString(),
      level,
      event,
      ...(meta ? (redactSensitive(meta) as Partial<LogEntry>) : {}),
    };

    const serialized = JSON.stringify(entry);
    if (level === 'error') {
      console.error(serialized);
    } else if (level === 'warn') {
      console.warn(serialized);
    } else {
      console.log(serialized);
    }
  }

  debug(event: string, meta?: Partial<LogEntry>): void {
    this.emit('debug', event, meta);
  }

  info(event: string, meta?: Partial<LogEntry>): void {
    this.emit('info', event, meta);
  }

  warn(event: string, meta?: Partial<LogEntry>): void {
    this.emit('warn', event, meta);
  }

  error(event: string, meta?: Partial<LogEntry>): void {
    this.emit('error', event, meta);
  }
}

export const defaultLogger = new StructuredLogger(
  (process.env['LOG_LEVEL']?.toLowerCase() as LogLevel) || 'info'
);
