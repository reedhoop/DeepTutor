"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  AudioLines,
  Bot,
  Loader2,
  Play,
  Settings2,
  Sparkles,
  X,
  type LucideIcon,
} from "lucide-react";

import { apiFetch, apiUrl } from "@/lib/api";
import {
  useDigitalHumanSettings,
  type DigitalHumanSettings,
} from "@/hooks/useDigitalHuman";

/** Chinese-first inline translation helper (mirrors DrawPad) — keeps the
 *  widget off web/locales/{en,zh}/app.json and the i18n parity gate. */
const tr = (zh: string, _en: string) => zh;

// ---------------------------------------------------------------------------
// Global media-play capture. TTS playback in this app uses `new Audio(url)`
// (e.g. PlayAudioButton), i.e. a media element *detached from the DOM* whose
// events never bubble to document/window. We wrap HTMLMediaElement.prototype
// .play once so every audio/video start anywhere in the app dispatches a
// window event the avatar can lip-sync to — zero changes to existing code.
// ---------------------------------------------------------------------------
const MEDIA_PLAY_EVENT = "deeptutor:media-play";
const MEDIA_STOP_EVENT = "deeptutor:media-stop";
const SAMPLE_TTS =
  "你好，我是你的 AI 学习伙伴。我们可以一起讨论这道几何题，你先把思路画给我看看？";

let mediaPatchInstalled = false;
let originalPlay: ((...args: unknown[]) => Promise<void>) | null = null;

function installMediaPlayPatch() {
  if (mediaPatchInstalled || typeof window === "undefined") return;
  const proto = HTMLMediaElement.prototype as unknown as {
    play: (...args: unknown[]) => Promise<void>;
  };
  // Keep the RAW native method (not bound): the wrapper below must re-invoke it
  // with `this` = the media instance. Binding it to the prototype object would
  // make the native play() run with an invalid `this` → TypeError: Illegal
  // invocation on every audio.play().
  originalPlay = proto.play;
  proto.play = function (this: HTMLMediaElement, ...args: unknown[]) {
    const el = this;
    const result = originalPlay!.call(this, ...args);
    // Lip-sync only for audio playback — video plays shouldn't move the mouth.
    if (el.tagName === "AUDIO") {
      window.dispatchEvent(
        new CustomEvent(MEDIA_PLAY_EVENT, { detail: { el } }),
      );
      if (!el.dataset.dhTracked) {
        el.dataset.dhTracked = "1";
        el.addEventListener("pause", () =>
          window.dispatchEvent(new Event(MEDIA_STOP_EVENT)),
        );
        el.addEventListener("ended", () =>
          window.dispatchEvent(new Event(MEDIA_STOP_EVENT)),
        );
      }
    }
    return result;
  };
  mediaPatchInstalled = true;
}

function restoreMediaPlayPatch() {
  if (mediaPatchInstalled && originalPlay) {
    const proto = HTMLMediaElement.prototype as unknown as {
      play: (...args: unknown[]) => Promise<void>;
    };
    if (proto.play !== originalPlay) proto.play = originalPlay;
    mediaPatchInstalled = false;
    originalPlay = null;
  }
}

/** Friendly built-in SVG tutor avatar. The mouth ellipse scales vertically
 *  while `speaking` via the `dh-mouth` keyframes (pure CSS, no timer). */
