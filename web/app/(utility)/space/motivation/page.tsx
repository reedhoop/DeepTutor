"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useTranslation } from "react-i18next";
import {
  CalendarCheck,
  CalendarDays,
  CheckCircle2,
  Crown,
  Flame,
  Layers,
  Loader2,
  Medal,
  PenLine,
  Sparkles,
  Sun,
  Target,
  type LucideIcon,
} from "lucide-react";

import { fetchMotivation, type Motivation } from "@/lib/learning-api";

type Lang = { zh: string; en: string };

interface BadgeMeta {
  name: Lang;
  desc: Lang;
  icon: LucideIcon;
}

// Display catalogue keyed by the backend badge `id`. The backend owns the
// earn-logic; this file owns localised names/descriptions/icons. Keep ids in
// sync with deeptutor/_local/motivation_overlay._build_badges.
const BADGE_CATALOG: Record<string, BadgeMeta> = {
  first_quiz: {
    name: { zh: "初次练习", en: "First Attempt" },
    desc: { zh: "完成你的第一次练习。", en: "Complete your first practice quiz." },
    icon: PenLine,
  },
  first_mastery: {
    name: { zh: "初次掌握", en: "First Mastery" },
    desc: { zh: "首个知识点达到掌握。", en: "Reach mastery on your first knowledge point." },
    icon: Sparkles,
  },
  quiz_run_5: {
    name: { zh: "连对达人", en: "Streak Shooter" },
    desc: { zh: "连续答对 5 题。", en: "Answer 5 quizzes correctly in a row." },
    icon: Target,
  },
  streak_3: {
    name: { zh: "三日热身", en: "3-Day Warmup" },
    desc: { zh: "连续学习 3 天。", en: "Learn on 3 consecutive days." },
    icon: CalendarCheck,
  },
  streak_7: {
    name: { zh: "一周坚持", en: "Week Streak" },
    desc: { zh: "连续学习 7 天。", en: "Learn on 7 consecutive days." },
    icon: CalendarDays,
  },
  streak_30: {
    name: { zh: "月度学者", en: "Month Scholar" },
    desc: { zh: "连续学习 30 天。", en: "Learn on 30 consecutive days." },
    icon: Flame,
  },
  mastery_10: {
    name: { zh: "十点精通", en: "Deca-Master" },
    desc: { zh: "掌握 10 个知识点。", en: "Master 10 knowledge points." },
    icon: Target,
  },
  mastery_50: {
    name: { zh: "半百通关", en: "Half-Century" },
    desc: { zh: "掌握 50 个知识点。", en: "Master 50 knowledge points." },
    icon: Medal,
  },
  mastery_100: {
    name: { zh: "百点宗师", en: "Centurion" },
    desc: { zh: "掌握 100 个知识点。", en: "Master 100 knowledge points." },
    icon: Crown,
  },
  error_graduate: {
    name: { zh: "错题克服", en: "Error Conqueror" },
    desc: { zh: "让一道错题达到已复习/毕业状态。", en: "Graduate an error record (reviewed/graduated)." },
    icon: CheckCircle2,
  },
  all_types: {
    name: { zh: "全科素养", en: "All-Rounder" },
    desc: { zh: "四种知识类型各掌握至少 1 个。", en: "Master at least one of each knowledge type." },
    icon: Layers,
  },
  active_10: {
    name: { zh: "十日光阴", en: "Ten Days" },
    desc: { zh: "累计活跃学习 10 天。", en: "Be active on 10 distinct days." },
    icon: Sun,
  },
};

const BADGE_ORDER = Object.keys(BADGE_CATALOG);
const SEEN_KEY = "dt_seen_badges";

/**
 * ER-14 motivation view — a read-only, personal-progress-only gamification layer.
 * Streak / badges / points are derived server-side from practice & mastery data;
 * this page only renders them. No competitive leaderboard, per the ER-14 spec.
 */
