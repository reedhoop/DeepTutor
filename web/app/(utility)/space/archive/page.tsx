"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import {
  LineChart,
  TrendingUp,
  BookOpen,
  AlertTriangle,
  Target,
  CheckCircle2,
  ListChecks,
  History,
  Network,
  Loader2,
  ChevronDown,
} from "lucide-react";

import {
  fetchDiagnoses,
  fetchStudyArchive,
  type DiagnosisRecord,
  type StudyArchive,
} from "@/lib/learning-api";
import KGraphMermaid from "@/components/kgraph/KGraphMermaid";

function fmtDate(ts: number): string {
  const d = new Date(ts * 1000);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate(),
  ).padStart(2, "0")}`;
}

/**
 * ER-13 growth archive — a read-only rollup across every mastery path.
 * Renders the overall rollup, a time-ordered mastery-evolution timeline, a
 * weak-point digest (with error counts), and a per-path knowledge map that
 * reuses the ER-1 KGraphMermaid component (coloured by mastery).
 */
export default function StudyArchivePage() {
  const { i18n } = useTranslation();
  const zh = i18n.language?.toLowerCase().startsWith("zh");
  const tr = useCallback((cn: string, en: string) => (zh ? cn : en), [zh]);
  const router = useRouter();

  const [data, setData] = useState<StudyArchive | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [diagnoses, setDiagnoses] = useState<DiagnosisRecord[]>([]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchStudyArchive()
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    fetchDiagnoses(20)
      .then((r) => {
        if (!cancelled) setDiagnoses(r.diagnoses);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return (
      <div className="flex items-center gap-2 px-1 py-10 text-sm text-[var(--muted-foreground)]">
        <Loader2 className="h-4 w-4 animate-spin" />
        {tr("加载成长档案…", "Loading study archive…")}
      </div>
    );
  }
  if (error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-600">
        {tr("成长档案加载失败：", "Failed to load study archive: ")}
        {error}
      </div>
    );
  }

  const overall = data?.overall;
  if (!data || !overall || overall.path_count === 0) {
    return (
      <div className="rounded-lg border border-dashed border-[var(--border)] bg-[var(--muted)]/30 px-4 py-10 text-center text-sm text-[var(--muted-foreground)]">
        {tr(
          "还没有学习路径记录。前往「精通之路」开始一次掌握式学习，这里会累积你的成长档案。",
          "No learning paths yet. Start a mastery path from “Mastery Path” and your growth archive will accumulate here.",
        )}
      </div>
    );
  }

  return (
    <div className="space-y-10">
      <header>
        <h1 className="flex items-center gap-2 font-serif text-[24px] font-semibold tracking-tight text-[var(--foreground)]">
          <LineChart className="h-6 w-6 text-[var(--primary)]" />
          {tr("成长档案", "Growth Archive")}
        </h1>
        <p className="mt-1.5 max-w-2xl text-[13px] leading-relaxed text-[var(--muted-foreground)]">
          {tr(
            "聚合你的全部学习路径：掌握度演进、薄弱点与知识脉络。数据只读派生自你的练习与掌握度记录。",
            "An aggregated view of every learning path — mastery evolution, weak points, and knowledge maps. Derived read-only from your practice and mastery records.",
          )}
        </p>
      </header>

      {/* Overall rollup */}
      <section className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <StatCard icon={BookOpen} label={tr("学习路径", "Paths")} value={overall.path_count} />
        <StatCard icon={Target} label={tr("知识点", "Knowledge pts")} value={overall.kp_count} />
        <StatCard
          icon={CheckCircle2}
          label={tr("已掌握", "Mastered")}
          value={overall.mastered_count}
        />
        <StatCard
          icon={TrendingUp}
          label={tr("平均掌握度", "Avg mastery")}
          value={`${overall.avg_mastery_pct}%`}
        />
        <StatCard icon={ListChecks} label={tr("练习", "Quizzes")} value={overall.quiz_count} />
        <StatCard
          icon={AlertTriangle}
          label={tr("错题", "Errors")}
          value={overall.error_count}
        />
      </section>

      {/* Mastery evolution timeline */}
      <section>
        <h2 className="mb-3 flex items-center gap-2 font-serif text-[16px] font-semibold tracking-tight text-[var(--foreground)]">
          <History className="h-4 w-4 opacity-70" />
          {tr("掌握度演进时间线", "Mastery Evolution Timeline")}
        </h2>
        <ol className="relative ml-2 border-l border-[var(--border)] pl-5">
          {data.timeline.map((b) => (
            <li key={b.book_id} className="relative pb-5 last:pb-0">
              <span className="absolute -left-[1.42rem] top-1 h-3 w-3 rounded-full border-2 border-[var(--background)] bg-[var(--primary)]" />
              <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                <span className="text-[13px] tabular-nums text-[var(--muted-foreground)]">
                  {fmtDate(b.updated_at)}
                </span>
                <button
                  onClick={() => router.push(`/space/learning?path=${encodeURIComponent(b.book_id)}`)}
                  className="text-[14px] font-medium text-[var(--foreground)] hover:text-[var(--primary)] hover:underline"
                >
                  {b.name}
                </button>
                <span className="text-[12px] text-[var(--muted-foreground)]">
                  · {b.avg_mastery_pct}% · {b.mastered_count}/{b.kp_count}
                </span>
              </div>
            </li>
          ))}
        </ol>
      </section>

      {/* Diagnosis trend (ER-12.2 linkage): accuracy across paper diagnoses */}
      {diagnoses.length > 0 && (
        <section>
          <h2 className="mb-3 flex items-center gap-2 font-serif text-[16px] font-semibold tracking-tight text-[var(--foreground)]">
            <LineChart className="h-4 w-4 opacity-70" />
            {tr("试卷诊断趋势", "Paper Diagnosis Trend")}
          </h2>
          <div className="rounded-lg border border-[var(--border)] p-4">
            <div className="flex items-end gap-1.5">
              {[...diagnoses].reverse().slice(-10).map((d) => (
                <div
                  key={d.id}
                  title={`${fmtDate(d.created_at)} · ${Math.round(d.accuracy * 100)}% · ${d.total} 题`}
                  className="flex-1"
                >
                  <div
                    className="w-full rounded-t bg-[var(--primary)]/70"
                    style={{ height: `${Math.max(4, Math.round(d.accuracy * 100))}px` }}
                  />
                </div>
              ))}
            </div>
            <div className="mt-2 space-y-1">
              {diagnoses.slice(0, 5).map((d) => (
                <div
                  key={d.id}
                  className="flex flex-wrap items-center gap-2 text-[12px] text-[var(--muted-foreground)]"
                >
                  <span className="text-[12px] tabular-nums">{fmtDate(d.created_at)}</span>
                  <span className="font-medium text-[var(--foreground)]">
                    {Math.round(d.accuracy * 100)}%
                  </span>
                  <span>
                    {d.total} {tr("题", "questions")} · {d.wrong} {tr("错", "wrong")}
                  </span>
                  {d.weak_kps.length > 0 && (
                    <span className="truncate text-[11.5px]">
                      {tr("薄弱", "weak")}: {d.weak_kps.map((w) => w.name).join("、")}
                    </span>
                  )}
                </div>
              ))}
            </div>
            <p className="mt-2 text-[11.5px] text-[var(--muted-foreground)]">
              {tr(
                "正确率来自学习空间 → 水平诊断的记录；多次诊断可看出水平变化。",
                "Accuracy comes from Level Diagnosis records; repeated diagnoses show progress over time.",
              )}
            </p>
          </div>
        </section>
      )}

      {/* Weak-point digest */}
      {data.weak_points.length > 0 && (
        <section>
          <h2 className="mb-3 flex items-center gap-2 font-serif text-[16px] font-semibold tracking-tight text-[var(--foreground)]">
            <AlertTriangle className="h-4 w-4 opacity-70" />
            {tr("薄弱点回顾", "Weak Points Digest")}
          </h2>
          <div className="divide-y divide-[var(--border)] overflow-hidden rounded-lg border border-[var(--border)]">
            {data.weak_points.map((w) => (
              <button
                key={w.knowledge_point_id}
                onClick={() => router.push(`/space/learning?path=${encodeURIComponent(w.module_id)}`)}
                className="flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-[var(--muted)]/40"
              >
                <span className="mt-0.5 shrink-0 rounded-md bg-rose-500/10 px-2 py-0.5 text-[11px] font-medium text-rose-600 dark:text-rose-400">
                  {Math.round(w.mastery * 100)}%
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[14px] font-medium text-[var(--foreground)]">
                    {w.name}
                  </p>
                  <p className="mt-0.5 text-[12px] text-[var(--muted-foreground)]">
                    {w.reason}
                  </p>
                </div>
                {w.error_count > 0 && (
                  <span className="shrink-0 text-[12px] text-[var(--muted-foreground)]">
                    {tr(`${w.error_count} 道错题`, `${w.error_count} errors`)}
                  </span>
                )}
              </button>
            ))}
          </div>
        </section>
      )}

      {/* Per-path knowledge maps (ER-1 reuse) */}
      <section>
        <h2 className="mb-3 flex items-center gap-2 font-serif text-[16px] font-semibold tracking-tight text-[var(--foreground)]">
          <Network className="h-4 w-4 opacity-70" />
          {tr("各路径知识脉络", "Knowledge Maps per Path")}
        </h2>
        <div className="space-y-3">
          {data.books.map((b) => {
            const isOpen = expanded === b.book_id;
            return (
              <div
                key={b.book_id}
                className="rounded-xl border border-[var(--border)] bg-[var(--card)]"
              >
                <button
                  onClick={() => setExpanded(isOpen ? null : b.book_id)}
                  className="flex w-full items-center gap-3 px-4 py-3 text-left"
                >
                  <BookOpen className="h-4 w-4 shrink-0 text-[var(--primary)]" />
                  <span className="min-w-0 flex-1 truncate text-[14px] font-medium text-[var(--foreground)]">
                    {b.name}
                  </span>
                  <span className="shrink-0 text-[12px] tabular-nums text-[var(--muted-foreground)]">
                    {b.avg_mastery_pct}% · {b.mastered_count}/{b.kp_count}
                  </span>
                  <ChevronDown
                    className={`h-4 w-4 shrink-0 text-[var(--muted-foreground)] transition-transform ${
                      isOpen ? "rotate-180" : ""
                    }`}
                  />
                </button>
                {isOpen && (
                  <div className="border-t border-[var(--border)] px-4 py-3">
                    <KGraphMermaid pathId={b.book_id} />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}

function StatCard({
  icon: Icon,
  label,
  value,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: number | string;
}) {
  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-3">
      <div className="flex items-center gap-1.5 text-[12px] text-[var(--muted-foreground)]">
        <Icon className="h-3.5 w-3.5" />
        {label}
      </div>
      <div className="mt-1 text-[22px] font-semibold leading-none tabular-nums text-[var(--foreground)]">
        {value}
      </div>
    </div>
  );
}
