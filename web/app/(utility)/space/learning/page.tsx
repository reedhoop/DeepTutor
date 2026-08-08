"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import {
  GraduationCap,
  Loader2,
  RotateCcw,
  Trash2,
  MessageSquare,
  BookText,
  CalendarDays,
  AlertTriangle,
  ChevronRight,
  Network,
} from "lucide-react";

import {
  fetchAllProgress,
  fetchMasteryMap,
  deleteProgress,
  redoProgress,
  fetchErrorBook,
  fetchVariants,
  type ProgressSummary,
  type MasteryMapResult,
  type ObjectiveStatus,
  type ErrorBookResult,
  type VariantExercise,
} from "@/lib/learning-api";
import { getOrCreateSessionByPath } from "@/lib/session-api";
import KGraphMermaid from "@/components/kgraph/KGraphMermaid";
import MarkdownRenderer from "@/components/common/MarkdownRenderer";

/**
 * Mastery Path dashboard — the persistent "screen" of the mastery experience.
 *
 * The tutoring itself runs on the chat agent loop (pick "Mastery Path" mode in
 * Chat); this page is the map of where the learner stands. It reads the
 * gate-accurate snapshot from ``/progress/{id}/map`` (per-type status computed
 * by ``deeptutor.learning.policy``) so the colours here agree with the gate the
 * tutor enforces. A path is keyed by its chat session, so "Continue" reopens
 * that session in mastery mode.
 */