export default function MotivationPage() {
  const { i18n } = useTranslation();
  const zh = i18n.language?.toLowerCase().startsWith("zh");
  const tr = useCallback((l: Lang) => (zh ? l.zh : l.en), [zh]);

  const [data, setData] = useState<Motivation | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [newBadges, setNewBadges] = useState<string[]>([]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchMotivation()
      .then((d) => {
        if (cancelled) return;
        setData(d);
        if (typeof window !== "undefined") {
          const seen: string[] = JSON.parse(localStorage.getItem(SEEN_KEY) || "[]");
          const earned = d.badges.filter((b) => b.earned).map((b) => b.id);
          const fresh = earned.filter((id) => !seen.includes(id));
          if (fresh.length) setNewBadges(fresh);
          localStorage.setItem(SEEN_KEY, JSON.stringify(earned));
        }
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const earnedCount = useMemo(
    () => (data ? data.badges.filter((b) => b.earned).length : 0),
    [data],
  );

  if (loading) {
    return (
      <div className="flex items-center gap-2 px-1 py-10 text-sm text-[var(--muted-foreground)]">
        <Loader2 className="h-4 w-4 animate-spin" />
        {tr({ zh: "加载学习激励…", en: "Loading motivation…" })}
      </div>
    );
  }
  if (error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-600">
        {tr({ zh: "学习激励加载失败：", en: "Failed to load motivation: " })}
        {error}
      </div>
    );
  }

  if (!data || !data.has_data) {
    return (
      <div className="space-y-10">
        <Header tr={tr} />
        <div className="rounded-lg border border-dashed border-[var(--border)] bg-[var(--muted)]/30 px-4 py-10 text-center text-sm text-[var(--muted-foreground)]">
          {tr({
            zh: "还没有学习记录。前往「精通之路」做几道题，这里会累积你的连续学习、徽章与积分。",
            en: "No learning records yet. Start a mastery path and your streaks, badges, and points will accumulate here.",
          })}
          <div className="mt-4">
            <Link
              href="/space/learning"
              className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3 py-1.5 text-[13px] font-medium text-[var(--primary-foreground)] hover:opacity-90"
            >
              {tr({ zh: "开始学习", en: "Start learning" })}
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-10">
      <Header tr={tr} />

      {newBadges.length > 0 && (
        <div className="flex items-center gap-3 rounded-xl border border-amber-300/60 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300">
          <Sparkles className="h-4 w-4 shrink-0" />
          <span>
            {tr({ zh: "新解锁 ", en: "Newly unlocked: " })}
            <span className="font-medium">
              {newBadges
                .map((id) => tr(BADGE_CATALOG[id]?.name ?? { zh: id, en: id }))
                .join("、")}
            </span>
          </span>
          <button
            onClick={() => setNewBadges([])}
            className="ml-auto text-amber-600/70 hover:text-amber-800 dark:text-amber-300/70 dark:hover:text-amber-200"
          >
            ✕
          </button>
        </div>
      )}

      {/* Top stats */}
      <section className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <StatCard
          icon={Flame}
          label={tr({ zh: "连续学习", en: "Day streak" })}
          value={`${data.streak.current}`}
          unit={tr({ zh: "天", en: "days" })}
          accent="text-orange-600 dark:text-orange-400"
          tile="bg-orange-500/10"
        />
        <StatCard
          icon={Sparkles}
          label={tr({ zh: "学习积分", en: "Points" })}
          value={`${data.points.total}`}
          unit={tr({ zh: "分", en: "pts" })}
          accent="text-violet-600 dark:text-violet-400"
          tile="bg-violet-500/10"
        />
        <StatCard
          icon={Target}
          label={tr({ zh: "已获徽章", en: "Badges" })}
          value={`${earnedCount}`}
          unit={`/ ${data.badges.length}`}
          accent="text-emerald-600 dark:text-emerald-400"
          tile="bg-emerald-500/10"
        />
      </section>

      {/* Streak detail + 14-day strip */}
      <section className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-4">
        <h2 className="mb-3 font-serif text-[16px] font-semibold tracking-tight text-[var(--foreground)]">
          {tr({ zh: "连续学习", en: "Learning Streak" })}
        </h2>
        <div className="flex flex-wrap gap-3">
          {data.streak.recent.map((d, i) => (
            <div
              key={d.date}
              title={d.date}
              className={`h-7 w-7 rounded-md ${
                d.active
                  ? "bg-orange-500 ring-2 ring-orange-300/50"
                  : "bg-[var(--muted)]"
              }`}
            >
              {i === data.streak.recent.length - 1 && (
                <span className="sr-only">{tr({ zh: "今日", en: "today" })}</span>
              )}
            </div>
          ))}
        </div>
        <div className="mt-3 grid grid-cols-2 gap-3 text-[13px] sm:grid-cols-4">
          <MiniStat
            label={tr({ zh: "当前连续", en: "Current" })}
            value={`${data.streak.current} ${tr({ zh: "天", en: "d" })}`}
          />
          <MiniStat
            label={tr({ zh: "最长连续", en: "Longest" })}
            value={`${data.streak.longest} ${tr({ zh: "天", en: "d" })}`}
          />
          <MiniStat
            label={tr({ zh: "累计活跃", en: "Active days" })}
            value={`${data.streak.active_days} ${tr({ zh: "天", en: "d" })}`}
          />
          <MiniStat
            label={tr({ zh: "最近活跃", en: "Last active" })}
            value={data.streak.last_active ?? "—"}
          />
        </div>
      </section>

      {/* Points breakdown */}
      <section className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-4">
        <h2 className="mb-3 font-serif text-[16px] font-semibold tracking-tight text-[var(--foreground)]">
          {tr({ zh: "积分明细", en: "Points Breakdown" })}
        </h2>
        <ul className="space-y-1.5 text-[13px]">
          <BreakdownRow
            tr={tr}
            label={tr({ zh: "练习次数", en: "Quiz attempts" })}
            pts={data.points.breakdown.quiz_attempts}
          />
          <BreakdownRow
            tr={tr}
            label={tr({ zh: "答对题数", en: "Correct answers" })}
            pts={data.points.breakdown.correct}
          />
          <BreakdownRow
            tr={tr}
            label={tr({ zh: "掌握知识点", en: "Mastered points" })}
            pts={data.points.breakdown.mastered}
          />
          <BreakdownRow
            tr={tr}
            label={tr({ zh: "活跃天数", en: "Active days" })}
            pts={data.points.breakdown.active_days}
          />
          <BreakdownRow
            tr={tr}
            label={tr({ zh: "徽章奖励", en: "Badge bonuses" })}
            pts={data.points.breakdown.badges}
          />
        </ul>
      </section>

      {/* Badge wall */}
      <section>
        <h2 className="mb-3 font-serif text-[16px] font-semibold tracking-tight text-[var(--foreground)]">
          {tr({ zh: "徽章墙", en: "Badge Wall" })}
        </h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {BADGE_ORDER.map((id) => {
            const meta = BADGE_CATALOG[id];
            const state = data.badges.find((b) => b.id === id);
            const earned = state?.earned ?? false;
            const progress = state?.progress ?? 0;
            const Icon = meta.icon;
            return (
              <div
                key={id}
                className={`rounded-xl border p-4 transition-colors ${
                  earned
                    ? "border-amber-300/70 bg-amber-50/60 dark:border-amber-500/30 dark:bg-amber-500/5"
                    : "border-[var(--border)] bg-[var(--card)] opacity-90"
                }`}
              >
                <div className="flex items-center gap-3">
                  <span
                    className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg ${
                      earned
                        ? "bg-amber-500/15 text-amber-600 dark:text-amber-400"
                        : "bg-[var(--muted)] text-[var(--muted-foreground)]"
                    }`}
                  >
                    <Icon size={18} strokeWidth={1.7} />
                  </span>
                  <div className="min-w-0">
                    <p className="truncate text-[14px] font-medium text-[var(--foreground)]">
                      {tr(meta.name)}
                    </p>
                    <p className="mt-0.5 text-[12px] text-[var(--muted-foreground)]">
                      {tr(meta.desc)}
                    </p>
                  </div>
                </div>
                <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-[var(--muted)]">
                  <div
                    className={`h-full rounded-full ${
                      earned ? "bg-amber-500" : "bg-[var(--primary)]/60"
                    }`}
                    style={{ width: `${Math.round(progress * 100)}%` }}
                  />
                </div>
                <p className="mt-1.5 text-right text-[11px] tabular-nums text-[var(--muted-foreground)]">
                  {earned
                    ? tr({ zh: "已解锁", en: "Unlocked" })
                    : `${Math.round(progress * 100)}%`}
                </p>
              </div>
            );
          })}
        </div>
        <p className="mt-4 text-[12px] text-[var(--muted-foreground)]">
          {tr({
            zh: "仅个人进度展示，无竞争排行。所有数据只读派生自你的练习与掌握度记录。",
            en: "Personal progress only — no leaderboards. All data is derived read-only from your practice and mastery records.",
          })}
        </p>
      </section>
    </div>
  );
}

function Header({ tr }: { tr: (l: Lang) => string }) {
  return (
    <header>
      <h1 className="flex items-center gap-2 font-serif text-[24px] font-semibold tracking-tight text-[var(--foreground)]">
        <Flame className="h-6 w-6 text-orange-500" />
        {tr({ zh: "学习激励", en: "Motivation" })}
      </h1>
      <p className="mt-1.5 max-w-2xl text-[13px] leading-relaxed text-[var(--muted-foreground)]">
        {tr({
          zh: "连续学习、掌握度徽章与学习积分 —— 全部由你的练习与掌握度只读派生，只为让你看见自己的坚持。",
          en: "Streaks, mastery badges, and points — all derived read-only from your practice and mastery, so you can see your own persistence.",
        })}
      </p>
    </header>
  );
}

function StatCard({
  icon: Icon,
  label,
  value,
  unit,
  accent,
  tile,
}: {
  icon: LucideIcon;
  label: string;
  value: string;
  unit: string;
  accent: string;
  tile: string;
}) {
  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-3">
      <div className={`flex items-center gap-1.5 text-[12px] ${accent}`}>
        <Icon className="h-3.5 w-3.5" />
        {label}
      </div>
      <div className="mt-1 text-[22px] font-semibold leading-none tabular-nums text-[var(--foreground)]">
        {value}
        <span className="ml-1 text-[12px] font-normal text-[var(--muted-foreground)]">
          {unit}
        </span>
      </div>
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wide text-[var(--muted-foreground)]">
        {label}
      </div>
      <div className="mt-0.5 text-[15px] font-medium tabular-nums text-[var(--foreground)]">
        {value}
      </div>
    </div>
  );
}

function BreakdownRow({
  label,
  pts,
  tr,
}: {
  label: string;
  pts: number;
  tr: (l: Lang) => string;
}) {
  return (
    <li className="flex items-center justify-between border-b border-[var(--border)]/60 pb-1.5 last:border-0">
      <span className="text-[var(--muted-foreground)]">{label}</span>
      <span className="tabular-nums text-[var(--foreground)]">
        +{pts} {tr({ zh: "分", en: "pts" })}
      </span>
    </li>
  );
}
