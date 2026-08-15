"use client";

import { useTranslation } from "react-i18next";

import {
  SettingRow,
  SettingSection,
  nativeSelectClass,
  selectOptionClass,
} from "@/components/settings/shared";
import { Toggle } from "@/components/settings/Toggle";

import { ReadinessNotice, type Readiness } from "./badges";

// -- PP-StructureV3 local-pipeline panel --
// Our custom engine — lives in the ext folder so the upstream page.tsx only
// imports and mounts it. `NotInstalledSection` is upstream infra kept in the
// page, so it is passed in as a prop (keeps this file dependency-free).
export function PPStructureV3Panel({
  slice,
  readiness,
  available,
  busy,
  onInstalled,
  onSave,
  NotInstalledSection,
}: {
  slice: Record<string, unknown>;
  readiness?: Readiness;
  available: boolean;
  busy: boolean;
  onInstalled: () => void;
  onSave: (patch: Record<string, unknown>) => void;
  NotInstalledSection: (props: {
    engineId: string;
    title: string;
    onInstalled: () => void;
  }) => React.ReactElement;
}) {
  const { t } = useTranslation();
  const device = typeof slice.device === "string" ? slice.device : "gpu";
  const lang = typeof slice.lang === "string" ? slice.lang : "ch";
  const allowDownload = Boolean(slice.allow_local_model_download);

  if (!available) {
    return (
      <NotInstalledSection
        engineId="pp_structurev3"
        title={t("PP-StructureV3")}
        onInstalled={onInstalled}
      />
    );
  }

  return (
    <SettingSection
      title={t("PP-StructureV3")}
      description={t(
        "Local PaddleOCR pipeline (layout, tables, formulas, charts, seals). No vLLM server. Downloads PaddleOCR weights on first run.",
      )}
    >
      <ReadinessNotice readiness={readiness} />
      <SettingRow
        title={t("Allow automatic model download")}
        description={t(
          "Off by default. When off, parsing fails with guidance instead of silently downloading models.",
        )}
        control={
          <Toggle
            checked={allowDownload}
            disabled={busy}
            onChange={(v) => onSave({ allow_local_model_download: v })}
          />
        }
      />
      <SettingRow
        title={t("Device")}
        control={
          <select
            className={`${nativeSelectClass} w-28`}
            value={device}
            disabled={busy}
            onChange={(e) => onSave({ device: e.target.value })}
          >
            {["gpu", "cpu"].map((d) => (
              <option key={d} className={selectOptionClass} value={d}>
                {d}
              </option>
            ))}
          </select>
        }
      />
      <SettingRow
        title={t("Language")}
        control={
          <select
            className={`${nativeSelectClass} w-28`}
            value={lang}
            disabled={busy}
            onChange={(e) => onSave({ lang: e.target.value })}
          >
            {["ch", "en"].map((l) => (
              <option key={l} className={selectOptionClass} value={l}>
                {l}
              </option>
            ))}
          </select>
        }
      />
      <SettingRow
        title={t("Formula recognition")}
        control={
          <Toggle
            checked={slice.use_formula_recognition !== false}
            disabled={busy}
            onChange={(v) => onSave({ use_formula_recognition: v })}
          />
        }
      />
      <SettingRow
        title={t("Chart recognition")}
        control={
          <Toggle
            checked={slice.use_chart_recognition !== false}
            disabled={busy}
            onChange={(v) => onSave({ use_chart_recognition: v })}
          />
        }
      />
      <SettingRow
        title={t("Seal recognition")}
        control={
          <Toggle
            checked={slice.use_seal_recognition !== false}
            disabled={busy}
            onChange={(v) => onSave({ use_seal_recognition: v })}
          />
        }
      />
      <SettingRow
        title={t("Document orientation classify")}
        description={t("Correct upside-down scans before parsing.")}
        control={
          <Toggle
            checked={Boolean(slice.use_doc_orientation_classify)}
            disabled={busy}
            onChange={(v) => onSave({ use_doc_orientation_classify: v })}
          />
        }
      />
      <SettingRow
        title={t("Document unwarping")}
        description={t("Dewarp curved / photographed pages.")}
        control={
          <Toggle
            checked={Boolean(slice.use_doc_unwarping)}
            disabled={busy}
            onChange={(v) => onSave({ use_doc_unwarping: v })}
          />
        }
      />
      <SettingRow
        title={t("Textline orientation")}
        description={t("Correct rotated text lines.")}
        control={
          <Toggle
            checked={Boolean(slice.use_textline_orientation)}
            disabled={busy}
            onChange={(v) => onSave({ use_textline_orientation: v })}
          />
        }
      />
      <SettingRow
        title={t("Layout threshold")}
        description={t("0.0–1.0. Lower keeps more regions.")}
        control={
          <input
            type="number"
            className={nativeSelectClass}
            min={0}
            max={1}
            step={0.05}
            defaultValue={
              Number.isFinite(Number(slice.layout_threshold))
                ? Number(slice.layout_threshold)
                : 0.5
            }
            disabled={busy}
            onBlur={(e) => {
              const value = Number(e.currentTarget.value);
              onSave({ layout_threshold: Number.isFinite(value) ? value : undefined });
            }}
          />
        }
      />
      <SettingRow
        title={t("Layout NMS")}
        description={t("Suppress overlapping region boxes.")}
        control={
          <Toggle
            checked={slice.layout_nms !== false}
            disabled={busy}
            onChange={(v) => onSave({ layout_nms: v })}
          />
        }
      />
    </SettingSection>
  );
}
