"use client";

import { CheckCircle2, XCircle } from "lucide-react";
import { useTranslation } from "react-i18next";

/* ── Engine-card badges (our additions) ─────────────────────────────────── */

export function EngineVersionBadge({ version }: { version?: string | null }) {
  if (!version) return null;
  return (
    <span className="rounded-full bg-[var(--muted)] px-1.5 py-0.5 text-[9.5px] font-mono text-[var(--muted-foreground)]">
      v{version}
    </span>
  );
}

export function EngineReadyBadge({
  available,
  ready,
}: {
  available: boolean;
  ready?: boolean;
}) {
  // Hook must run unconditionally — a card's `ready` flips after model
  // downloads, and a conditional hook would crash React ("fewer hooks").
  const { t } = useTranslation();
  if (available && ready === false) {
    return (
      <span className="rounded-full border border-amber-400/50 bg-amber-400/10 px-2 py-0.5 text-[10px] text-amber-600 dark:text-amber-400">
        {t("Needs models")}
      </span>
    );
  }
  return null;
}

/* ── Readiness status primitives (copied locally so this ext folder is
   dependency-free; the page still keeps its own upstream copies for the
   built-in engine panels). ─────────────────────────────────────────────── */

export type Readiness = { ready: boolean; reason: string; message: string };

export function ReadinessNotice({ readiness }: { readiness?: Readiness }) {
  const { t } = useTranslation();
  if (!readiness) return null;
  if (readiness.ready) {
    return (
      <div className="flex items-center gap-1.5 px-1 py-4 text-[12px] text-emerald-600 dark:text-emerald-400">
        <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
        {t("Ready to parse.")}
      </div>
    );
  }
  return (
    <div className="px-1 py-4">
      <div className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2.5 text-[12px] leading-relaxed text-amber-700 dark:text-amber-300">
        <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <span className="min-w-0">{readiness.message}</span>
      </div>
    </div>
  );
}
