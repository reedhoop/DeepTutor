"use client";

import { useCallback, useEffect, useState } from "react";

import { apiFetch, apiUrl } from "@/lib/api";

export interface DigitalHumanSettings {
  /** Master switch for the digital-human widget. */
  enabled: boolean;
  /** "builtin" = built-in TTS-lip-synced SVG avatar; "iframe" = embed an
   *  external digital-human web UI (e.g. GMTalker) via `iframe_url`. */
  mode: "builtin" | "iframe";
  /** Absolute URL of the external digital-human web UI (iframe mode). */
  iframe_url: string;
}

export const DEFAULT_DIGITAL_HUMAN: DigitalHumanSettings = {
  enabled: false,
  mode: "builtin",
  iframe_url: "",
};

// Module-level cache so every surface shares one copy of the settings and no
// two widgets fire duplicate GET /settings round-trips (mirrors useTtsVoices).
const GLOBAL_EVENT = "deeptutor:digital-human-global";
let cachedSettings: DigitalHumanSettings | null = null;
let settingsInflight: Promise<DigitalHumanSettings> | null = null;

function normalize(raw: unknown): DigitalHumanSettings {
  const r = (raw ?? {}) as Record<string, unknown>;
  const mode = r.mode === "iframe" ? "iframe" : "builtin";
  return {
    enabled: Boolean(r.enabled),
    mode,
    iframe_url: typeof r.iframe_url === "string" ? r.iframe_url : "",
  };
}

function fetchSettings(): Promise<DigitalHumanSettings> {
  if (cachedSettings) return Promise.resolve(cachedSettings);
  if (!settingsInflight) {
    settingsInflight = apiFetch(apiUrl("/api/v1/settings"))
      .then((r) => (r.ok ? r.json() : null))
      .then((payload) => {
        cachedSettings = normalize(payload?.ui?.digital_human);
        return cachedSettings;
      })
      .catch(() => {
        cachedSettings = { ...DEFAULT_DIGITAL_HUMAN };
        return cachedSettings;
      })
      .finally(() => {
        settingsInflight = null;
      });
  }
  return settingsInflight;
}

export function useDigitalHumanSettings() {
  const [settings, setSettings] = useState<DigitalHumanSettings | null>(
    cachedSettings,
  );
  const [loading, setLoading] = useState<boolean>(cachedSettings === null);

  useEffect(() => {
    let active = true;
    fetchSettings().then((s) => {
      if (active) {
        setSettings(s);
        setLoading(false);
      }
    });
    // Live updates when another surface changes the settings.
    const onGlobal = (e: Event) => {
      const next = (e as CustomEvent).detail?.settings as
        | DigitalHumanSettings
        | undefined;
      if (next) setSettings(next);
    };
    window.addEventListener(GLOBAL_EVENT, onGlobal);
    return () => {
      active = false;
      window.removeEventListener(GLOBAL_EVENT, onGlobal);
    };
  }, []);

  const update = useCallback(
    async (patch: Partial<DigitalHumanSettings>) => {
      const next = normalize({
        ...(cachedSettings ?? DEFAULT_DIGITAL_HUMAN),
        ...patch,
      });
      // Optimistic local update + broadcast.
      cachedSettings = next;
      setSettings(next);
      window.dispatchEvent(
        new CustomEvent(GLOBAL_EVENT, { detail: { settings: next } }),
      );
      try {
        await apiFetch(apiUrl("/api/v1/settings/digital-human"), {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(next),
        });
      } catch {
        // Persistence failure: keep the optimistic value; the next page load
        // falls back to the server's copy.
      }
    },
    [],
  );

  return { settings, loading, update };
}