function BuiltinAvatar({ speaking }: { speaking: boolean }) {
  return (
    <svg
      viewBox="0 0 160 150"
      role="img"
      aria-label={tr("数字人形象", "Digital tutor avatar")}
      className="h-full w-full"
    >
      <style>{`
        @keyframes dh-mouth {
          0%   { transform: scaleY(0.35); }
          100% { transform: scaleY(1); }
        }
        .dh-mouth-open {
          animation: dh-mouth 0.32s ease-in-out infinite alternate;
          transform-box: fill-box;
          transform-origin: center;
        }
      `}</style>
      {/* hair */}
      <ellipse cx="80" cy="38" rx="42" ry="30" fill="#3b4a5e" />
      <path
        d="M38 46 Q38 14 80 12 Q122 14 122 46 Q112 30 96 27 Q84 32 80 30 Q76 32 64 27 Q48 30 38 46 Z"
        fill="#2c3a4d"
      />
      {/* face */}
      <circle cx="80" cy="72" r="40" fill="#ffe0c2" />
      {/* ears */}
      <circle cx="42" cy="74" r="8" fill="#ffd3ab" />
      <circle cx="118" cy="74" r="8" fill="#ffd3ab" />
      {/* eyes */}
      <circle cx="66" cy="68" r="4.5" fill="#24303d" />
      <circle cx="94" cy="68" r="4.5" fill="#24303d" />
      <circle cx="68.2" cy="66.2" r="1.5" fill="#fff" />
      <circle cx="96.2" cy="66.2" r="1.5" fill="#fff" />
      {/* brows */}
      <path d="M58 58 Q66 54 74 58" stroke="#24303d" strokeWidth="2" fill="none" strokeLinecap="round" />
      <path d="M86 58 Q94 54 102 58" stroke="#24303d" strokeWidth="2" fill="none" strokeLinecap="round" />
      {/* cheeks */}
      <circle cx="56" cy="82" r="5" fill="#ffb88c" opacity="0.6" />
      <circle cx="104" cy="82" r="5" fill="#ffb88c" opacity="0.6" />
      {/* nose */}
      <path d="M78 74 Q80 80 82 74" stroke="#e8a878" strokeWidth="2" fill="none" strokeLinecap="round" />
      {/* mouth — animates while speaking */}
      <ellipse
        cx="80"
        cy="90"
        rx="9"
        ry="5"
        fill="#c2574f"
        className={speaking ? "dh-mouth-open" : undefined}
      />
      {/* body hint */}
      <path d="M56 112 Q80 104 104 112 L112 150 L48 150 Z" fill="#6d8fc4" opacity="0.9" />
    </svg>
  );
}

function FloatingButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={tr("数字人", "Digital human")}
      aria-label={tr("数字人", "Digital human")}
      className="flex h-11 w-11 items-center justify-center rounded-full border border-[var(--border)]/60 bg-[var(--card)] text-[var(--muted-foreground)] shadow-[0_4px_18px_-6px_rgba(0,0,0,0.25)] backdrop-blur-md transition-[color,transform] hover:text-[var(--primary)] active:scale-90"
    >
      <Sparkles size={19} strokeWidth={1.8} />
    </button>
  );
}

function PanelButton({
  icon: Icon,
  label,
  onClick,
  active,
  disabled,
}: {
  icon: LucideIcon;
  label: string;
  onClick: () => void;
  active?: boolean;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={label}
      aria-label={label}
      className={`flex h-8 w-8 items-center justify-center rounded-lg transition-colors active:scale-90 disabled:cursor-not-allowed disabled:opacity-40 ${
        active
          ? "bg-[var(--primary)]/[0.1] text-[var(--primary)]"
          : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]/55 hover:text-[var(--foreground)]"
      }`}
    >
      <Icon size={16} strokeWidth={1.8} />
    </button>
  );
}

