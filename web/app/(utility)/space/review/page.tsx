"use client";

import { useCallback, useRef, useState } from "react";
import {
  BookOpenCheck,
  ChevronDown,
  ClipboardPaste,
  FileText,
  Gauge,
  ImageUp,
  Loader2,
  Send,
  ShieldCheck,
  Sparkles,
  XCircle,
} from "lucide-react";

import {
  diagnoseReview,
  reviewExercisePage,
  submitReviewErrors,
  type DiagnoseResult,
  type ExerciseReviewResult,
  type ReviewQuestion,
} from "@/lib/learning-api";

/** Chinese-first inline translation helper (mirrors the other ER surfaces). */
const tr = (zh: string, _en: string) => zh;

const DEFAULT_BOOK_ID = "exercise_review";

type Mode = "image" | "json";

export default function ExerciseReviewPage() {
  const [mode, setMode] = useState<Mode>("image");
  const [bookId, setBookId] = useState(DEFAULT_BOOK_ID);
  const [imageBase64, setImageBase64] = useState("");
  const [imageName, setImageName] = useState("");
  const [jsonDraft, setJsonDraft] = useState("");
  const [result, setResult] = useState<ExerciseReviewResult | null>(null);
  const [wrong, setWrong] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [diagnose, setDiagnose] = useState<DiagnoseResult | null>(null);
  const [diagnosing, setDiagnosing] = useState(false);
  const fileRef = useRef<HTMLInputElement | null>(null);

  const runReview = useCallback(
    async (payload: {
      image_base64?: string;
      auto_split?: boolean;
      questions?: Omit<ReviewQuestion, "variant" | "variant_note">[];
    }) => {
      setBusy(true);
      setError(null);
      setNotice(null);
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
        void runReview({ image_base64: url, auto_split: true });
      };
      reader.onerror = () => setError(tr("读取图片失败", "Failed to read image"));
      reader.readAsDataURL(file);
    },
    [runReview],
  );

  const runJsonReview = useCallback(() => {
    let parsed: unknown;
    try {
      parsed = JSON.parse(jsonDraft);
    } catch {
      setError(tr("JSON 解析失败，请检查格式", "Invalid JSON — please check the format"));
      return;
    }
    if (!Array.isArray(parsed) || parsed.length === 0) {
      setError(tr("JSON 应为题目数组，如 [{\"stem\": \"...\"}]", "JSON must be an array of questions"));
      return;
    }
    void runReview({ questions: parsed as Omit<ReviewQuestion, "variant" | "variant_note">[] });
  }, [jsonDraft, runReview]);

  const toggleExpanded = useCallback((id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const wrongCount = Object.values(wrong).filter(Boolean).length;

  const sendToErrorBook = useCallback(async () => {
    if (!result) return;
    const errors = result.questions
      .filter((q) => wrong[q.id])
      .map((q) => ({
        question_id: q.id,
        stem: q.stem,
        kp_id: q.kp_id,
        error_type: q.error_type || undefined,
        module_id: q.module_id || undefined,
      }));
    if (!errors.length) {
      setNotice(tr("尚未标记任何错题", "No questions marked as wrong yet"));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await submitReviewErrors({
        book_id: bookId.trim() || DEFAULT_BOOK_ID,
        errors,
      });
      setNotice(
        tr(
          `已将 ${res.added} 道错题记入错题本（${res.book_id}），可在"学习空间 → 错题本"中查看。`,
          `${res.added} wrong answers recorded to the error book (${res.book_id}).`,
        ),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [bookId, result, wrong]);

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
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setDiagnosing(false);
    }
  }, [bookId, result, wrong]);

  return (
    <div className="mx-auto w-full max-w-[880px] px-6 py-8">
      <div className="mb-6">
        <h1 className="flex items-center gap-2 text-[20px] font-semibold text-[var(--foreground)]">
          <BookOpenCheck size={20} strokeWidth={1.9} className="text-[var(--primary)]" />
          {tr("AI 习题讲评", "AI Exercise Review")}
        </h1>
        <p className="mt-1 text-[13px] leading-relaxed text-[var(--muted-foreground)]">
          {tr(
            "上传整页练习照片或粘贴抽好的题目 JSON，生成逐题讲评视图；做错标记的题目一键进入错题本。",
            "Upload a whole exercise page or paste question JSON, get a per-question review view; mark wrong answers and send them to the error book.",
          )}
        </p>
      </div>

      {/* Input card */}
      <div className="rounded-2xl border border-[var(--border)]/60 bg-[var(--card)] p-4 shadow-sm">
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-0.5 rounded-lg bg-[var(--muted)]/40 p-0.5">
            <button
              type="button"
              onClick={() => setMode("image")}
              className={`flex h-7 items-center gap-1.5 rounded-md px-2.5 text-[12px] transition-colors ${
                mode === "image"
                  ? "bg-[var(--card)] font-medium text-[var(--foreground)] shadow-sm"
                  : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
              }`}
            >
              <ImageUp size={14} strokeWidth={1.8} />
              {tr("上传整页图片", "Upload page image")}
            </button>
            <button
              type="button"
              onClick={() => setMode("json")}
              className={`flex h-7 items-center gap-1.5 rounded-md px-2.5 text-[12px] transition-colors ${
                mode === "json"
                  ? "bg-[var(--card)] font-medium text-[var(--foreground)] shadow-sm"
                  : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
              }`}
            >
              <ClipboardPaste size={14} strokeWidth={1.8} />
              {tr("粘贴题目 JSON", "Paste question JSON")}
            </button>
          </div>
          <label className="ml-auto flex items-center gap-1.5 text-[12px] text-[var(--muted-foreground)]">
            {tr("错题本路径", "Book")}
            <input
              value={bookId}
              onChange={(e) => setBookId(e.target.value)}
              className="h-7 w-[160px] rounded-lg border border-[var(--border)]/60 bg-[var(--card)] px-2 text-[12px] text-[var(--foreground)] outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)]/40"
            />
          </label>
        </div>

        {mode === "image" ? (
          <div className="mt-3">
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              disabled={busy}
              className="flex h-24 w-full flex-col items-center justify-center gap-1.5 rounded-xl border-2 border-dashed border-[var(--border)]/70 text-[var(--muted-foreground)] transition-colors hover:border-[var(--primary)]/50 hover:text-[var(--foreground)] disabled:opacity-50"
            >
              <ImageUp size={22} strokeWidth={1.7} />
              <span className="text-[12.5px]">
                {imageName || tr("点击选择整页练习照片（印刷体）", "Click to pick a printed exercise page")}
              </span>
              <span className="text-[11px] opacity-80">
                {tr("选中后自动尝试切分并生成讲评", "Auto-splits and reviews once selected")}
              </span>
            </button>
            <input
              ref={fileRef}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={(e) => void handleFile(e.target.files?.[0])}
            />
            <p className="mt-2 text-[11px] leading-snug text-[var(--muted-foreground)]">
              {tr(
                "自动切分需要视觉模型/VLM 引擎支持；若提示不可用，请切换到「粘贴题目 JSON」模式，先用任意视觉 LLM 抽取题目后粘贴。",
                "Auto-splitting needs a vision model / VLM engine; if unavailable, switch to JSON mode and paste questions extracted by any vision LLM.",
              )}
            </p>
          </div>
        ) : (
          <div className="mt-3">
            <textarea
              value={jsonDraft}
              onChange={(e) => setJsonDraft(e.target.value)}
              rows={6}
              placeholder={tr(
                '[{"stem": "题目题干", "options": ["A", "B", "C", "D"], "answer": "A", "kp_id": "可选知识点", "error_type": "可选"}]',
                '[{"stem": "question stem", "options": ["A","B","C","D"], "answer": "A", "kp_id": "optional"}]',
              )}
              className="w-full resize-y rounded-xl border border-[var(--border)]/60 bg-[var(--card)] px-3 py-2.5 font-mono text-[12.5px] leading-relaxed text-[var(--foreground)] outline-none placeholder:text-[var(--muted-foreground)] focus-visible:ring-2 focus-visible:ring-[var(--primary)]/40"
            />
            <button
              type="button"
              onClick={runJsonReview}
              disabled={busy || !jsonDraft.trim()}
              className="mt-2 inline-flex h-8 items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3.5 text-[12.5px] font-medium text-[var(--primary-foreground)] transition-colors hover:bg-[var(--primary)]/90 disabled:opacity-40"
            >
              {busy ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <Send size={14} strokeWidth={2} />
              )}
              {tr("生成讲评", "Generate review")}
            </button>
          </div>
        )}

        {error && (
          <div className="mt-3 flex items-start gap-2 rounded-xl border border-red-500/25 bg-red-500/[0.06] px-3 py-2.5 text-[12.5px] leading-relaxed text-red-600 dark:text-red-400">
            <XCircle size={15} strokeWidth={1.9} className="mt-0.5 shrink-0" />
            <span>{error}</span>
          </div>
        )}
        {notice && (
          <div className="mt-3 flex items-start gap-2 rounded-xl border border-emerald-500/25 bg-emerald-500/[0.06] px-3 py-2.5 text-[12.5px] leading-relaxed text-emerald-600 dark:text-emerald-400">
            <ShieldCheck size={15} strokeWidth={1.9} className="mt-0.5 shrink-0" />
            <span>{notice}</span>
          </div>
        )}
      </div>

      {/* Review view */}
      {result && result.questions.length > 0 && (
        <div className="mt-5 space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-[15px] font-semibold text-[var(--foreground)]">
              {tr("逐题讲评", "Per-question review")}
              <span className="ml-2 text-[12px] font-normal text-[var(--muted-foreground)]">
                {result.questions.length} {tr("题", "questions")} · {wrongCount} {tr("题标记做错", "marked wrong")}
              </span>
            </h2>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={runDiagnose}
                disabled={busy || diagnosing}
                className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-[var(--border)] bg-[var(--card)] px-3.5 text-[12.5px] font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--muted)]/40 active:scale-95 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {diagnosing ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <Gauge size={14} strokeWidth={2} className="text-[var(--primary)]" />
                )}
                {tr("生成水平诊断", "Level diagnosis")}
              </button>
              <button
                type="button"
                onClick={sendToErrorBook}
                disabled={busy || wrongCount === 0}
                className={`inline-flex h-8 items-center gap-1.5 rounded-lg px-3.5 text-[12.5px] font-medium transition-colors active:scale-95 disabled:cursor-not-allowed disabled:opacity-40 ${
                  wrongCount > 0
                    ? "bg-[var(--primary)] text-[var(--primary-foreground)] hover:bg-[var(--primary)]/90"
                    : "bg-[var(--muted)] text-[var(--muted-foreground)]"
                }`}
              >
                {busy ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <BookOpenCheck size={14} strokeWidth={2} />
                )}
                {tr(`错题入错题本（${wrongCount}）`, `Send ${wrongCount} to error book`)}
              </button>
            </div>
          </div>

          {result.questions.map((q, i) => {
            const isWrong = Boolean(wrong[q.id]);
            const isOpen = expanded.has(q.id);
            return (
              <div
                key={q.id || i}
                className={`rounded-2xl border bg-[var(--card)] shadow-sm transition-colors ${
                  isWrong ? "border-red-500/40" : "border-[var(--border)]/60"
                }`}
              >
                <div className="flex items-start gap-3 px-4 py-3">
                  <span
                    className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[12px] font-semibold ${
                      isWrong
                        ? "bg-red-500/15 text-red-500"
                        : "bg-[var(--primary)]/[0.1] text-[var(--primary)]"
                    }`}
                  >
                    {i + 1}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-[13.5px] leading-relaxed text-[var(--foreground)]">
                      {q.stem || tr("（无题干）", "(no stem)")}
                    </p>
                    {q.options.length > 0 && (
                      <ul className="mt-1.5 grid gap-1 sm:grid-cols-2">
                        {q.options.map((opt, oi) => (
                          <li key={oi} className="text-[12.5px] text-[var(--muted-foreground)]">
                            {String.fromCharCode(65 + oi)}. {opt}
                          </li>
                        ))}
                      </ul>
                    )}
                    {q.analysis && (
                      <p className="mt-1.5 text-[12.5px] leading-relaxed text-[var(--muted-foreground)]">
                        {tr("解析", "Analysis")}：{q.analysis}
                      </p>
                    )}
                    {q.variant.length > 0 && (
                      <button
                        type="button"
                        onClick={() => toggleExpanded(q.id)}
                        className="mt-2 inline-flex items-center gap-1 text-[12px] font-medium text-[var(--primary)]"
                      >
                        <ChevronDown
                          size={13}
                          strokeWidth={2}
                          className={`transition-transform ${isOpen ? "rotate-180" : ""}`}
                        />
                        {tr("变式练习", "Variant practice")}
                        <span className="font-normal text-[var(--muted-foreground)]">
                          ({q.variant.length})
                        </span>
                      </button>
                    )}
                    {q.variant_note && (
                      <p className="mt-1.5 text-[11.5px] text-[var(--muted-foreground)]">
                        {q.variant_note}
                      </p>
                    )}
                    {isOpen && q.variant.length > 0 && (
                      <div className="mt-2 space-y-2 rounded-xl border border-[var(--border)]/50 bg-[var(--muted)]/25 p-3">
                        {q.variant.map((v, vi) => (
                          <div key={vi}>
                            <div className="flex items-center gap-1.5">
                              <FileText size={13} strokeWidth={1.8} className="shrink-0 text-[var(--primary)]" />
                              <span className="text-[12px] font-medium text-[var(--foreground)]">
                                {tr("变式", "Variant")} {vi + 1}
                                {v.source && (
                                  <span className="ml-1 font-normal text-[var(--muted-foreground)]">
                                    · {v.source}
                                  </span>
                                )}
                              </span>
                            </div>
                            <p className="mt-1 text-[12.5px] leading-relaxed text-[var(--foreground)]">
                              {v.question}
                            </p>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                  <button
                    type="button"
                    role="switch"
                    aria-checked={isWrong}
                    onClick={() =>
                      setWrong((prev) => ({ ...prev, [q.id]: !prev[q.id] }))
                    }
                    title={isWrong ? tr("标记为做错", "Marked wrong") : tr("标记为做错", "Mark wrong")}
                    className={`relative mt-1 h-5 w-9 shrink-0 rounded-full transition-colors ${
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
              </div>
            );
          })}
        </div>
      )}

      {/* Level diagnosis report */}
      {diagnose && (
        <div className="mt-6 rounded-2xl border border-[var(--border)]/60 bg-[var(--card)] p-5 shadow-sm">
          <h2 className="flex items-center gap-2 text-[15px] font-semibold text-[var(--foreground)]">
            <Gauge size={17} strokeWidth={1.9} className="text-[var(--primary)]" />
            {tr("水平诊断报告", "Level Diagnosis")}
            <span className="ml-auto text-[12px] font-normal text-[var(--muted-foreground)]">
              {diagnose.total} {tr("题", "questions")} · {tr("正确", "correct")}{" "}
              {diagnose.correct} · {tr("做错", "wrong")} {diagnose.wrong}
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
                      <span className="w-20 shrink-0 text-[12px] text-[var(--foreground)]">
                        {et.name}
                      </span>
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
                {tr("薄弱知识点", "Weak knowledge points")}
              </div>
              <div className="mt-2 space-y-2">
                {diagnose.weak_kps.map((wk) => (
                  <div
                    key={wk.kp_id}
                    className="rounded-xl border border-red-500/20 bg-red-500/[0.04] px-3.5 py-2.5"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-[13px] font-medium text-[var(--foreground)]">
                        {wk.name}
                      </span>
                      <span className="rounded-full bg-red-500/10 px-2 py-0.5 text-[11px] font-medium text-red-600 dark:text-red-400">
                        {tr("错", "wrong")} {wk.wrong_count}
                      </span>
                      <span className="text-[11.5px] text-[var(--muted-foreground)]">
                        {tr("掌握度", "mastery")} {Math.round(wk.mastery * 100)}%
                      </span>
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

      {!result && (
        <div className="mt-8 rounded-2xl border border-dashed border-[var(--border)]/60 px-6 py-10 text-center text-[13px] text-[var(--muted-foreground)]">
          <BookOpenCheck size={26} strokeWidth={1.6} className="mx-auto mb-3 opacity-50" />
          {tr(
            "上传一页印刷体练习照片（含 5+ 题），或粘贴题目 JSON，即可生成逐题讲评视图。",
            "Upload a printed exercise page (5+ questions) or paste question JSON to generate the review view.",
          )}
        </div>
      )}
    </div>
  );
}
