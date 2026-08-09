"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, Volume2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useTtsVoices, type TtsVoice } from "@/hooks/useTtsVoices";

/**
 * TTS voice switcher (composer toolbar).
 *
 * Mirrors PersonaSelector's chip + dropdown pattern. The selection is a
 * PER-USER preference persisted via `ui.tts_voice` (Settings › Voice). Value ""
 * means "system default" — the catalog's configured voice for the active model.
 * Voices are grouped by their catalog profile so multi-profile setups stay
 * readable.
 */
export default function VoiceSelector({
  value,
  onChange,
  placement = "top",
}: {
  /** Active voice string; "" = System default. */
  value: string;
  onChange: (voice: string) => void;
  placement?: "top" | "bottom";
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const { voices, loading } = useTtsVoices();

  // Close on outside click.
  useEffect(() => {
    if (!open) return;
    const handler = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const groups = useMemo(() => {
    const map = new Map<string, TtsVoice[]>();
    for (const v of voices) {
      const key = v.profile_name || v.provider || t("Voice");
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(v);
    }
    return Array.from(map.entries());
  }, [voices, t]);

  const selectedLabel =
    voices.find((v) => v.voice === value)?.label ||
    (value ? value : t("System default voice"));

  const menuPlacementClass =
    placement === "bottom" ? "top-full mt-1.5" : "bottom-full mb-1.5";

  const pick = (voice: string) => {
    onChange(voice);
    setOpen(false);
  };

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-label={t("Select voice")}
        aria-expanded={open}
        className={`inline-flex h-8 shrink-0 items-center rounded-lg px-2 text-[14px] font-medium transition-[background-color,color,transform] duration-150 active:scale-[0.97] ${
          open
            ? "bg-[var(--muted)] text-[var(--foreground)]"
            : value
              ? "text-[var(--primary)] hover:bg-[var(--primary)]/[0.07]"
              : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]/55 hover:text-[var(--foreground)]"
        }`}
      >
        <Volume2 size={16} strokeWidth={1.7} className="shrink-0" />
        <span
          className={`flex min-w-0 items-center gap-1 overflow-hidden whitespace-nowrap transition-[max-width,opacity,margin-left] duration-300 ease-out ${
            open || value
              ? "ml-1.5 max-w-[140px] opacity-100"
              : "ml-0 max-w-0 opacity-0"
          }`}
        >
          <span className="min-w-0 truncate">{value ? selectedLabel : t("Voice")}</span>
          <ChevronDown
            size={13}
            className={`shrink-0 transition-transform ${open ? "rotate-180" : ""}`}
          />
        </span>
      </button>

      {open && (
        <div
          className={`absolute right-0 z-50 ${menuPlacementClass} w-[min(280px,calc(100vw-32px))] overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--popover)] shadow-lg backdrop-blur-md`}
        >
          <div className="max-h-[280px] overflow-y-auto py-1">
            <button
              type="button"
              onClick={() => pick("")}
              className={`flex w-full items-center gap-2.5 px-3 py-1.5 text-left transition-colors active:bg-[var(--muted)]/70 ${
                !value ? "bg-[var(--primary)]/[0.06]" : "hover:bg-[var(--muted)]/45"
              }`}
            >
              <Volume2
                size={15}
                strokeWidth={1.7}
                className={`shrink-0 ${!value ? "text-[var(--primary)]" : "text-[var(--muted-foreground)]"}`}
              />
              <div className="min-w-0 flex-1">
                <div className="truncate text-[12.5px] font-medium leading-snug text-[var(--foreground)]">
                  {t("System default voice")}
                </div>
                <div className="truncate text-[11px] leading-snug text-[var(--muted-foreground)]">
                  {t("Use the catalog's configured voice")}
                </div>
              </div>
              {!value && (
                <Check size={14} strokeWidth={2} className="shrink-0 text-[var(--primary)]" />
              )}
            </button>

            {groups.map(([group, items]) => (
              <div key={group}>
                <div className="px-3 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
                  {group}
                </div>
                {items.map((v) => {
                  const selected = v.voice === value;
                  return (
                    <button
                      key={v.id}
                      type="button"
                      onClick={() => pick(v.voice)}
                      className={`flex w-full items-center gap-2.5 py-1.5 pl-6 pr-3 text-left transition-colors active:bg-[var(--muted)]/70 ${
                        selected
                          ? "bg-[var(--primary)]/[0.06]"
                          : "hover:bg-[var(--muted)]/45"
                      }`}
                    >
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-[12.5px] font-medium leading-snug text-[var(--foreground)]">
                          {v.label}
                        </div>
                        <div className="truncate text-[11px] leading-snug text-[var(--muted-foreground)]">
                          {v.voice}
                        </div>
                      </div>
                      {selected && (
                        <Check
                          size={14}
                          strokeWidth={2}
                          className="shrink-0 text-[var(--primary)]"
                        />
                      )}
                    </button>
                  );
                })}
              </div>
            ))}

            {loading && (
              <div className="px-3 py-4 text-center text-[12px] text-[var(--muted-foreground)]">
                {t("Loading voices...")}
              </div>
            )}
            {!loading && voices.length === 0 && (
              <div className="px-3 py-4 text-center text-[12px] text-[var(--muted-foreground)]">
                {t("No TTS voices are configured.")}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
