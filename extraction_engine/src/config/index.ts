import { ProviderName } from '../types/index.js';

export interface ProviderConfig {
  apiKey?: string;
  model: string;
  baseUrl: string;
  timeoutMs: number;
  maxTokens: number;
}

export interface EngineConfig {
  providerChain: ProviderName[];
  defaultMaxRetries: number;
  defaultTimeoutMs: number;
  baseDelayMs: number;
  maxDelayMs: number;
  maxPayloadBytes: number;
  maxInputTokens: number;
  repairAttempts: number;
  enableConsolidation: boolean;
  providers: {
    'gemini-flash': ProviderConfig;
    'groq-llama3': ProviderConfig;
    deepseek: ProviderConfig;
    [key: string]: ProviderConfig | undefined;
  };
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): EngineConfig {
  const chainStr = env['EXTRACTION_PROVIDER_CHAIN'] || 'gemini-flash,groq-llama3,deepseek';
  const providerChain: ProviderName[] = chainStr
    .split(',')
    .map((p) => p.trim())
    .filter(Boolean);

  return {
    providerChain,
    defaultMaxRetries: Number(env['EXTRACTION_MAX_RETRIES'] || '3'),
    defaultTimeoutMs: Number(env['EXTRACTION_TIMEOUT_MS'] || '30000'),
    baseDelayMs: Number(env['EXTRACTION_BASE_DELAY_MS'] || '500'),
    maxDelayMs: Number(env['EXTRACTION_MAX_DELAY_MS'] || '10000'),
    maxPayloadBytes: Number(env['EXTRACTION_MAX_PAYLOAD_BYTES'] || '250000'),
    maxInputTokens: Number(env['EXTRACTION_MAX_INPUT_TOKENS'] || '12000'),
    repairAttempts: Number(env['EXTRACTION_REPAIR_ATTEMPTS'] || '1'),
    enableConsolidation: env['EXTRACTION_ENABLE_CONSOLIDATION'] !== 'false',
    providers: {
      'gemini-flash': {
        apiKey: env['GEMINI_API_KEY'],
        model: env['GEMINI_MODEL'] || 'gemini-1.5-flash',
        baseUrl:
          env['GEMINI_BASE_URL'] ||
          'https://generativelanguage.googleapis.com/v1beta',
        timeoutMs: Number(env['GEMINI_TIMEOUT_MS'] || '30000'),
        maxTokens: Number(env['GEMINI_MAX_TOKENS'] || '32000'),
      },
      'groq-llama3': {
        apiKey: env['GROQ_API_KEY'],
        model: env['GROQ_MODEL'] || 'llama-3.3-70b-versatile',
        baseUrl:
          env['GROQ_BASE_URL'] ||
          'https://api.groq.com/openai/v1',
        timeoutMs: Number(env['GROQ_TIMEOUT_MS'] || '30000'),
        maxTokens: Number(env['GROQ_MAX_TOKENS'] || '8000'),
      },
      deepseek: {
        apiKey: env['DEEPSEEK_API_KEY'],
        model: env['DEEPSEEK_MODEL'] || 'deepseek-chat',
        baseUrl:
          env['DEEPSEEK_BASE_URL'] ||
          'https://api.deepseek.com',
        timeoutMs: Number(env['DEEPSEEK_TIMEOUT_MS'] || '35000'),
        maxTokens: Number(env['DEEPSEEK_MAX_TOKENS'] || '16000'),
      },
    },
  };
}

export const defaultConfig = loadConfig();
