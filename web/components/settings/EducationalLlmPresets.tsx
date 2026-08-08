"use client";

import { useEffect, useState } from "react";
import { CheckCircle2, Loader2, Plus, Sparkles } from "lucide-react";

import { apiFetch, apiUrl } from "@/lib/api";
import { useSettings } from "./SettingsContext";

type Preset = {
  id: string;
  name: string;
  description: string;
  binding: string;
  base_url: string;
  models: { model: string; name: string; context_window: string }[];
};

export function EducationalLlmPresets() {
  const { language, reloadSettings, setToast } = useSettings();
  const tr = (zh: string, en: string) => (language === "zh" ? zh : en);

  const [presets, setPresets] = useState<Preset[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [applyingId, setApplyingId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await apiFetch(apiUrl("/api/v1/settings/llm-presets"));
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = (await res.json()) as { presets: Preset[] };
        if (!cancelled) setPresets(data.presets ?? []);
      } catch (err) {
        if (!cancelled)
          setError(
            err instanceof Error ? err.message : "Failed to load presets",
          );
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const applyPreset = async (presetId: string) => {
    setApplyingId(presetId);
    try {
      const res = await apiFetch(apiUrl("/api/v1/settings/llm-presets/apply"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ preset_id: presetId }),
      });
      if (!res.ok) {
        const detail = await res.text().catch(() => "");
        throw new Error(detail || `HTTP ${res.status}`);
      }
      await reloadSettings();
      setToast(tr("已添加并设为当前模型", "Added and set as the active model"));
    } catch (err) {
      setToast(
        tr("添加失败：", "Failed to add: ") +
          (err instanceof Error ? err.message : String(err)),
      );
    } finally {
      setApplyingId(null);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-[var(--border)] px-4 py-3 text-[12px] text-[var(--muted-foreground)]">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        {tr("正在加载教育模型预设…", "Loading educational model presets…")}
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-xl border border-[var(--border)] px-4 py-3 text-[12px] text-[var(--muted-foreground)]">
        {tr("无法加载预设：", "Could not load presets: ")}
        {error}
      </div>
    );
  }

  if (presets.length === 0) return null;

  return (
    <div className="rounded-xl border border-[var(--border)] p-5">
      <div className="mb-3 flex items-center gap-2 text-[13px] font-medium text-[var(--foreground)]">
        <Sparkles className="h-4 w-4" />
        {tr("教育模型预设", "Educational Model Presets")}
      </div>
      <p className="mb-4 text-[12px] leading-relaxed text-[var(--muted-foreground)]">
        {tr(
          "一键添加面向教育的 LLM 配置（含正确的接口地址与模型名），添加后填入 API Key 即可使用。",
          "One-click add education-oriented LLM profiles (correct endpoint and model name included). Fill in your API key afterwards.",
        )}
      </p>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {presets.map((preset) => {
          const modelName = preset.models[0]?.model ?? "";
          return (
            <div
              key={preset.id}
              className="flex flex-col rounded-lg border border-[var(--border)]/70 bg-[var(--card)]/40 p-3.5"
            >
              <div className="text-[13px] font-semibold text-[var(--foreground)]">
                {preset.name}
              </div>
              <p className="mt-1 line-clamp-3 flex-1 text-[11px] leading-relaxed text-[var(--muted-foreground)]">
                {preset.description}
              </p>
              <div className="mt-2 space-y-0.5 font-mono text-[10.5px] text-[var(--muted-foreground)]/80">
                <div className="truncate" title={modelName}>
                  {modelName}
                </div>
                <div className="truncate" title={preset.base_url}>
                  {preset.base_url}
                </div>
              </div>
              <button
                type="button"
                disabled={applyingId === preset.id}
                onClick={() => applyPreset(preset.id)}
                className="mt-3 inline-flex items-center justify-center gap-1.5 rounded-lg border border-[var(--primary)]/30 bg-[var(--primary)]/5 px-2.5 py-1.5 text-[12px] font-medium text-[var(--primary)] transition-colors hover:border-[var(--primary)]/60 hover:bg-[var(--primary)]/10 disabled:opacity-50"
              >
                {applyingId === preset.id ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Plus className="h-3.5 w-3.5" />
                )}
                {tr("添加为当前模型", "Add as active model")}
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
