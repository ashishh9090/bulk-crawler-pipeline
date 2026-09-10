import { EngineConfig, defaultConfig } from '../config/index.js';
import { HttpClient, LLMProviderAdapter, ProviderName } from '../types/index.js';
import { GeminiFlashAdapter } from './gemini.js';
import { GroqLlamaAdapter } from './groq.js';
import { DeepSeekAdapter } from './deepseek.js';

export class ProviderRegistry {
  private adapters = new Map<ProviderName, LLMProviderAdapter>();

  constructor(
    config: EngineConfig = defaultConfig,
    httpClient?: HttpClient
  ) {
    // Register built-in adapters
    const geminiCfg = config.providers['gemini-flash'];
    this.register(
      new GeminiFlashAdapter({
        apiKey: geminiCfg?.apiKey,
        baseUrl: geminiCfg?.baseUrl,
        httpClient,
      })
    );

    const groqCfg = config.providers['groq-llama3'];
    this.register(
      new GroqLlamaAdapter({
        apiKey: groqCfg?.apiKey,
        baseUrl: groqCfg?.baseUrl,
        httpClient,
      })
    );

    const deepseekCfg = config.providers['deepseek'];
    this.register(
      new DeepSeekAdapter({
        apiKey: deepseekCfg?.apiKey,
        baseUrl: deepseekCfg?.baseUrl,
        httpClient,
      })
    );
  }

  register(adapter: LLMProviderAdapter): void {
    this.adapters.set(adapter.name, adapter);
  }

  get(name: ProviderName): LLMProviderAdapter | undefined {
    return this.adapters.get(name);
  }

  resolveChain(
    requestedChain?: ProviderName[],
    defaultChain: ProviderName[] = ['gemini-flash', 'groq-llama3', 'deepseek']
  ): LLMProviderAdapter[] {
    const chainNames = requestedChain && requestedChain.length > 0
      ? requestedChain
      : defaultChain;

    const resolved: LLMProviderAdapter[] = [];
    for (const name of chainNames) {
      const adapter = this.adapters.get(name);
      if (adapter) {
        resolved.push(adapter);
      }
    }
    return resolved;
  }
}
