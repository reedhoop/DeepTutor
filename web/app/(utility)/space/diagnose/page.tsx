"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import {
  BookOpenCheck,
  ChevronRight,
  ClipboardPaste,
  Gauge,
  ImageUp,
  Loader2,
  Route,
  Sparkles,
  XCircle,
} from "lucide-react";

import {
  diagnoseReview,
  fetchDiagnoses,
  reviewExercisePage,
  startKgraphPath,
  type DiagnoseResult,
  type DiagnosisRecord,
  type ReviewQuestion,
} from "@/lib/learning-api";

const DEFAULT_BOOK_ID = "exercise_review";

type Mode = "image" | "json";

export default function LevelDiagnosePage() {
  const router = useRouter();
  const { i18n } = useTranslation();
  const zh = i18n.language?.toLowerCase().startsWith("zh");
  const tr = useCallback((cn: string, en: string) => (zh ? cn : en), [zh]);
  const [mode, setMode] = useState<Mode>("image");
  const [bookId, setBookId] = useState(DEFAULT_BOOK_ID);
  const [imageBase64, setImageBase64] = useState("");
  const [imageName, setImageName] = useState("");
  const [jsonDraft, setJsonDraft] = useState("");
  const [result, setResult] = useState<{ questions: ReviewQuestion[] } | null>(null);
  const [wrong, setWrong] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState(false);
  const [diagnosing, setDiagnosing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [diagnose, setDiagnose] = useState<DiagnoseResult | null>(null);
  const [history, setHistory] = useState<DiagnosisRecord[]>([]);
  const [startingKp, setStartingKp] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);

  // Load recent diagnosis history on mount (archive/trend linkage).
  useEffect(() => {
    fetchDiagnoses(10)
      .then((d) => setHistory(d.diagnoses))
      .catch(() => undefined);
  }, []);

  const runReview = useCallback(
    async (payload: {
      image_base64?: string;
      auto_split?: boolean;
      questions?: Omit<ReviewQuestion, "variant" | "variant_note">[];
    }) => {
      setBusy(true);
      setError(null);
      setDiagnose(null);
      try {
        const res = await reviewExercisePage({
          book_id: bookId.trim() || DEFAULT_BOOK_ID,
          ...payload,
        });
        setResult(res);
        setWrong({});
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setBusy(false);
      }
    },
    [bookId],
  );

  const handleFile = useCallback(
    async (file: File | undefined) => {
      if (!file) return;
      setImageName(file.name);
      const reader = new FileReader();
      reader.onload = () => {
        const url = String(reader.result || "");
        setImageBase64(url);
        void runReview({
          image_base64: url.split(",").pop() || url,
          auto_split: true,
        });
      };
      reader.readAsDataURL(file);
    },
    [runReview],
  );

  const handlePasteJson = useCallback(() => {
    try {
      const parsed = JSON.parse(jsonDraft);
      if (!Array.isArray(parsed)) throw new Error("expected array");
      void runReview({
        questions: parsed as Omit<ReviewQuestion, "variant" | "variant_note">[],
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [jsonDraft, runReview]);

  const wrongCount = Object.values(wrong).filter(Boolean).length;

  const runDiagnose = useCallback(async () => {
    if (!result) return;
    const questions = result.questions.map((q) => ({
      id: q.id,
      kp_id: q.kp_id,
      error_type: q.error_type,
      is_correct: !wrong[q.id],
    }));
    setDiagnosing(true);
    setError(null);
    try {
      const res = await diagnoseReview({
        book_id: bookId.trim() || DEFAULT_BOOK_ID,
        questions,
      });
      setDiagnose(res);
      // Refresh history so the trend section reflects the new record.
      const h = await fetchDiagnoses(10).catch(() => null);
      if (h) setHistory(h.diagnoses);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setDiagnosing(false);
    }
  }, [bookId, result, wrong]);

  // Weak point → one-click mastery path (links to /space/learning).
  const startPath = useCallback(
    async (kpId: string) => {
      setStartingKp(kpId);
      setError(null);
      try {
        await startKgraphPath(kpId);
        router.push(
          `/space/learning?path=${encodeURIComponent(`kgraph_${kpId}`)}`,
        );
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
        setStartingKp(null);
      }
    },
    [router],
  );

  return (
    <div className="mx-auto w-full max-w-[880px] px-6 py-8">
      <div className="mb-6">
        <h1 className="flex items-center gap-2 text-[20px] font-semibold text-[var(--foreground)]">
          <Gauge size={20} strokeWidth={1.9} className="text-[var(--primary)]" />
          {tr("水平诊断", "Level Diagnosis")}
        </h1>
        <p className="mt-1 text-[13px] leading-relaxed text-[var(--muted-foreground)]">
          {tr(
            "上传一份做过的试卷（或粘贴题目），逐题标记对错后一键评估学习水平：得出正确率、错因分布与薄弱知识点，每个薄弱点都可一键生成专攻学习路径。",
            "Upload a completed exercise page (or paste questions), mark right/wrong per question, and get a level assessment: accuracy, error causes and weak knowledge points — each weak point can start a dedicated mastery path.",
          )}
        </p>
      </div>

      {/* Input card */}
      <div className="rounded-2xl border border-[var(--border)]/60 bg-[var(--card)] p-4 shadow-sm">
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-0.5 rounded-lg bg-[var(--muted)]/40 p-0.5">
            {(
              [
                ["image", tr("上传试卷", "Upload paper"), ImageUp],
                ["json", tr("粘贴题目", "Paste JSON"), ClipboardPaste],
              ] as const
            ).map(([m, label, Icon]) => (
              <button
                key={m}
                type="button"
                onClick={() => setMode(m)}
                className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[12.5px] transition-colors ${
                  mode === m
                    ? "bg-[var(--card)] text-[var(--foreground)] shadow-sm"
                    : "text-[var(--muted-foreground)]"
                }`}
              >
                <Icon size={13} strokeWidth={1.9} />
                {label}
              </button>
            ))}
          </div>
          <label className="ml-2 text-[12px] text-[var(--muted-foreground)]">
            {tr("错题本", "Book")}
            <input
              value={bookId}
              onChange={(e) => setBookId(e.target.value)}
              className="ml-1.5 w-32 rounded-md border border-[var(--border)] bg-[var(--background)] px-2 py-1 text-[12px] text-[var(--foreground)]"
            />
          </label>
        </div>

        {mode === "image" ? (
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            disabled={busy}
            className="mt-3 flex w-full flex-col items-center gap-1.5 rounded-xl border border-dashed border-[var(--border)]/70 bg-[var(--muted)]/15 px-4 py-8 text-center transition-colors hover:border-[var(--primary)]/50 disabled:opacity-40"
          >
            <ImageUp size={22} strokeWidth={1.6} className="text-[var(--muted-foreground)]" />
            <span className="text-[13px] text-[var(--foreground)]">
              {imageName || tr("上传整页试卷照片（印刷体）", "Upload a printed exercise page")}
            </span>
            <span className="text-[11.5px] text-[var(--muted-foreground)]">
              {tr("支持自动切分（OCR）为逐题列表", "auto-split into per-question list (OCR)")}
            </span>
            <input
              ref={fileRef}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={(e) => void handleFile(e.target.files?.[0])}
            />
          </button>
        ) : (
          <div className="mt-3">
            <textarea
              value={jsonDraft}
              onChange={(e) => setJsonDraft(e.target.value)}
              placeholder={tr(
                '[{"stem": "题目题干", "options": ["A","B","C","D"], "answer": "A", "kp_id": "可选", "error_type": "可选"}]',
                '[{"stem": "stem", "options": ["A","B","C","D"], "answer": "A", "kp_id": "optional"}]',
              )}
              rows={5}
              className="w-full resize-y rounded-xl border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[12.5px] leading-relaxed text-[var(--foreground)] outline-none focus:border-[var(--primary)]/50"
            />
            <button
              type="button"
              onClick={handlePasteJson}
              disabled={busy || !jsonDraft.trim()}
              className="mt-2 inline-flex h-8 items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3.5 text-[12.5px] font-medium text-[var(--primary-foreground)] transition-colors hover:bg-[var(--primary)]/90 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {busy ? <Loader2 size={14} className="animate-spin" /> : <ClipboardPaste size={14} />}
              {tr("解析题目", "Parse questions")}
            </button>
          </div>
        )}

        {error && (
          <div className="mt-3 flex items-start gap-2 rounded-xl border border-red-500/25 bg-red-500/[0.06] px-3 py-2.5 text-[12.5px] leading-relaxed text-red-600 dark:text-red-400">
            <XCircle size={15} strokeWidth={1.9} className="mt-0.5 shrink-0" />
            <span>{error}</span>
          </div>
        )}
      </div>

      {/* Question list with right/wrong marking */}
      {result && result.questions.length > 0 && (
        <div className="mt-5 rounded-2xl border border-[var(--border)]/60 bg-[var(--card)] p-4 shadow-sm">
          <div className="flex items-center justify-between">
            <h2 className="text-[14px] font-semibold text-[var(--foreground)]">
              {tr("逐题标记", "Mark per question")}
              <span className="ml-2 text-[12px] font-normal text-[var(--muted-foreground)]">
                {result.questions.length} {tr("题", "questions")} · {wrongCount} {tr("做错", "wrong")}
              </span>
            </h2>
            <button
              type="button"
              onClick={runDiagnose}
              disabled={busy || diagnosing}
              className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3.5 text-[12.5px] font-medium text-[var(--primary-foreground)] transition-colors hover:bg-[var(--primary)]/90 active:scale-95 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {diagnosing ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <Gauge size={14} strokeWidth={2} />
              )}
              {tr("生成水平诊断", "Generate diagnosis")}
            </button>
          </div>
          <div className="mt-3 space-y-1.5">
            {result.questions.map((q, i) => {
              const isWrong = Boolean(wrong[q.id]);
              return (
                <div
                  key={q.id || i}
                  className={`flex items-center gap-3 rounded-xl border px-3.5 py-2.5 transition-colors ${
                    isWrong ? "border-red-500/35 bg-red-500/[0.04]" : "border-[var(--border)]/50"
                  }`}
                >
                  <span
                    className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[12px] font-semibold ${
                      isWrong ? "bg-red-500/15 text-red-500" : "bg-[var(--primary)]/[0.1] text-[var(--primary)]"
                    }`}
                  >
                    {i + 1}
                  </span>
                  <p className="min-w-0 flex-1 truncate text-[13px] text-[var(--foreground)]">
                    {q.stem || tr("（无题干）", "(no stem)")}
                  </p>
                  <button
                    type="button"
                    role="switch"
                    aria-checked={isWrong}
                    onClick={() => setWrong((prev) => ({ ...prev, [q.id]: !prev[q.id] }))}
                    title={tr("标记为做错 / 答对", "Mark wrong / correct")}
                    className={`relative h-5 w-9 shrink-0 rounded-full transition-colors ${
                      isWrong ? "bg-red-500" : "bg-[var(--muted)]"
                    }`}
                  >
                    <span
                      className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-[left] ${
                        isWrong ? "left-[18px]" : "left-0.5"
                      }`}
                    />
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Diagnosis report */}
      {diagnose && (
        <div className="mt-5 rounded-2xl border border-[var(--border)]/60 bg-[var(--card)] p-5 shadow-sm">
          <h2 className="flex items-center gap-2 text-[15px] font-semibold text-[var(--foreground)]">
            <Gauge size={17} strokeWidth={1.9} className="text-[var(--primary)]" />
            {tr("水平诊断报告", "Level Diagnosis Report")}
            <span className="ml-auto text-[12px] font-normal text-[var(--muted-foreground)]">
              {diagnose.total} {tr("题", "questions")} · {tr("对", "right")} {diagnose.correct} ·{" "}
              {tr("错", "wrong")} {diagnose.wrong}
            </span>
          </h2>

          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            <div className="rounded-xl border border-[var(--border)]/50 bg-[var(--muted)]/25 p-3.5">
              <div className="text-[11px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
                {tr("正确率", "Accuracy")}
              </div>
              <div className="mt-1 text-[26px] font-bold leading-none text-[var(--foreground)]">
                {Math.round(diagnose.accuracy * 100)}%
              </div>
              <div className="mt-1 text-[11.5px] text-[var(--muted-foreground)]">
                {diagnose.correct} / {diagnose.total}
              </div>
            </div>
            <div className="rounded-xl border border-[var(--border)]/50 bg-[var(--muted)]/25 p-3.5 sm:col-span-2">
              <div className="text-[11px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
                {tr("错因分布", "Error causes")}
              </div>
              {diagnose.error_types.length === 0 ? (
                <p className="mt-2 text-[12.5px] text-[var(--muted-foreground)]">
                  {tr("本次没有标记错因的错题。", "No wrong answers with a cause this time.")}
                </p>
              ) : (
                <div className="mt-2 space-y-1.5">
                  {diagnose.error_types.map((et) => (
                    <div key={et.type} className="flex items-center gap-2">
                      <span className="w-20 shrink-0 text-[12px] text-[var(--foreground)]">{et.name}</span>
                      <div className="h-2 flex-1 overflow-hidden rounded-full bg-[var(--muted)]/50">
                        <div
                          className="h-full rounded-full bg-[var(--primary)]/70"
                          style={{ width: `${(et.count / Math.max(diagnose.wrong, 1)) * 100}%` }}
                        />
                      </div>
                      <span className="w-5 shrink-0 text-right text-[12px] text-[var(--muted-foreground)]">
                        {et.count}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {diagnose.weak_kps.length > 0 && (
            <div className="mt-4">
              <div className="text-[12px] font-semibold text-[var(--foreground)]">
                {tr("薄弱知识点（可一键生成专攻路径）", "Weak knowledge points — start a mastery path")}
              </div>
              <div className="mt-2 space-y-2">
                {diagnose.weak_kps.map((wk) => (
                  <div
                    key={wk.kp_id}
                    className="rounded-xl border border-red-500/20 bg-red-500/[0.04] px-3.5 py-2.5"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-[13px] font-medium text-[var(--foreground)]">{wk.name}</span>
                      <span className="rounded-full bg-red-500/10 px-2 py-0.5 text-[11px] font-medium text-red-600 dark:text-red-400">
                        {tr("错", "wrong")} {wk.wrong_count}
                      </span>
                      <span className="text-[11.5px] text-[var(--muted-foreground)]">
                        {tr("掌握度", "mastery")} {Math.round(wk.mastery * 100)}%
                      </span>
                      <button
                        type="button"
                        onClick={() => void startPath(wk.kp_id)}
                        disabled={startingKp === wk.kp_id}
                        className="ml-auto inline-flex h-7 items-center gap-1 rounded-lg bg-[var(--primary)] px-2.5 text-[12px] font-medium text-[var(--primary-foreground)] transition-colors hover:bg-[var(--primary)]/90 active:scale-95 disabled:opacity-50"
                      >
                        {startingKp === wk.kp_id ? (
                          <Loader2 size={12} className="animate-spin" />
                        ) : (
                          <Route size={12} strokeWidth={2} />
                        )}
                        {tr("生成专攻路径", "Start path")}
                      </button>
                    </div>
                    <p className="mt-1 text-[12px] leading-relaxed text-[var(--muted-foreground)]">
                      {wk.suggestion}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {diagnose.suggestions.length > 0 && (
            <div className="mt-4 rounded-xl border border-[var(--border)]/50 bg-[var(--muted)]/20 p-3.5">
              <div className="flex items-center gap-1.5 text-[12px] font-semibold text-[var(--foreground)]">
                <Sparkles size={13} strokeWidth={1.9} className="text-[var(--primary)]" />
                {tr("专项提升建议", "Suggestions")}
              </div>
              <ul className="mt-1.5 space-y-1">
                {diagnose.suggestions.map((s, i) => (
                  <li key={i} className="text-[12.5px] leading-relaxed text-[var(--muted-foreground)]">
                    · {s}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* Diagnosis history (archive linkage) */}
      {history.length > 0 && (
        <div className="mt-6 rounded-2xl border border-[var(--border)]/60 bg-[var(--card)] p-4 shadow-sm">
          <div className="flex items-center gap-1.5 text-[13px] font-semibold text-[var(--foreground)]">
            <BookOpenCheck size={14} strokeWidth={1.9} className="text-[var(--primary)]" />
            {tr("诊断历史", "Diagnosis history")}
          </div>
          <div className="mt-2 space-y-1.5">
            {history.slice(0, 6).map((h) => (
              <div
                key={h.id}
                className="flex items-center gap-3 rounded-lg px-2.5 py-1.5 text-[12px] text-[var(--muted-foreground)] hover:bg-[var(--muted)]/30"
              >
                <span className="font-medium text-[var(--foreground)]">
                  {Math.round(h.accuracy * 100)}%
                </span>
                <div className="h-1.5 w-24 overflow-hidden rounded-full bg-[var(--muted)]/50">
                  <div
                    className="h-full rounded-full bg-[var(--primary)]/70"
                    style={{ width: `${Math.round(h.accuracy * 100)}%` }}
                  />
                </div>
                <span>
                  {h.total} {tr("题", "questions")} · {h.wrong} {tr("错", "wrong")}
                </span>
                <span className="ml-auto">
                  {new Date(h.created_at * 1000).toLocaleString()}
                </span>
                {h.weak_kps.length > 0 && (
                  <ChevronRight size={12} className="opacity-40" />
                )}
              </div>
            ))}
          </div>
          <p className="mt-2 text-[11.5px] text-[var(--muted-foreground)]">
            {tr(
              "每次诊断都会记录，学习空间 → 成长档案可查看掌握度演进与薄弱点汇总。",
              "Every diagnosis is recorded; the growth archive shows mastery evolution and weak-point summaries.",
            )}
          </p>
        </div>
      )}
    </div>
  );
}
