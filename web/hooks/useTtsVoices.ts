"use client";

import { useCallback, useEffect, useState } from "react";

import { apiFetch, apiUrl } from "@/lib/api";

export interface TtsVoice {
  /** Stable unique id: `${profile_id}::${voice}`. */
  id: string;
  /** Provider `voice` param sent to `/api/v1/voice/tts`. */
  voice: string;
  /** Human-readable label (preset name or voice string). */
  label: string;
  /** Catalog model id this voice speaks through. */
  model: string;
  /** Canonical provider key (e.g. "siliconflow"). */
  provider: string;
  profile_id: string;
  profile_name: string;
}

// ----- available voices list (module-cached so every surface shares one copy) -----
let voicesCache: TtsVoice[] | null = null;
let voicesInflight: Promise<TtsVoice[]> | null = null;

async function fetchVoices(): Promise<TtsVoice[]> {
  if (voicesCache) return voicesCache;
  if (!voicesInflight) {
    voicesInflight = apiFetch(apiUrl("/api/v1/voice/voices"))
      .then((r) => (r.ok ? r.json() : { voices: [] }))
      .then((d: { voices?: TtsVoice[] }) => {
        voicesCache = d.voices ?? [];
        return voicesCache;
      })
      .catch(() => {
        voicesCache = [];
        return [];
      })
      .finally(() => {
        voicesInflight = null;
      });
  }
  return voicesInflight;
}

export function useTtsVoices() {
  const [voices, setVoices] = useState<TtsVoice[]>(voicesCache ?? []);
  const [loading, setLoading] = useState<boolean>(voicesCache === null);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    let active = true;
    fetchVoices()
      .then((v) => active && setVoices(v))
      .catch((e) => active && setError(e instanceof Error ? e : new Error(String(e))))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, []);

  return { voices, loading, error };
}

// ----- user's selected voice (persisted per-user via ui.tts_voice) -----
// null = not loaded yet; "" = explicitly "system default"; otherwise the voice string.
const GLOBAL_EVENT = "deeptutor:tts-voice-global";
let cachedGlobalVoice: string | null = null;
let voiceInflight: Promise<string | null> | null = null;

function fetchGlobalVoice(): Promise<string | null> {
  if (cachedGlobalVoice !== null) return Promise.resolve(cachedGlobalVoice);
  if (!voiceInflight) {
    voiceInflight = apiFetch(apiUrl("/api/v1/settings"))
      .then((r) => (r.ok ? r.json() : null))
      .then((payload) => {
        const v = payload?.ui?.tts_voice ?? null;
        cachedGlobalVoice = v == null ? "" : String(v);
        return cachedGlobalVoice;
      })
      .catch(() => {
        cachedGlobalVoice = "";
        return "";
      })
      .finally(() => {
        voiceInflight = null;
      });
  }
  return voiceInflight;
}

/**
 * Chat-surface hook: the user's preferred TTS voice plus the setter. `value` of
 * "" means "use the catalog's default voice". Selecting a voice writes it to
 * `ui.tts_voice` and broadcasts a global event so all PlayAudioButtons update.
 */
export function useTtsVoicePreference() {
  const [value, setVal] = useState<string | null>(cachedGlobalVoice);
  const [loading, setLoading] = useState<boolean>(cachedGlobalVoice === null);

  useEffect(() => {
    let active = true;
    fetchGlobalVoice().then((v) => {
      if (active) {
        setVal(v);
        setLoading(false);
      }
    });
    // Live updates when another surface changes the selection.
    const onGlobal = (e: Event) =>
      setVal(String((e as CustomEvent).detail?.value ?? ""));
    window.addEventListener(GLOBAL_EVENT, onGlobal);
    return () => {
      active = false;
      window.removeEventListener(GLOBAL_EVENT, onGlobal);
    };
  }, []);

  const setValue = useCallback(async (next: string | null) => {
    setVal(next ?? "");
    cachedGlobalVoice = next ?? "";
    if (typeof window !== "undefined") {
      window.dispatchEvent(
        new CustomEvent(GLOBAL_EVENT, { detail: { value: next ?? "" } }),
      );
    }
    await apiFetch(apiUrl("/api/v1/settings/tts-voice"), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tts_voice: next }),
    });
  }, []);

  return { value, setValue, loading };
}
