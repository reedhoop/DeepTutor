"use client";

import {
  AlertCircle,
  ArrowLeft,
  BookOpen,
  ChevronRight,
  Layers,
  Loader2,
  Network,
  Search,
  Sparkles,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import {
  kgAvailable,
  kgConcept,
  kgSearch,
  type KgCandidate,
  type KgConcept,
  type KgLiteConcept,
} from "@/lib/knowledge-api";

interface KgTabBodyProps {
  /** Optional concept name to focus the browser on when the tab opens. */
  concept?: string;
}

const SUGGESTIONS = [
  "勾股定理",
  "函数",
  "一元二次方程",
  "牛顿第一定律",
  "光合作用",
  "氧化还原反应",
];

function labelClass(label: string): string {
  switch (label) {
    case "Concept":
      return "bg-blue-500/10 text-blue-500";
    case "Skill":
      return "bg-purple-500/10 text-purple-500";
    case "Exercise":
      return "bg-amber-500/10 text-amber-600";
    case "Experiment":
      return "bg-emerald-500/10 text-emerald-600";
    default:
      return "bg-slate-500/10 text-slate-500";
  }
}

function Badge({ children, cls }: { children: ReactNode; cls: string }) {
  return (
    <span
      className={`inline-flex shrink-0 items-center rounded-md px-1.5 py-0.5 text-[10.5px] font-medium ${cls}`}
    >
      {children}
    </span>
  );
}

/**
 * Self-contained K12-KGraph browser. Lives inside the right-hand
 * SessionViewerPanel's ``kg`` tab:
 *
 *  • search box (debounced) → ranked candidate list
 *  • clicking a candidate (or a prerequisite / path node) opens its full
 *    curriculum card: definition, aliases, importance, examples,
 *    prerequisites chain (navigable), learning-path breadcrumb, and the
 *    aggregated textbook evidence.
 *
 * No external state — it talks straight to ``/api/v1/kg/*``.
 */
export default function KgTabBody({ concept }: KgTabBodyProps) {
  const { t } = useTranslation();
  const [inputValue, setInputValue] = useState(concept ?? "");
  const [results, setResults] = useState<KgCandidate[]>([]);
  const [selected, setSelected] = useState<KgConcept | null>(null);
  const [trail, setTrail] = useState<KgLiteConcept[]>([]);
  const [loadingResults, setLoadingResults] = useState(false);
  const [loadingConcept, setLoadingConcept] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [available, setAvailable] = useState<boolean | null>(null);
  const didInit = useRef(false);

  const doSearch = useCallback(async (q: string) => {
    const term = q.trim();
    if (!term) {
      setResults([]);
      return;
    }
    setLoadingResults(true);
    setError(null);
    try {
      const r = await kgSearch(term, { top_k: 8 });
      setAvailable(r.available);
      setResults(r.candidates);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoadingResults(false);
    }
  }, []);

  const openConcept = useCallback(async (id: string, name?: string) => {
    setLoadingConcept(true);
    setError(null);
    try {
      const c = await kgConcept(id);
      setSelected(c);
      setTrail((prev) => [...prev, { id: c.id, name: c.name, label: c.label }]);
      if (name) setInputValue(name);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoadingConcept(false);
    }
  }, []);

  const openByName = useCallback(
    async (name: string) => {
      setLoadingConcept(true);
      setError(null);
      try {
        const r = await kgSearch(name, { top_k: 1 });
        setAvailable(r.available);
        setResults(r.candidates);
        if (r.candidates.length === 0) {
          setError(t("kg.noMatch", "未找到匹配的概念，换个说法试试"));
          setLoadingConcept(false);
          return;
        }
        const top = r.candidates[0];
        const c = await kgConcept(top.id);
        setSelected(c);
        setTrail((prev) => [...prev, { id: c.id, name: c.name, label: c.label }]);
        setInputValue(c.name);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setLoadingConcept(false);
      }
    },
    [t],
  );

  // Debounced search as the user types; the very first run (when a concept
  // was passed in) resolves that concept directly instead of just listing.
  useEffect(() => {
    if (!didInit.current) {
      didInit.current = true;
      if (concept) {
        openByName(concept);
        return;
      }
    }
    const h = window.setTimeout(() => {
      if (inputValue.trim()) doSearch(inputValue);
    }, 300);
    return () => window.clearTimeout(h);
  }, [inputValue, concept, doSearch, openByName]);

  // One-shot availability probe (so we can show a clear "not loaded" state).
  useEffect(() => {
    kgAvailable()
      .then((r) => setAvailable(r.available))
      .catch(() => setAvailable(false));
  }, []);

  const showEmptyState = !selected && !loadingConcept && results.length === 0 && !inputValue.trim();

  const header = useMemo(
    () => (
      <div className="relative flex-1">
        <Search
          size={14}
          strokeWidth={1.9}
          className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--muted-foreground)]"
        />
        <input
          type="text"
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          placeholder={t("kg.searchPlaceholder", "搜索概念，如 勾股定理、函数…")}
          className="w-full rounded-lg border border-[var(--border)]/55 bg-[var(--background)] py-2 pl-8 pr-8 text-[13px] text-[var(--foreground)] outline-none transition-colors placeholder:text-[var(--muted-foreground)]/60 focus:border-[var(--primary)]/45"
        />
        {inputValue ? (
          <button
            type="button"
            onClick={() => {
              setInputValue("");
              setResults([]);
            }}
            className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-0.5 text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
            aria-label={t("kg.clear", "清空")}
          >
            <X size={13} />
          </button>
        ) : null}
      </div>
    ),
    [inputValue, t],
  );

  return (
    <div className="flex h-full flex-col bg-[var(--card)]">
      {/* Search rail */}
      <div className="shrink-0 border-b border-[var(--border)]/40 px-3 py-2.5">
        {header}
        {available === false ? (
          <div className="mt-2 flex items-center gap-1.5 text-[11px] text-amber-600">
            <AlertCircle size={12} strokeWidth={1.9} />
            {t("kg.notAvailable", "课程知识图谱未加载（K12-KGraph 数据缺失）")}
          </div>
        ) : available === true ? (
          <div className="mt-1.5 px-0.5 text-[10.5px] text-[var(--muted-foreground)]">
            {t("kg.browseHint", "点击概念查看定义、前置与教材依据")}
          </div>
        ) : null}
      </div>

      {error ? (
        <div className="m-3 flex items-center gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-[12px] text-red-600">
          <AlertCircle size={13} strokeWidth={1.9} />
          {error}
        </div>
      ) : null}

      <div className="relative flex-1 overflow-y-auto px-3 py-3">
        {loadingConcept ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-[12px] text-[var(--muted-foreground)]">
            <Loader2 size={18} strokeWidth={1.7} className="animate-spin text-[var(--primary)]/80" />
            {t("kg.loading", "加载中…")}
          </div>
        ) : selected ? (
          <ConceptCard
            concept={selected}
            trail={trail}
            onBack={() => {
              setSelected(null);
              setTrail([]);
            }}
            onNavigate={(id, name) => openConcept(id, name)}
          />
        ) : showEmptyState ? (
          <EmptyState onPick={(s) => openByName(s)} />
        ) : (
          <ResultsList
            loading={loadingResults}
            results={results}
            query={inputValue}
            onPick={(c) => openConcept(c.id, c.name)}
          />
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Empty state (first open)                                           */
/* ------------------------------------------------------------------ */

function EmptyState({ onPick }: { onPick: (s: string) => void }) {
  const { t } = useTranslation();
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-[12px] text-[var(--muted-foreground)]">
        <Sparkles size={13} strokeWidth={1.9} className="text-[var(--primary)]" />
        {t("kg.tryThese", "从热门概念开始浏览")}
      </div>
      <div className="flex flex-wrap gap-2">
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => onPick(s)}
            className="rounded-full border border-[var(--border)]/55 bg-[var(--background)] px-3 py-1.5 text-[12px] text-[var(--foreground)] transition-colors hover:border-[var(--primary)]/45 hover:text-[var(--primary)]"
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Search results list                                                */
/* ------------------------------------------------------------------ */

function ResultsList({
  loading,
  results,
  query,
  onPick,
}: {
  loading: boolean;
  results: KgCandidate[];
  query: string;
  onPick: (c: KgCandidate) => void;
}) {
  const { t } = useTranslation();
  if (loading) {
    return (
      <div className="flex items-center gap-2 text-[12px] text-[var(--muted-foreground)]">
        <Loader2 size={15} strokeWidth={1.7} className="animate-spin text-[var(--primary)]/80" />
        {t("kg.searching", "搜索中…")}
      </div>
    );
  }
  if (results.length === 0) {
    return (
      <div className="px-1 text-[12px] text-[var(--muted-foreground)]">
        {t("kg.noResults", "未找到与「{{q}}」匹配的概念", { q: query })}
      </div>
    );
  }
  return (
    <ul className="space-y-1">
      {results.map((c) => (
        <li key={c.id}>
          <button
            type="button"
            onClick={() => onPick(c)}
            className="flex w-full items-center gap-2 rounded-lg border border-transparent px-2.5 py-2 text-left transition-colors hover:border-[var(--border)]/60 hover:bg-[var(--muted)]/30"
          >
            <Network size={14} strokeWidth={1.8} className="shrink-0 text-[var(--muted-foreground)]" />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[13px] font-medium text-[var(--foreground)]">
                {c.name}
              </span>
              <span className="block truncate text-[10.5px] text-[var(--muted-foreground)]">
                {c.id}
              </span>
            </span>
            <Badge cls={labelClass(c.label)}>{c.label}</Badge>
          </button>
        </li>
      ))}
    </ul>
  );
}

/* ------------------------------------------------------------------ */
/*  Concept card                                                       */
/* ------------------------------------------------------------------ */

function ConceptCard({
  concept,
  trail,
  onBack,
  onNavigate,
}: {
  concept: KgConcept;
  trail: KgLiteConcept[];
  onBack: () => void;
  onNavigate: (id: string, name: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="space-y-4">
      {/* Breadcrumb trail of opened concepts */}
      {trail.length > 0 ? (
        <div className="flex flex-wrap items-center gap-1 text-[11px] text-[var(--muted-foreground)]">
          {trail.map((node, i) => (
            <span key={`${node.id}-${i}`} className="inline-flex items-center gap-1">
              {i > 0 ? <ChevronRight size={11} strokeWidth={1.9} /> : null}
              <button
                type="button"
                onClick={() => onNavigate(node.id, node.name)}
                className={
                  i === trail.length - 1
                    ? "font-medium text-[var(--foreground)]"
                    : "hover:text-[var(--primary)]"
                }
              >
                {node.name}
              </button>
            </span>
          ))}
        </div>
      ) : null}

      <button
        type="button"
        onClick={onBack}
        className="inline-flex items-center gap-1 text-[11.5px] text-[var(--muted-foreground)] transition-colors hover:text-[var(--primary)]"
      >
        <ArrowLeft size={12} strokeWidth={1.9} />
        {t("kg.backToResults", "返回搜索结果")}
      </button>

      {/* Title */}
      <div className="flex items-center gap-2">
        <BookOpen size={18} strokeWidth={1.8} className="shrink-0 text-[var(--primary)]" />
        <h2 className="text-[17px] font-semibold text-[var(--foreground)]">{concept.name}</h2>
        <Badge cls={labelClass(concept.label)}>{concept.label}</Badge>
        {concept.importance ? (
          <Badge cls="bg-slate-500/10 text-slate-500">{concept.importance}</Badge>
        ) : null}
      </div>

      {/* Definition */}
      {concept.definition ? (
        <section className="rounded-xl border border-[var(--border)]/55 bg-[var(--background)] p-3">
          <SectionTitle icon={<BookOpen size={12} />}>{t("kg.definition", "定义")}</SectionTitle>
          <p className="text-[13px] leading-relaxed text-[var(--foreground)]">
            {concept.definition}
          </p>
        </section>
      ) : null}

      {/* Aliases */}
      {concept.aliases.length > 0 ? (
        <section className="flex flex-wrap items-center gap-1.5">
          <span className="text-[11px] font-medium text-[var(--muted-foreground)]">
            {t("kg.aliases", "别名")}：
          </span>
          {concept.aliases.map((a) => (
            <span
              key={a}
              className="rounded-full bg-[var(--muted)]/50 px-2 py-0.5 text-[11px] text-[var(--foreground)]"
            >
              {a}
            </span>
          ))}
        </section>
      ) : null}

      {/* Examples */}
      {concept.examples.length > 0 ? (
        <section>
          <SectionTitle icon={<Sparkles size={12} />}>{t("kg.examples", "示例")}</SectionTitle>
          <ul className="list-disc space-y-1 pl-5 text-[12.5px] text-[var(--foreground)]">
            {concept.examples.map((ex, i) => (
              <li key={i}>{ex}</li>
            ))}
          </ul>
        </section>
      ) : null}

      {/* Prerequisites (navigable) */}
      <section>
        <SectionTitle icon={<Layers size={12} />}>{t("kg.prerequisites", "前置基础")}</SectionTitle>
        {concept.prerequisites.length === 0 ? (
          <p className="text-[12px] text-[var(--muted-foreground)]">
            {t("kg.noPrereq", "暂无记录的前置概念")}
          </p>
        ) : (
          <ul className="space-y-1">
            {concept.prerequisites.map((p) => (
              <li key={p.id}>
                <button
                  type="button"
                  onClick={() => onNavigate(p.id, p.name)}
                  className="flex w-full items-center gap-2 rounded-lg border border-transparent px-2.5 py-1.5 text-left transition-colors hover:border-[var(--border)]/60 hover:bg-[var(--muted)]/30"
                >
                  <ChevronRight size={13} strokeWidth={1.9} className="shrink-0 text-[var(--muted-foreground)]" />
                  <span className="min-w-0 flex-1 truncate text-[12.5px] text-[var(--foreground)]">
                    {p.name}
                  </span>
                  <Badge cls={labelClass(p.label)}>{p.label}</Badge>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Learning path breadcrumb */}
      {concept.path.length > 0 ? (
        <section>
          <SectionTitle icon={<Network size={12} />}>{t("kg.path", "课程位置")}</SectionTitle>
          <div className="flex flex-wrap items-center gap-1 text-[12px]">
            {concept.path.map((p, i) => (
              <span key={`${p.id}-${i}`} className="inline-flex items-center gap-1">
                {i > 0 ? <ChevronRight size={11} strokeWidth={1.9} className="text-[var(--muted-foreground)]" /> : null}
                <button
                  type="button"
                  onClick={() => onNavigate(p.id, p.name)}
                  className="rounded px-1.5 py-0.5 text-[var(--foreground)] transition-colors hover:bg-[var(--muted)]/40 hover:text-[var(--primary)]"
                >
                  {p.name}
                </button>
                <span className="text-[10px] text-[var(--muted-foreground)]">{p.label}</span>
              </span>
            ))}
          </div>
        </section>
      ) : null}

      {/* Textbook evidence */}
      <section>
        <SectionTitle icon={<BookOpen size={12} />}>{t("kg.evidence", "教材依据")}</SectionTitle>
        {concept.evidence.evidences.length === 0 && concept.evidence.relations.length === 0 ? (
          <p className="text-[12px] text-[var(--muted-foreground)]">
            {t("kg.noEvidence", "暂无教材依据原文")}
          </p>
        ) : (
          <div className="space-y-2">
            {concept.evidence.evidences.map((e, i) => (
              <p
                key={`e-${i}`}
                className="rounded-lg border-l-2 border-[var(--primary)]/40 bg-[var(--muted)]/30 px-3 py-2 text-[12px] leading-relaxed text-[var(--foreground)]"
              >
                {e}
              </p>
            ))}
            {concept.evidence.relations.length > 0 ? (
              <div className="flex flex-wrap gap-1.5">
                {concept.evidence.relations.map((r, i) => (
                  <span
                    key={`r-${i}`}
                    className="rounded-full bg-[var(--muted)]/50 px-2 py-0.5 text-[11px] text-[var(--muted-foreground)]"
                  >
                    {r}
                  </span>
                ))}
              </div>
            ) : null}
          </div>
        )}
      </section>
    </div>
  );
}

function SectionTitle({
  icon,
  children,
}: {
  icon: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="mb-1.5 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.05em] text-[var(--muted-foreground)]">
      <span className="text-[var(--primary)]">{icon}</span>
      {children}
    </div>
  );
}