export default function MasteryPathPage() {
  const { i18n } = useTranslation();
  const zh = i18n.language?.toLowerCase().startsWith("zh");
  const tr = useCallback((cn: string, en: string) => (zh ? cn : en), [zh]);
  const router = useRouter();

  const [paths, setPaths] = useState<ProgressSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<MasteryMapResult | null>(null);
  const [loadingList, setLoadingList] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  // Guard against double-click while we're awaiting the get-or-create call.
  const [continuing, setContinuing] = useState(false);

  const loadList = useCallback(async () => {
    setLoadingList(true);
    try {
      const result = await fetchAllProgress();
      const withContent = result.summaries
        .filter((s) => s.kp_count > 0)
        .sort((a, b) => b.updated_at - a.updated_at);
      setPaths(withContent);
      setSelected((prev) => prev ?? withContent[0]?.book_id ?? null);
    } catch {
      setPaths([]);
    } finally {
      setLoadingList(false);
    }
  }, []);

  useEffect(() => {
    loadList();
  }, [loadList]);

  // Preselect a path when arriving from the textbook navigator (?path=kgraph_...).
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const p = params.get("path");
    if (p) setSelected(p);
  }, []);

  useEffect(() => {
    if (!selected) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    setLoadingDetail(true);
    fetchMasteryMap(selected)
      .then((result) => {
        if (!cancelled) setDetail(result);
      })
      .catch(() => {
        if (!cancelled) setDetail(null);
      })
      .finally(() => {
        if (!cancelled) setLoadingDetail(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selected]);

  const handleDelete = useCallback(
    async (pathId: string) => {
      if (
        !window.confirm(
          tr("确定删除这条精通之路？", "Delete this mastery path?"),
        )
      )
        return;
      await deleteProgress(pathId);
      if (selected === pathId) setSelected(null);
      await loadList();
    },
    [selected, loadList, tr],
  );

  const handleRedo = useCallback(
    async (pathId: string) => {
      if (
        !window.confirm(
          tr(
            "重置进度？知识点保留，但掌握度与复习计划清空。",
            "Reset progress? Objectives are kept, but mastery and reviews are cleared.",
          ),
        )
      )
        return;
      await redoProgress(pathId);
      const result = await fetchMasteryMap(pathId);
      setDetail(result);
    },
    [tr],
  );

  return (
    <div className="flex h-full">
      {/* Path list */}
      <aside className="w-64 shrink-0 border-r border-[var(--border)] flex flex-col">
        <header className="px-4 py-3 border-b border-[var(--border)]">
          <div className="flex items-center gap-2 text-[var(--foreground)]">
            <GraduationCap className="w-4 h-4" />
            <h1 className="text-sm font-semibold">
              {tr("精通之路", "Mastery Path")}
            </h1>
          </div>
          <p className="mt-1 text-xs text-[var(--muted-foreground)]">
            {tr(
              "掌握式学习：硬门槛 + 间隔复习",
              "Mastery-based learning: hard gate + spaced review",
            )}
          </p>
        </header>
        <div className="flex-1 overflow-y-auto p-2 space-y-1">
          {loadingList ? (
            <div className="flex items-center justify-center py-8 text-[var(--muted-foreground)]">
              <Loader2 className="w-4 h-4 animate-spin" />
            </div>
          ) : paths.length === 0 ? (
            <p className="px-2 py-3 text-xs text-[var(--muted-foreground)] leading-relaxed">
              {tr(
                "还没有精通之路。去「课本导航」点选一节课，让系统按知识链生成一条可跟进的学习路径；或在「对话」里用 Mastery Path 模式开始。",
                "No paths yet. Open Textbook Navigator and pick a section to generate a knowledge-chain path, or start one in Chat with Mastery Path mode.",
              )}
            </p>
          ) : (
            paths.map((path) => (
              <button
                key={path.book_id}
                onClick={() => setSelected(path.book_id)}
                className={`w-full text-left px-3 py-2 rounded-md transition-colors cursor-pointer ${
                  selected === path.book_id
                    ? "bg-[var(--primary)]/10 ring-1 ring-[var(--primary)]/30"
                    : "hover:bg-[var(--accent)]"
                }`}
              >
                <div className="truncate text-sm text-[var(--foreground)]">
                  {path.name}
                </div>
                <div className="mt-0.5 text-xs text-[var(--muted-foreground)]">
                  {path.kp_count} {tr("个知识点", "objectives")} ·{" "}
                  {path.avg_mastery_pct}%
                </div>
              </button>
            ))
          )}
        </div>
        <footer className="p-2 border-t border-[var(--border)] space-y-1.5">
          <button
            onClick={() => router.push("/textbook")}
            className="w-full flex items-center justify-center gap-1.5 px-3 py-2 text-sm rounded-md border border-[var(--border)] text-[var(--foreground)] hover:bg-[var(--accent)] transition-colors cursor-pointer"
          >
            <BookText className="w-3.5 h-3.5" />
            {tr("从课本选择", "From textbook")}
          </button>
          <button
            onClick={() => router.push("/home")}
            className="w-full flex items-center justify-center gap-1.5 px-3 py-2 text-sm rounded-md bg-[var(--primary)] text-[var(--primary-foreground)] hover:opacity-90 transition-opacity cursor-pointer"
          >
            <MessageSquare className="w-3.5 h-3.5" />
            {tr("新建（在对话中）", "New (in Chat)")}
          </button>
        </footer>
      </aside>

      {/* Selected path map */}
      <section className="flex-1 overflow-y-auto">
        {loadingDetail ? (
          <div className="flex items-center justify-center h-full text-[var(--muted-foreground)]">
            <Loader2 className="w-5 h-5 animate-spin" />
          </div>
        ) : !detail ? (
          <div className="flex flex-col items-center justify-center h-full text-center px-6 text-[var(--muted-foreground)]">
            <GraduationCap className="w-10 h-10 mb-3 opacity-40" />
            <p className="text-sm max-w-sm leading-relaxed">
              {tr(
                "选择一条精通之路查看进度地图，或在「对话」里用 Mastery Path 模式开始。",
                "Select a path to see its progress map, or start one in Chat with Mastery Path mode.",
              )}
            </p>
          </div>
        ) : (
          <MapView
            result={detail}
            zh={!!zh}
            tr={tr}
            continuing={continuing}
            onContinue={async () => {
              if (!selected || continuing) return;
              setContinuing(true);
              const name =
                paths.find((p) => p.book_id === selected)?.name || "";
              try {
                // Bind this chapter to a single chat session: if the user
                // already opened this mastery path before, resume that
                // session instead of creating a new "新对话".
                const { session, created } = await getOrCreateSessionByPath(
                  selected,
                  "mastery_path",
                  name,
                );
                router.push(
                  `/home/${encodeURIComponent(session.session_id)}?mastery_path=${encodeURIComponent(
                    selected,
                  )}&created=${created ? "1" : "0"}`,
                );
                return;
              } catch (err) {
                console.error(
                  "Failed to bind mastery path to session, falling back",
                  err,
                );
              } finally {
                setContinuing(false);
              }
              // Fallback: legacy draft flow so the user is never stranded.
              router.push(
                `/home?mastery_path=${encodeURIComponent(selected)}&title=${encodeURIComponent(name)}`,
              );
            }}
            onRedo={() => selected && handleRedo(selected)}
            onDelete={() => selected && handleDelete(selected)}
          />
        )}
      </section>
    </div>
  );
}

const STATUS_META: Record<
  ObjectiveStatus,
  { cn: string; en: string; className: string }
> = {
  mastered: { cn: "已掌握", en: "Mastered", className: "text-green-500" },
  learning: { cn: "学习中", en: "Learning", className: "text-yellow-500" },
  new: {
    cn: "未开始",
    en: "Not started",
    className: "text-[var(--muted-foreground)]",
  },
};

const ACTION_LABEL: Record<string, { cn: string; en: string }> = {
  probe: { cn: "先探查是否已掌握", en: "Probe — test out first" },
  practice: { cn: "练习直到达标", en: "Practice until the gate clears" },
  assess: { cn: "用自己的话解释", en: "Explain it in your own words" },
  review: { cn: "到期复习", en: "Due for review" },
  answer_pending: {
    cn: "有待回答的问题",
    en: "A question is awaiting your answer",
  },
  complete: { cn: "已全部掌握 🎉", en: "All mastered 🎉" },
};

// ── Four-colour mastery buckets (薄弱 / 合格 / 良好 / 精通) ───────────────────
// Derived from each objective's raw ``mastery`` float so the dashboard's colours
// agree with the gate the tutor enforces, but shown at the finer four-level
// granularity the learning-report calls for.
type Bucket = "weak" | "qualified" | "good" | "proficient";

const BUCKET_META: Record<
  Bucket,
  { cn: string; en: string; dot: string }
> = {
  weak: { cn: "薄弱", en: "Weak", dot: "bg-red-500" },
  qualified: { cn: "合格", en: "Qualified", dot: "bg-yellow-500" },
  good: { cn: "良好", en: "Good", dot: "bg-sky-500" },
  proficient: { cn: "精通", en: "Proficient", dot: "bg-green-500" },
};

const BUCKET_ORDER: Bucket[] = ["weak", "qualified", "good", "proficient"];

function bucketOf(mastery: number): Bucket {
  if (mastery >= 0.9) return "proficient";
  if (mastery >= 0.7) return "good";
  if (mastery >= 0.4) return "qualified";
  return "weak";
}

function BucketDot({ mastery }: { mastery: number }) {
  const b = bucketOf(mastery);
  return <span className={`w-2.5 h-2.5 shrink-0 rounded-full ${BUCKET_META[b].dot}`} />;
}

/**
 * A lightweight weekly plan derived entirely from real signals: the number of
 * objectives still un-mastered and the due reviews from the spaced-repetition
 * scheduler. The 7-day strip spreads that load evenly as a suggestion.
 */
function WeeklyPlan({
  dueReviews,
  remaining,
  zh,
  tr,
}: {
  dueReviews: number;
  remaining: number;
  zh: boolean;
  tr: (cn: string, en: string) => string;
}) {
  const planTotal = remaining + dueReviews;
  const perDay = planTotal > 0 ? Math.max(1, Math.ceil(planTotal / 7)) : 0;
  const days = zh
    ? ["一", "二", "三", "四", "五", "六", "日"]
    : ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  return (
    <div className="mt-4 rounded-lg border border-[var(--border)] p-3">
      <div className="flex items-center gap-2 text-sm font-medium text-[var(--foreground)]">
        <CalendarDays className="w-4 h-4" />
        {tr("本周建议", "This week's plan")}
      </div>
      <p className="mt-1 text-xs text-[var(--muted-foreground)] leading-relaxed">
        {zh
          ? `还有 ${remaining} 个未掌握${dueReviews > 0 ? `，其中 ${dueReviews} 个到期复习` : ""}；建议每天推进约 ${perDay} 个。`
          : `${remaining} objectives left${dueReviews > 0 ? `, ${dueReviews} due for review` : ""}; aim for ~${perDay}/day.`}
      </p>
      <div className="mt-2 grid grid-cols-7 gap-1">
        {days.map((d) => (
          <div
            key={d}
            className="rounded-md bg-[var(--accent)]/50 px-1 py-1.5 text-center"
          >
            <div className="text-[10px] text-[var(--muted-foreground)]">{d}</div>
            <div className="text-[11px] font-medium text-[var(--foreground)]">
              {perDay || "—"}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function MapView({
  result,
  zh,
  tr,
  continuing,
  onContinue,
  onRedo,
  onDelete,
}: {
  result: MasteryMapResult;
  zh: boolean;
  tr: (cn: string, en: string) => string;
  continuing: boolean;
  onContinue: () => Promise<void> | void;
  onRedo: () => void;
  onDelete: () => void;
}) {
  const { map, next } = result;
  const pct = map.counts.total
    ? Math.round((map.counts.mastered / map.counts.total) * 100)
    : 0;
  const action = ACTION_LABEL[next.action] ?? {
    cn: next.reason,
    en: next.reason,
  };

  const allKps = map.modules.flatMap((m) => m.knowledge_points);
  const kpNames: Record<string, string> = {};
  for (const kp of allKps) kpNames[kp.id] = kp.name;
  const bucketCounts: Record<Bucket, number> = {
    weak: 0,
    qualified: 0,
    good: 0,
    proficient: 0,
  };
  for (const kp of allKps) bucketCounts[bucketOf(kp.mastery)]++;
  const totalKp = allKps.length || 1;

  return (
    <div className="max-w-2xl mx-auto px-6 py-5">
      {/* Header: progress + next + actions */}
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 text-sm text-[var(--muted-foreground)]">
            <span>
              {map.counts.mastered}/{map.counts.total}{" "}
              {tr("已掌握", "mastered")}
            </span>
            {map.due_reviews > 0 && (
              <span className="text-yellow-600">
                · {map.due_reviews} {tr("项待复习", "due for review")}
              </span>
            )}
          </div>
            <div className="mt-1.5 h-1.5 w-full rounded-full bg-[var(--accent)] overflow-hidden">
              <div
                className="h-full bg-green-500 transition-all"
                style={{ width: `${pct}%` }}
              />
            </div>
            {/* Four-colour mastery distribution (薄弱 / 合格 / 良好 / 精通) */}
            <div className="mt-2 flex h-2 w-full overflow-hidden rounded-full bg-[var(--accent)]">
              {BUCKET_ORDER.map((b) => (
                <div
                  key={b}
                  className={BUCKET_META[b].dot}
                  style={{ width: `${(bucketCounts[b] / totalKp) * 100}%` }}
                />
              ))}
            </div>
            <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-[var(--muted-foreground)]">
              {BUCKET_ORDER.map((b) => (
                <span key={b} className="flex items-center gap-1">
                  <span className={`w-2 h-2 rounded-full ${BUCKET_META[b].dot}`} />
                  {zh ? BUCKET_META[b].cn : BUCKET_META[b].en} {bucketCounts[b]}
                </span>
              ))}
            </div>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <button
            onClick={onRedo}
            title={tr("重置进度", "Reset progress")}
            className="p-1.5 rounded-md text-[var(--muted-foreground)] hover:bg-[var(--accent)] cursor-pointer"
          >
            <RotateCcw className="w-4 h-4" />
          </button>
          <button
            onClick={onDelete}
            title={tr("删除", "Delete")}
            className="p-1.5 rounded-md text-[var(--muted-foreground)] hover:bg-red-500/10 hover:text-red-500 cursor-pointer"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Next step */}
      <button
        onClick={onContinue}
        disabled={continuing}
        className="mt-4 w-full text-left rounded-lg border border-[var(--border)] hover:border-[var(--primary)]/40 hover:bg-[var(--accent)] p-3 transition-colors cursor-pointer disabled:opacity-60 disabled:cursor-wait"
      >
        <div className="text-xs text-[var(--muted-foreground)]">
          {tr("接下来", "Next")}
        </div>
        <div className="mt-0.5 text-sm font-medium text-[var(--foreground)]">
          {next.action === "complete"
            ? tr(action.cn, action.en)
            : `${next.knowledge_point_name} — ${tr(action.cn, action.en)}`}
        </div>
        <div className="mt-1 text-xs text-[var(--primary)]">
          {continuing ? (
            <span className="inline-flex items-center gap-1.5">
              <Loader2 className="w-3 h-3 animate-spin" />
              {tr("打开对话中…", "Opening chat…")}
            </span>
          ) : (
            tr("在对话中继续辅导 →", "Continue tutoring in Chat →")
          )}
        </div>
      </button>

      {/* Weekly plan — derived from due reviews + remaining objectives */}
      <WeeklyPlan
        dueReviews={map.due_reviews}
        remaining={map.counts.total - map.counts.mastered}
        zh={zh}
        tr={tr}
      />

      {/* Module / objective map */}
      <div className="mt-5 space-y-4">
        {map.modules.map((module) => (
          <div key={module.id}>
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-medium text-[var(--foreground)]">
                {module.name}
              </h3>
              <span className="text-xs text-[var(--muted-foreground)]">
                {module.mastered}/{module.total}
              </span>
            </div>
            <div className="mt-1.5 space-y-1">
              {module.knowledge_points.map((kp) => (
                <div
                  key={kp.id}
                  className="flex items-center gap-2 px-2 py-1 rounded-md text-sm"
                >
                  <BucketDot mastery={kp.mastery} />
                  <span className="flex-1 truncate text-[var(--foreground)]">
                    {kp.name}
                  </span>
                  <span className="text-[10px] uppercase tracking-wide text-[var(--muted-foreground)]">
                    {kp.type}
                  </span>
                  <span
                    className={`text-xs ${STATUS_META[kp.status].className}`}
                  >
                    {zh ? STATUS_META[kp.status].cn : STATUS_META[kp.status].en}
                  </span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      {/* ER-1: KGraph visualization of the path's objectives. The in-path
          KP ids are KGraph concept ids (see ErrorBook), so the backend can
          connect them by prerequisite edges and colour them by mastery. */}
      <section className="mt-6">
        <div className="flex items-center gap-2 text-sm font-medium text-[var(--foreground)]">
          <Network className="h-4 w-4" />
          {tr("知识图谱", "Knowledge Graph")}
        </div>
        <p className="mt-1 text-xs text-[var(--muted-foreground)]">
          {tr(
            "本路径知识点在课程知识图谱中的前置 / 后继关系，按掌握度着色。",
            "How this path's objectives connect in the curriculum graph, coloured by mastery.",
          )}
        </p>
        <div className="mt-2 rounded-lg border border-[var(--border)] bg-[var(--card)] p-3">
          <KGraphMermaid pathId={result.book_id} />
        </div>
      </section>

      {/* Stage 3: Error book + weak-point backfill */}
      <ErrorBook bookId={result.book_id} kpNames={kpNames} zh={zh} tr={tr} />
    </div>
  );
}

// ── Error book / weak-point backfill (Stage 3) ─────────────────────────────
// Reads /progress/{book_id}/error-book. The in-path KP id is also the KGraph
// concept id, so the "看变式题" preview can query /kgraph/variants/{concept_id}
// directly (teacher view, answers shown) to close the loop on screen.

const ERROR_TYPE_DOT: Record<string, string> = {
  知识结构性: "bg-red-500",
  理解偏差型: "bg-orange-500",
  应用错误: "bg-amber-500",
  元认知型: "bg-violet-500",
};

function ErrorBook({
  bookId,
  kpNames,
  zh,
  tr,
}: {
  bookId: string;
  kpNames: Record<string, string>;
  zh: boolean;
  tr: (cn: string, en: string) => string;
}) {
  const [data, setData] = useState<ErrorBookResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [errored, setErrored] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [variants, setVariants] = useState<VariantExercise[] | null>(null);
  const [loadingVariants, setLoadingVariants] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    setErrored(false);
    fetchErrorBook(bookId, { topK: 10 })
      .then((d) => setData(d))
      .catch(() => setErrored(true))
      .finally(() => setLoading(false));
  }, [bookId]);

  useEffect(() => {
    load();
  }, [load]);

  const toggleVariants = useCallback(
    async (conceptId: string) => {
      if (expanded === conceptId) {
        setExpanded(null);
        setVariants(null);
        return;
      }
      setExpanded(conceptId);
      setLoadingVariants(true);
      setVariants(null);
      try {
        const res = await fetchVariants(conceptId, { count: 4, bookId });
        setVariants(res.variants);
      } catch {
        setVariants([]);
      } finally {
        setLoadingVariants(false);
      }
    },
    [expanded, bookId],
  );

  if (loading) {
    return (
      <div className="mt-6 flex items-center gap-2 text-sm text-[var(--muted-foreground)]">
        <Loader2 className="w-4 h-4 animate-spin" />
        {tr("加载错题本…", "Loading error book…")}
      </div>
    );
  }
  if (errored) {
    return (
      <div className="mt-6 rounded-lg border border-[var(--border)] p-3 text-sm text-[var(--muted-foreground)]">
        {tr("错题本暂时不可用", "Error book unavailable")}
      </div>
    );
  }
  if (!data || (data.total_records === 0 && data.weak_points.length === 0)) {
    return (
      <div className="mt-6 rounded-lg border border-dashed border-[var(--border)] p-4 text-center text-sm text-[var(--muted-foreground)]">
        {tr(
          "还没有错题。在「对话」里用 Mastery Path 模式做题，答错的会自动归集到这里，并生成薄弱回灌建议。",
          "No errors yet. Answer questions in Chat with Mastery Path mode — wrong answers are collected here automatically, with weak-point backfill suggestions.",
        )}
      </div>
    );
  }

  const typeEntries = Object.entries(data.by_error_type);

  return (
    <div className="mt-6 rounded-lg border border-[var(--border)] p-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-sm font-medium text-[var(--foreground)]">
          <AlertTriangle className="w-4 h-4 text-red-500" />
          {tr("错题本 / 薄弱回灌", "Error Book / Weak-point Backfill")}
        </div>
        <span className="text-xs text-[var(--muted-foreground)]">
          {data.open_records} {tr("道待订正", "open")} · {data.graduated_records}{" "}
          {tr("道已订正", "graduated")}
        </span>
      </div>

      {/* Error-type distribution */}
      {typeEntries.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {typeEntries.map(([label, n]) => (
            <span
              key={label}
              className="inline-flex items-center gap-1.5 rounded-full bg-[var(--accent)] px-2.5 py-1 text-xs text-[var(--foreground)]"
            >
              <span
                className={`w-2 h-2 rounded-full ${
                  ERROR_TYPE_DOT[label] ?? "bg-gray-400"
                }`}
              />
              {label} · {n}
            </span>
          ))}
        </div>
      )}

      {/* Weak points ranked worst-first */}
      {data.weak_points.length > 0 && (
        <div className="mt-4 space-y-2">
          <div className="text-xs font-medium text-[var(--muted-foreground)]">
            {tr("薄弱点（按优先级排序）", "Weak points (by priority)")}
          </div>
          {data.weak_points.map((w) => (
            <div
              key={w.knowledge_point_id}
              className="rounded-md border border-[var(--border)] p-2.5"
            >
              <div className="flex items-center justify-between gap-2">
                <div className="min-w-0">
                  <div className="truncate text-sm text-[var(--foreground)]">
                    {w.name}
                  </div>
                  <div className="mt-0.5 text-xs text-[var(--muted-foreground)]">
                    <MarkdownRenderer
                      content={w.reason}
                      variant="compact"
                      enableMath
                    />
                  </div>
                </div>
                <button
                  onClick={() => toggleVariants(w.knowledge_point_id)}
                  className="shrink-0 rounded-md border border-[var(--border)] px-2 py-1 text-xs text-[var(--primary)] hover:bg-[var(--accent)] cursor-pointer"
                >
                  {expanded === w.knowledge_point_id
                    ? tr("收起变式题", "Hide variants")
                    : tr("看变式题", "Show variants")}
                </button>
              </div>
              <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-[var(--muted-foreground)]">
                <span>
                  {tr("掌握度", "Mastery")} {Math.round(w.mastery * 100)}%
                </span>
                <span>
                  {tr("错题", "Errors")} {w.error_count}
                </span>
                {w.consecutive_wrong > 0 && (
                  <span>
                    {tr("连错", "Streak")} {w.consecutive_wrong}
                  </span>
                )}
                {w.unmet_prereqs.length > 0 && (
                  <span className="text-red-500">
                    {tr("未掌握前置", "Unmet prereq")}:{" "}
                    {w.unmet_prereqs
                      .map((p) => kpNames[p] ?? p)
                      .join("、")}
                  </span>
                )}
              </div>

              {/* Variant preview (teacher view, answers shown) */}
              {expanded === w.knowledge_point_id && (
                <div className="mt-2 space-y-2 border-t border-[var(--border)] pt-2">
                  {loadingVariants ? (
                    <div className="flex items-center gap-2 text-xs text-[var(--muted-foreground)]">
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      {tr("加载变式题…", "Loading variants…")}
                    </div>
                  ) : variants && variants.length > 0 ? (
                    variants.map((v) => (
                      <div
                        key={v.exercise_id}
                        className="rounded-md bg-[var(--accent)]/40 p-2 text-xs"
                      >
                        <div className="flex items-center gap-2 text-[var(--muted-foreground)]">
                          <span className="rounded bg-[var(--background)] px-1.5 py-0.5">
                            {v.source_type || v.question_type}
                          </span>
                          {v.difficulty_label && (
                            <span className="rounded bg-[var(--background)] px-1.5 py-0.5">
                              {v.difficulty_label}
                            </span>
                          )}
                          <span className="rounded bg-[var(--background)] px-1.5 py-0.5">
                            {v.source === "direct"
                              ? tr("直连", "direct")
                              : v.source === "section"
                                ? tr("同节", "section")
                                : v.source === "neighbor"
                                  ? tr("邻节", "neighbor")
                                  : tr("同章", "chapter")}
                          </span>
                        </div>
                        <div className="mt-1 text-[var(--foreground)] leading-relaxed">
                          <MarkdownRenderer
                            content={v.question}
                            variant="compact"
                            enableMath
                          />
                        </div>
                        {v.options.length > 0 && (
                          <div className="mt-1 text-[var(--muted-foreground)]">
                            <MarkdownRenderer
                              content={v.options.join("　")}
                              variant="compact"
                              enableMath
                            />
                          </div>
                        )}
                        <div className="mt-1 text-green-600">
                          {tr("答案", "Answer")}：
                          <MarkdownRenderer
                            content={v.expected_answer}
                            variant="compact"
                            enableMath
                            className="text-green-600"
                          />
                          {v.analysis && (
                            <>
                              {" · "}
                              <MarkdownRenderer
                                content={v.analysis}
                                variant="compact"
                                enableMath
                                className="text-[var(--muted-foreground)]"
                              />
                            </>
                          )}
                        </div>
                      </div>
                    ))
                  ) : (
                    <div className="text-xs text-[var(--muted-foreground)]">
                      {tr("没有可返回的变式题", "No variants available")}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Root-cause-first backfill order */}
      {data.backfill_order.length > 0 && (
        <div className="mt-4 rounded-md bg-red-500/5 p-2.5">
          <div className="flex items-center gap-1.5 text-xs font-medium text-red-600">
            <ChevronRight className="w-3.5 h-3.5" />
            {tr("回灌顺序（根因优先）", "Backfill order (root cause first)")}
          </div>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {data.backfill_order.map((id, i) => (
              <span
                key={`${id}-${i}`}
                className="rounded-md bg-[var(--background)] px-2 py-1 text-xs text-[var(--foreground)]"
              >
                {i + 1}. {kpNames[id] ?? id}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Raw error records */}
      {data.records.length > 0 && (
        <details className="mt-3">
          <summary className="cursor-pointer text-xs text-[var(--muted-foreground)]">
            {tr("错题明细", "Error record details")} ({data.records.length})
          </summary>
          <div className="mt-2 space-y-1">
            {data.records.map((r) => (
              <div
                key={r.id}
                className="flex items-center justify-between gap-2 text-xs text-[var(--muted-foreground)]"
              >
                <span className="truncate">
                  {r.knowledge_point_name || r.knowledge_point_id}
                </span>
                <span className="flex items-center gap-2 shrink-0">
                  <span
                    className={`w-2 h-2 rounded-full ${
                      ERROR_TYPE_DOT[r.error_type_label] ?? "bg-gray-400"
                    }`}
                  />
                  {r.error_type_label}
                  {r.retry_count > 0 && (
                    <span>· {tr("重试", "retry")} {r.retry_count}</span>
                  )}
                  <span>· {r.status}</span>
                </span>
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}
