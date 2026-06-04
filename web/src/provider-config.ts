export const providerStorageKey = "lumak.providerConfig";

export const customModelOptions = ["custom"];

export const modelOptions: Record<string, string[]> = {
  minimax: ["MiniMax-M2.7", "abab6.5s-chat", "custom"],
  anthropic: ["claude-sonnet-4-5", "claude-opus-4-1", "custom"],
  openai: ["gpt-5.1", "gpt-5.1-mini", "custom"],
  deepseek: ["deepseek-chat", "deepseek-reasoner", "custom"],
  custom: customModelOptions,
};

export type ProviderConfig = {
  apiKey: string;
  baseUrl?: string;
  model: string;
  provider: string;
  maxTokens?: number;
  maxSteps?: number;
};
