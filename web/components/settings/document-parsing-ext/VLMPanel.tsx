"use client";

import { useTranslation } from "react-i18next";

import {
  SettingRow,
  SettingSection,
  nativeSelectClass,
} from "@/components/settings/shared";
import { Toggle } from "@/components/settings/Toggle";
import { apiFetch, apiUrl } from "@/lib/api";

// -- VLM engine panel (shared by OvisOCR2 / PaddleOCR-VL) --
// Our custom engine — lives in the ext folder so the upstream page.tsx only
// imports and mounts it (a thin, rebase-safe glue line).
// Note: no "Model status" readiness row here — the settings payload's
// readiness dict deliberately skips remote VLM engines (live probing every
// request cost seconds). Use the Test button below for an on-demand probe.
export function VLMPanel({
  engineId,
  label,
  slice,
  busy,
  onSave,
}: {
  engineId: string;
  label: string;
  slice: Record<string, unknown>;
  busy: boolean;
  onSave: (patch: Record<string, unknown>) => void;
}) {
  const { t } = useTranslation();

  return (
    <SettingSection
      title={label}
      description={t(
        "End-to-end VLM document parsing via a self-hosted vLLM server. " +
          "No local model download.",
      )}
    >
      <SettingRow
        title={t("vLLM base URL")}
        description={t(
          "OpenAI-compatible endpoint, e.g. http://192.168.1.100:8000/v1",
        )}
        control={
          <input
            type="text"
            className={nativeSelectClass}
            defaultValue={String(slice.api_base_url || "")}
            placeholder="http://127.0.0.1:8000/v1"
            disabled={busy}
            onBlur={(e) =>
              onSave({ api_base_url: e.currentTarget.value.trim() || undefined })
            }
          />
        }
      />

      <SettingRow
        title={t("Model name")}
        description={t("The model id as registered in vLLM.")}
        control={
          <input
            type="text"
            className={nativeSelectClass}
            defaultValue={String(slice.model_name || "")}
            disabled={busy}
            onBlur={(e) =>
              onSave({ model_name: e.currentTarget.value.trim() || undefined })
            }
          />
        }
      />

      {engineId === "paddleocr_vl" && (
        <SettingRow
          title={t("Layout-assisted parsing (PP-DocLayoutV2)")}
          description={t(
            "Region-by-region parsing with task prompts (OCR / Table / Formula / Chart). Falls back to whole-page if PaddleOCR isn't installed.",
          )}
          control={
            <Toggle
              checked={slice.enable_layout !== false}
              disabled={busy}
              onChange={(v) => onSave({ enable_layout: v })}
            />
          }
        />
      )}

      <SettingRow
        title={t("API key")}
        description={t('Leave empty if vLLM runs without auth ("EMPTY").')}
        control={
          <input
            type="password"
            className={nativeSelectClass}
            defaultValue={""}
            placeholder="(unchanged)"
            disabled={busy}
            onBlur={(e) => {
              const v = e.currentTarget.value;
              onSave({ api_token: v === "" ? null : v });
            }}
          />
        }
      />

      <SettingRow
        title={t("Image DPI")}
        description={t("Render resolution for PDF pages.")}
        control={
          <input
            type="number"
            className={nativeSelectClass}
            min={72}
            max={600}
            defaultValue={Number(slice.image_dpi) || 200}
            disabled={busy}
            onBlur={(e) =>
              onSave({ image_dpi: Number(e.currentTarget.value) || undefined })
            }
          />
        }
      />

      <SettingRow
        title={t("Max tokens")}
        description={t("Single page output limit.")}
        control={
          <input
            type="number"
            className={nativeSelectClass}
            min={256}
            max={32768}
            defaultValue={Number(slice.max_tokens) || 4096}
            disabled={busy}
            onBlur={(e) =>
              onSave({ max_tokens: Number(e.currentTarget.value) || undefined })
            }
          />
        }
      />

      <SettingRow
        title={t("Temperature")}
        description={t("0 = deterministic, higher = more creative.")}
        control={
          <input
            type="number"
            className={nativeSelectClass}
            min={0}
            max={2}
            step={0.1}
            defaultValue={Number(slice.temperature) ?? 0.0}
            disabled={busy}
            onBlur={(e) => {
              const value = Number(e.currentTarget.value);
              onSave({ temperature: Number.isFinite(value) ? value : undefined });
            }}
          />
        }
      />

      <SettingRow
        title={t("Max concurrency")}
        description={t("Parallel page requests to vLLM.")}
        control={
          <input
            type="number"
            className={nativeSelectClass}
            min={1}
            max={16}
            defaultValue={Number(slice.max_concurrency) || 4}
            disabled={busy}
            onBlur={(e) =>
              onSave({
                max_concurrency: Number(e.currentTarget.value) || undefined,
              })
            }
          />
        }
      />

      <SettingRow
        title={t("Extra prompt")}
        description={t("Appended after the built-in OCR instruction.")}
        control={
          <input
            type="text"
            className={nativeSelectClass}
            defaultValue={String(slice.extra_prompt || "")}
            disabled={busy}
            onBlur={(e) =>
              onSave({ extra_prompt: e.currentTarget.value || undefined })
            }
          />
        }
      />

      <div className="flex items-center gap-3 pt-2">
        <button
          type="button"
          disabled={busy}
          className="rounded-lg border border-[var(--border)] px-4 py-2 text-[12px] font-medium transition-colors hover:bg-[var(--card)] disabled:opacity-60"
          onClick={async () => {
            try {
              const response = await apiFetch(
                apiUrl("/api/v1/settings/document-parsing/test"),
                {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ engine: engineId }),
                },
              );
              const payload = await response
                .json()
                .catch(() => ({ ok: false, message: "Unexpected response" }));
              alert(
                payload.ok
                  ? "Test passed: engine is ready."
                  : `Test failed: ${payload.message || "Unknown error"}`,
              );
            } catch {
              alert("Test request failed.");
            }
          }}
        >
          {t("Test")}
        </button>
      </div>
    </SettingSection>
  );
}
