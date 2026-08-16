/**
 * Infer an upstream-model brand from a model id, so the chat model picker
 * can show a vendor logo that matches the model itself rather than the
 * profile's OpenAI-compatible binding. Probing the catalog would be more
 * accurate but forces a request; a small heuristic table covers the
 * model names that show up today and degrades to the binding name
 * silently for anything unknown.
 *
 * Returned keys match the binding strings recognised by `ProviderIcon`
 * (e.g. "deepseek" -> deepseek-color.svg, "zhipu" -> zhipu-color.svg).
 * Returning `undefined` lets the caller fall back to `option.provider`,
 * which is the safe default for already-bound models (gpt-* / claude-* /
 * gemini-* etc. will keep their binding-native logo).
 */
const PREFIX_TABLE: ReadonlyArray<readonly [RegExp, string]> = [
  // OpenAI
  [/\bgpt-/, "openai"],
  [/\bo[1-9]\b/, "openai"],
  // Anthropic
  [/\bclaude-/, "anthropic"],
  // DeepSeek
  [/^deepseek[-_/]/i, "deepseek"],
  [/\/deepseek-/i, "deepseek"],
  // DeepSeek routed via vendor slugs ("deepseek-ai/DeepSeek-V3")
  [/^deepseek-ai\//i, "deepseek"],
  // Zhipu / GLM
  [/^glm[-_]/i, "zhipu"],
  // Qwen / Dashscope / Aliyun
  [/^qwen[-_/]?/i, "qwen"],
  [/\/qwen[-_]?/i, "qwen"],
  // Moonshot / Kimi
  [/\bkimi[-_]?/i, "moonshot"],
  [/^moonshot-?/i, "moonshot"],
  // Stepfun
  [/^step[-_]/i, "stepfun"],
  // Mistral
  [/^mistral[-_]/i, "mistral"],
  [/^mixtral[-_]/i, "mistral"],
  // Yi (零一万物) — no vendored logo in ProviderIcon today, leave fallback.
  // Google Gemini
  [/^gemini[-_]/i, "gemini"],
  // Meta Llama routed through a vendor, e.g. "meta-llama/…" — no specific
  // binding key in ProviderIcon; leave fallback.
];

export function inferModelBrandKey(modelId: string | null | undefined): string | undefined {
  if (!modelId) return undefined;
  const id = modelId.trim();
  if (!id) return undefined;
  const lower = id.toLowerCase();
  for (const [pattern, key] of PREFIX_TABLE) {
    if (pattern.test(lower)) return key;
  }
  return undefined;
}
