"use client";

import { BookOpen } from "lucide-react";
import { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useKgTabOpener } from "@/context/KgTabContext";

interface KgOpenCTAProps {
  /** Concept name to focus the browser on (from the ```kgraph[concept] fence). */
  concept: string;
  /** Title to show on the CTA + the resulting tab. */
  title?: string;
  className?: string;
}

/**
 * Card-style CTA shown in-place of a ```kgraph fence in chat answers. Clicking
 * expands the right-hand SessionViewerPanel and opens (or focuses) a KG
 * browser tab focused on this concept's knowledge card.
 *
 * When no KgTabProvider is mounted (e.g. preview surfaces), the button is
 * disabled with a tooltip — we don't want a click to silently no-op.
 */
export default function KgOpenCTA({
  concept,
  title,
  className = "",
}: KgOpenCTAProps) {
  const { t } = useTranslation();
  const controller = useKgTabOpener();

  const id = useMemo(() => `kg:${concept || "browse"}`, [concept]);

  const onClick = useCallback(() => {
    if (!controller) return;
    controller.openTab({ id, concept, title: title || concept });
  }, [controller, id, concept, title]);

  const disabled = !controller;

  return (
    <div className={`my-3 ${className}`}>
      <button
        type="button"
        onClick={onClick}
        disabled={disabled}
        title={
          disabled
            ? t("Knowledge graph viewer is not available in this surface")
            : undefined
        }
        className={`group flex w-full items-center gap-3 rounded-xl border border-[var(--border)] bg-[var(--card)] px-4 py-3 text-left transition-colors ${
          disabled
            ? "cursor-not-allowed opacity-60"
            : "hover:border-[var(--primary)]/60 hover:bg-[var(--muted)]/30"
        }`}
      >
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[var(--primary)]/10 text-[var(--primary)]">
          <BookOpen size={18} strokeWidth={1.9} />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-medium text-[var(--foreground)]">
            {title || concept || t("Course knowledge graph")}
          </span>
          <span className="block text-xs text-[var(--muted-foreground)]">
            {t("Click to open this concept's knowledge card in the side viewer.")}
          </span>
        </span>
      </button>
    </div>
  );
}
