"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { apiFetch, apiUrl } from "@/lib/api";

export type RecorderState = "idle" | "recording" | "transcribing";

// SenseVoice-style ASR models prefix transcripts with control tags (e.g.
// `<|zh|>`, `<|NEUTRAL|>`, `<|Basketball|>`). The backend now strips these, but
// we clean defensively here too so any provider/version returns usable text.
const SENSEVOICE_TAG = /<\|[^|>]*\|>/g;

export function cleanTranscript(text: string): string {
  return text
    .replace(SENSEVOICE_TAG, "")
    .replace(/\s+/g, " ")
    .trim();
}

/**
 * Microphone capture → backend transcription. Records via MediaRecorder, posts
 * the clip to ``/api/voice/stt`` (which uses the admin-configured STT
 * provider), and hands the transcript back through ``onTranscript``.
 */
export function useVoiceRecorder(onTranscript: (text: string) => void) {
  const [state, setState] = useState<RecorderState>("idle");
  const [error, setError] = useState<string | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const onTranscriptRef = useRef(onTranscript);
  onTranscriptRef.current = onTranscript;

  // Synchronous re-entrancy guard: `state` updates asynchronously, so two rapid
  // toggles both read "idle" and would otherwise open two mic streams (the first
  // being overwritten and leaked). Kept true from the moment start() runs until
  // React commits a non-idle state.
  const startingRef = useRef(false);
  useEffect(() => {
    if (state !== "idle") startingRef.current = false;
  }, [state]);

  const releaseStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }, []);

  const start = useCallback(async () => {
    if (state !== "idle" || startingRef.current) return;
    startingRef.current = true;
    setError(null);
    if (
      typeof navigator === "undefined" ||
      !navigator.mediaDevices?.getUserMedia ||
      typeof MediaRecorder === "undefined"
    ) {
      startingRef.current = false;
      setError("Recording is not supported in this browser.");
      return;
    }
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      startingRef.current = false;
      setError("Microphone permission denied.");
      return;
    }
    streamRef.current = stream;
    const recorder = new MediaRecorder(stream);
    chunksRef.current = [];
    recorder.ondataavailable = (event) => {
      if (event.data && event.data.size > 0) chunksRef.current.push(event.data);
    };
    recorder.onstop = async () => {
      const mimeType = recorder.mimeType || "audio/webm";
      releaseStream();
      const blob = new Blob(chunksRef.current, { type: mimeType });
      chunksRef.current = [];
      if (!blob.size) {
        setState("idle");
        return;
      }
      setState("transcribing");
      try {
        const ext = mimeType.includes("ogg")
          ? "ogg"
          : mimeType.includes("mp4")
            ? "mp4"
            : "webm";
        const form = new FormData();
        form.append("file", blob, `recording.${ext}`);
        const resp = await apiFetch(apiUrl("/api/voice/stt"), {
          method: "POST",
          body: form,
        });
        if (!resp.ok) {
          const detail = (await resp.json().catch(() => null)) as {
            detail?: string;
          } | null;
          throw new Error(
            detail?.detail || `Transcription failed (HTTP ${resp.status}).`,
          );
        }
        const data = (await resp.json()) as { text?: string };
        const text = cleanTranscript(data.text || "");
        if (text) onTranscriptRef.current(text);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Transcription failed.");
      } finally {
        setState("idle");
      }
    };
    recorder.start();
    recorderRef.current = recorder;
    setState("recording");
  }, [releaseStream, state]);

  const stop = useCallback(() => {
    const recorder = recorderRef.current;
    if (recorder && recorder.state !== "inactive") {
      recorder.stop(); // fires onstop → transcribe
    }
  }, []);

  const toggle = useCallback(() => {
    if (state === "recording") stop();
    else if (state === "idle") void start();
  }, [start, state, stop]);

  // Stop the mic if the component unmounts mid-recording.
  useEffect(() => {
    return () => {
      const recorder = recorderRef.current;
      if (recorder && recorder.state !== "inactive") recorder.stop();
      streamRef.current?.getTracks().forEach((track) => track.stop());
    };
  }, []);

  return { state, error, toggle, start, stop };
}