export function DigitalHumanWidget() {
  const { settings, loading, update } = useDigitalHumanSettings();
  const [open, setOpen] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [testing, setTesting] = useState(false);
  const [draftUrl, setDraftUrl] = useState("");

  // Avatar starts from the persisted iframe_url once settings arrive.
  const draftUrlRef = useRef("");
  const setDraft = (v: string) => {
    draftUrlRef.current = v;
    setDraftUrl(v);
  };
  useEffect(() => {
    if (settings) {
      setDraft(settings.iframe_url);
      setSpeaking(false);
    }
  }, [settings]);

  // Install the media-play patch while the widget is alive (restored on unmount).
  useEffect(() => {
    installMediaPlayPatch();
    const onPlay = (e: Event) => {
      const el = (e as CustomEvent).detail?.el as HTMLAudioElement | undefined;
      setSpeaking(true);
      // Safety stop: if the media element ends without our stop listeners
      // firing (e.g. killed mid-stream), cap the mouth animation.
      if (el && Number.isFinite(el.duration) && el.duration > 0) {
        window.setTimeout(() => setSpeaking(false), el.duration * 1000 + 800);
      }
    };
    const onStop = () => setSpeaking(false);
    window.addEventListener(MEDIA_PLAY_EVENT, onPlay);
    window.addEventListener(MEDIA_STOP_EVENT, onStop);
    return () => {
      window.removeEventListener(MEDIA_PLAY_EVENT, onPlay);
      window.removeEventListener(MEDIA_STOP_EVENT, onStop);
      restoreMediaPlayPatch();
    };
  }, []);

  const s: DigitalHumanSettings =
    settings ?? { enabled: false, mode: "builtin", iframe_url: "" };

  const playSample = useCallback(async () => {
    setTesting(true);
    try {
      const resp = await apiFetch(apiUrl("/api/v1/voice/tts"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: SAMPLE_TTS }),
      });
      if (!resp.ok) return;
      const blob = await resp.blob();
      const audio = new Audio(URL.createObjectURL(blob));
      void audio.play();
    } finally {
      setTesting(false);
    }
  }, []);

  const iframeMode = s.mode === "iframe" && !!s.iframe_url.trim();

  return (
    <>
      <div className="fixed bottom-24 right-5 z-[80]">
        <AnimatePresence>
          {open ? (
            <motion.div
              key="panel"
              className="absolute bottom-14 right-0 w-[300px] overflow-hidden rounded-2xl border border-[var(--border)]/70 bg-[var(--popover)] shadow-2xl backdrop-blur-md"
              style={{ transformOrigin: "bottom right" }}
              initial={{ opacity: 0, y: 8, scale: 0.96 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 6, scale: 0.97 }}
              transition={{ duration: 0.16, ease: [0.16, 1, 0.3, 1] }}
            >
              <div className="flex items-center justify-between border-b border-[var(--border)]/60 px-3 py-2">
                <div className="flex items-center gap-2 text-[13px] font-medium text-[var(--foreground)]">
                  <Bot size={15} strokeWidth={1.8} className="text-[var(--primary)]" />
                  {tr("数字人", "Digital human")}
                  {speaking && (
                    <span className="inline-flex items-center gap-1 rounded-full bg-[var(--primary)]/[0.1] px-1.5 py-0.5 text-[10px] font-medium text-[var(--primary)]">
                      <AudioLines size={10} strokeWidth={2} />
                      {tr("说话中", "Speaking")}
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    onClick={() => setOpen(false)}
                    aria-label={tr("收起", "Collapse")}
                    className="flex h-7 w-7 items-center justify-center rounded-lg text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)]/55 hover:text-[var(--foreground)]"
                  >
                    <X size={15} strokeWidth={1.9} />
                  </button>
                </div>
              </div>

              {/* Avatar stage */}
              <div className="px-3 pt-3">
                <div className="relative h-40 overflow-hidden rounded-xl border border-[var(--border)]/60 bg-gradient-to-b from-[var(--primary)]/[0.06] to-transparent">
                  {iframeMode ? (
                    <iframe
                      src={s.iframe_url.trim()}
                      title={tr("数字人", "Digital human")}
                      className="h-full w-full border-0"
                      sandbox="allow-scripts allow-same-origin allow-forms allow-modals"
                      allow="microphone; autoplay"
                    />
                  ) : (
                    <BuiltinAvatar speaking={speaking && s.enabled} />
                  )}
                  {!s.enabled && (
                    <div className="absolute inset-0 flex items-center justify-center bg-[var(--card)]/55 text-[12px] text-[var(--muted-foreground)] backdrop-blur-[1px]">
                      {tr("数字人已停用", "Digital human is disabled")}
                    </div>
                  )}
                </div>
              </div>

              {/* Controls */}
              <div className="space-y-2.5 px-3 py-3">
                <label className="flex cursor-pointer items-center justify-between gap-2 text-[12.5px] text-[var(--foreground)]">
                  <span>{tr("启用数字人", "Enable digital human")}</span>
                  <button
                    type="button"
                    role="switch"
                    aria-checked={s.enabled}
                    disabled={loading}
                    onClick={() => update({ enabled: !s.enabled })}
                    className={`relative h-5 w-9 shrink-0 rounded-full transition-colors disabled:opacity-40 ${
                      s.enabled ? "bg-[var(--primary)]" : "bg-[var(--muted)]"
                    }`}
                  >
                    <span
                      className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-[left] ${
                        s.enabled ? "left-[18px]" : "left-0.5"
                      }`}
                    />
                  </button>
                </label>

                <div className="flex items-center justify-between gap-2 text-[12.5px] text-[var(--foreground)]">
                  <span>{tr("形象", "Avatar")}</span>
                  <select
                    value={s.mode}
                    disabled={loading}
                    onChange={(e) =>
                      update({ mode: e.target.value as "builtin" | "iframe" })
                    }
                    className="h-7 rounded-lg border border-[var(--border)]/60 bg-[var(--card)] px-2 text-[12px] text-[var(--foreground)] outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)]/40"
                  >
                    <option value="builtin">
                      {tr("内置形象（随 TTS 嘴型）", "Built-in avatar (TTS lip-sync)")}
                    </option>
                    <option value="iframe">
                      {tr("GMTalker / 外部数字人 iframe", "GMTalker / external iframe")}
                    </option>
                  </select>
                </div>

                {s.mode === "iframe" && (
                  <div className="space-y-1">
                    <input
                      value={draftUrl}
                      onChange={(e) => setDraft(e.target.value)}
                      placeholder={tr("http://127.0.0.1:8231", "http://127.0.0.1:8231")}
                      className="h-7 w-full rounded-lg border border-[var(--border)]/60 bg-[var(--card)] px-2 text-[12px] text-[var(--foreground)] outline-none placeholder:text-[var(--muted-foreground)] focus-visible:ring-2 focus-visible:ring-[var(--primary)]/40"
                    />
                    <button
                      type="button"
                      onClick={() => update({ iframe_url: draftUrl.trim() })}
                      disabled={draftUrl === s.iframe_url}
                      className="h-7 w-full rounded-lg bg-[var(--muted)] text-[12px] font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--muted)]/70 disabled:opacity-40"
                    >
                      {tr("保存 iframe 地址", "Save iframe URL")}
                    </button>
                  </div>
                )}

                <div className="flex items-center gap-2 pt-1">
                  <PanelButton
                    icon={Play}
                    label={tr("试听（验证嘴型）", "Preview TTS (verify lip-sync)")}
                    onClick={playSample}
                    disabled={testing || !s.enabled}
                  />
                  {testing && (
                    <Loader2 size={14} strokeWidth={2} className="animate-spin text-[var(--muted-foreground)]" />
                  )}
                  <span className="text-[11px] leading-snug text-[var(--muted-foreground)]">
                    {tr(
                      "试听会播放一句 TTS，观察数字人嘴型是否随语音开合。",
                      "Preview plays one TTS line so you can see the avatar's mouth move with the audio.",
                    )}
                  </span>
                </div>

                {s.mode === "iframe" && !s.iframe_url.trim() && (
                  <p className="text-[11px] leading-snug text-[var(--muted-foreground)]">
                    {tr(
                      "填入 GMTalker 网页地址后保存即可切换为外部数字人（部署步骤见 reports/er8_gmtalker_deploy.md）。",
                      "Paste your GMTalker web URL and save to switch to the external avatar (see reports/er8_gmtalker_deploy.md).",
                    )}
                  </p>
                )}
              </div>
            </motion.div>
          ) : null}
        </AnimatePresence>

        {!open && <FloatingButton onClick={() => setOpen(true)} />}
        {open && (
          <SettingsIconButton
            onClick={() => setOpen(false)}
            title={tr("收起", "Collapse")}
          />
        )}
      </div>
    </>
  );
}

function SettingsIconButton({
  onClick,
  title,
}: {
  onClick: () => void;
  title: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      aria-label={title}
      className="flex h-11 w-11 items-center justify-center rounded-full border border-[var(--border)]/60 bg-[var(--card)] text-[var(--primary)] shadow-[0_4px_18px_-6px_rgba(0,0,0,0.25)] backdrop-blur-md transition-transform active:scale-90"
    >
      <Settings2 size={19} strokeWidth={1.8} />
    </button>
  );
}
