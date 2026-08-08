"use client";

import { useCallback, useEffect, useMemo, useState, memo } from "react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import {
  BookText,
  ChevronDown,
  ChevronRight,
  GraduationCap,
  Loader2,
  AlertTriangle,
  List,
  Network,
} from "lucide-react";

import {
  fetchTextbookTree,
  type TextbookBook,
  type TextbookChapter,
  type TextbookSection,
  type TextbookSubject,
  type TextbookTree,
} from "@/lib/textbook-api";
import { startKgraphPath } from "@/lib/learning-api";
import TextbookMindmap from "@/components/textbook/TextbookMindmap";

/**
 * Textbook Navigator.
 *
 * Renders the K12 curriculum tree (subject → book/年级 → chapter → section) from
 * ``/api/v1/kgraph/textbook-tree``. Clicking a *section* (the leaf) and pressing
 * "开始学习" builds a mastery path from that section's knowledge sub-tree via
 * ``POST /api/v1/learning/progress/{book_id}/from-kgraph`` and jumps to the
 * learning dashboard with the new path preselected.
 */
const toggleCls = (active: boolean) =>
  `flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
    active
      ? "bg-[var(--primary)] text-[var(--primary-foreground)]"
      : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
  }`;

const chipCls = (active: boolean) =>
  `rounded-full border px-2.5 py-1 text-xs transition-colors ${
    active
      ? "border-[var(--primary)] bg-[var(--primary)]/10 text-[var(--foreground)]"
      : "border-[var(--border)] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
  }`;

export default function TextbookNavigatorPage() {
  const { i18n } = useTranslation();
  const zh = i18n.language?.toLowerCase().startsWith("zh");
  const tr = useCallback((cn: string, en: string) => (zh ? cn : en), [zh]);
  const router = useRouter();

  const [tree, setTree] = useState<TextbookTree | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState<TextbookSection | null>(null);
  const [selectionPath, setSelectionPath] = useState<string[]>([]);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);

  // ER-2: textbook mind-map view (subject → book → chapter → section)
  const [view, setView] = useState<"list" | "mindmap">("list");
  const [mindmapScope, setMindmapScope] = useState<"all" | string>("all");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchTextbookTree()
      .then((t) => {
        if (cancelled) return;
        setTree(t);
        // Expand the first subject + first book so the tree is never empty.
        const first = t.subjects[0];
        if (first && first.books[0]) {
          setExpanded(new Set([first.id, first.books[0].id]));
        }
      })
      .catch((e) => {
        if (!cancelled) setLoadError(e?.message || "加载课本树失败");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const toggle = useCallback((id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const selectSection = useCallback(
    (section: TextbookSection, trail: string[]) => {
      setSelected(section);
      setSelectionPath(trail);
      setStartError(null);
    },
    [],
  );

  const handleStart = useCallback(async () => {
    if (!selected) return;
    setStarting(true);
    setStartError(null);
    try {
      await startKgraphPath(selected.id);
      router.push(
        `/space/learning?path=${encodeURIComponent(`kgraph_${selected.id}`)}`,
      );
    } catch (e) {
      setStartError((e as Error)?.message || tr("创建学习路径失败", "Failed to start the path"));
      setStarting(false);
    }
  }, [selected, router, tr]);

  const totalSections = useMemo(() => {
    if (!tree) return 0;
    let n = 0;
    for (const s of tree.subjects)
      for (const b of s.books) for (const c of b.chapters) n += c.sections.length;
    return n;
  }, [tree]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* Toolbar: list / mindmap toggle + subject drill-down */}
      <div className="flex flex-wrap items-center gap-3 border-b border-[var(--border)] px-4 py-2">
        <div className="flex items-center gap-1 rounded-lg bg-[var(--muted)]/50 p-0.5">
          <button
            onClick={() => setView("list")}
            className={toggleCls(view === "list")}
          >
            <List className="w-3.5 h-3.5" />
            {tr("列表", "List")}
          </button>
          <button
            onClick={() => setView("mindmap")}
            className={toggleCls(view === "mindmap")}
          >
            <Network className="w-3.5 h-3.5" />
            {tr("脑图", "Mindmap")}
          </button>
        </div>

        {view === "mindmap" && (
          <div className="flex flex-wrap items-center gap-1.5">
            <button
              onClick={() => setMindmapScope("all")}
              className={chipCls(mindmapScope === "all")}
            >
              {tr("全部教材", "All books")}
            </button>
            {tree?.subjects.map((s) => (
              <button
                key={s.id}
                onClick={() => setMindmapScope(s.id)}
                className={chipCls(mindmapScope === s.id)}
              >
                {s.name}
              </button>
            ))}
          </div>
        )}

        <div className="ml-auto flex items-center gap-1.5 text-xs text-[var(--muted-foreground)]">
          <BookText className="w-3.5 h-3.5" />
          <span>
            {totalSections} {tr("节", "sections")}
          </span>
        </div>
      </div>

      {view === "mindmap" ? (
        <div className="flex-1 min-h-0 p-3">
          {!tree ? (
            <div className="flex h-full items-center justify-center text-[var(--muted-foreground)]">
              {loading ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                loadError ?? tr("加载中…", "Loading…")
              )}
            </div>
          ) : (
            <TextbookMindmap tree={tree} scope={mindmapScope} />
          )}
        </div>
      ) : (
      <div className="flex h-full min-h-0">
      {/* Tree */}
      <aside className="flex w-80 shrink-0 flex-col border-r border-[var(--border)] bg-[var(--card)]/40">
        <header className="border-b border-[var(--border)] px-4 py-3">
          <div className="flex items-center gap-2 text-[var(--foreground)]">
            <BookText className="w-4 h-4" />
            <h1 className="text-sm font-semibold">
              {tr("课本导航", "Textbook Navigator")}
            </h1>
          </div>
          <p className="mt-1 text-xs text-[var(--muted-foreground)]">
            {tr(
              "按学科 → 年级 → 章 → 节，点选一节即可生成学习路径",
              "Pick a section to generate a mastery path",
            )}
            {tree ? ` · ${totalSections} ${tr("节", "sections")}` : ""}
          </p>
        </header>

        <div className="flex-1 overflow-y-auto px-2 py-2">
          {loading ? (
            <div className="flex items-center justify-center py-10 text-[var(--muted-foreground)]">
              <Loader2 className="w-4 h-4 animate-spin" />
            </div>
          ) : loadError ? (
            <div className="flex flex-col items-center gap-2 px-3 py-8 text-center text-[var(--muted-foreground)]">
              <AlertTriangle className="w-5 h-5 text-yellow-500" />
              <p className="text-xs leading-relaxed">{loadError}</p>
            </div>
          ) : (
            tree?.subjects.map((subject) => (
              <SubjectNode
                key={subject.id}
                subject={subject}
                expanded={expanded}
                selectedId={selected?.id}
                onToggle={toggle}
                onSelectSection={selectSection}
                tr={tr}
              />
            ))
          )}
        </div>
      </aside>

      {/* Detail */}
      <section className="flex-1 overflow-y-auto">
        {!selected ? (
          <div className="flex h-full flex-col items-center justify-center px-6 text-center text-[var(--muted-foreground)]">
            <BookText className="mb-3 w-10 h-10 opacity-40" />
            <p className="max-w-sm text-sm leading-relaxed">
              {tr(
                "从左侧选择一节课本内容。系统会按知识链的前置依赖，自动排好学习顺序，生成一条可增量测评、进度自动推进的专精之路。",
                "Pick a section from the left. The system orders it by the knowledge-chain prerequisites into a mastery path you can practise and track.",
              )}
            </p>
          </div>
        ) : (
          <div className="mx-auto max-w-2xl px-6 py-6">
            <nav className="flex flex-wrap items-center gap-1 text-xs text-[var(--muted-foreground)]">
              {selectionPath.map((p, i) => (
                <span key={i} className="flex items-center gap-1">
                  {i > 0 && <ChevronRight className="w-3 h-3 opacity-50" />}
                  <span className={i === selectionPath.length - 1 ? "text-[var(--foreground)]" : ""}>
                    {p}
                  </span>
                </span>
              ))}
            </nav>

            <h2 className="mt-3 text-lg font-semibold text-[var(--foreground)]">
              {selected.name}
            </h2>

            <button
              onClick={handleStart}
              disabled={starting}
              className="mt-5 flex items-center gap-2 rounded-lg bg-[var(--primary)] px-4 py-2.5 text-sm font-medium text-[var(--primary-foreground)] shadow-md shadow-[var(--primary)]/15 transition-opacity hover:opacity-90 disabled:opacity-60 cursor-pointer"
            >
              {starting ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <GraduationCap className="w-4 h-4" />
              )}
              {starting
                ? tr("正在生成路径…", "Building path…")
                : tr("开始学习这一节", "Start learning this section")}
            </button>

            {startError && (
              <p className="mt-3 flex items-center gap-1.5 text-xs text-red-500">
                <AlertTriangle className="w-3.5 h-3.5" />
                {startError}
              </p>
            )}

            <p className="mt-4 text-xs leading-relaxed text-[var(--muted-foreground)]">
              {tr(
                "路径会先测你已经会的，再带你学还没掌握的；完成一小步后自动推进到下一个知识点（含跨年级前置）。",
                "The path probes what you already know, then coaches the rest — advancing automatically as each step clears (including cross-grade prerequisites).",
              )}
            </p>
            <p className="mt-2 text-xs leading-relaxed text-[var(--muted-foreground)]/80">
              {tr(
                "→ 本节涵盖知识点、前置链和练习题，请进入学习工作区查看。",
                "→ The knowledge points, prerequisites and exercises live in the learning workspace.",
              )}
            </p>
          </div>
        )}
      </section>
      </div>
      )}
    </div>
  );
}

const SubjectNode = memo(function SubjectNode({
  subject,
  expanded,
  selectedId,
  onToggle,
  onSelectSection,
  tr,
}: {
  subject: TextbookSubject;
  expanded: Set<string>;
  selectedId: string | undefined;
  onToggle: (id: string) => void;
  onSelectSection: (s: TextbookSection, trail: string[]) => void;
  tr: (cn: string, en: string) => string;
}) {
  const open = expanded.has(subject.id);
  return (
    <div className="mb-1">
      <button
        onClick={() => onToggle(subject.id)}
        className="flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-left text-sm font-medium text-[var(--foreground)] hover:bg-[var(--muted)]/40"
      >
        {open ? <ChevronDown className="w-3.5 h-3.5 shrink-0" /> : <ChevronRight className="w-3.5 h-3.5 shrink-0" />}
        <span>{subject.name}</span>
        <span className="ml-auto text-[10px] uppercase tracking-wide text-[var(--muted-foreground)]">
          {subject.books.length}
        </span>
      </button>
      {open &&
        subject.books.map((book) => (
          <BookNode
            key={book.id}
            book={book}
            expanded={expanded}
            selectedId={selectedId}
            onToggle={onToggle}
            onSelectSection={onSelectSection}
            tr={tr}
          />
        ))}
    </div>
  );
}, (prev, next) =>
  prev.subject === next.subject &&
  prev.expanded === next.expanded &&
  prev.selectedId === next.selectedId &&
  prev.onToggle === next.onToggle &&
  prev.onSelectSection === next.onSelectSection &&
  prev.tr === next.tr
);

const BookNode = memo(function BookNode({
  book,
  expanded,
  selectedId,
  onToggle,
  onSelectSection,
  tr,
}: {
  book: TextbookBook;
  expanded: Set<string>;
  selectedId: string | undefined;
  onToggle: (id: string) => void;
  onSelectSection: (s: TextbookSection, trail: string[]) => void;
  tr: (cn: string, en: string) => string;
}) {
  const open = expanded.has(book.id);
  return (
    <div className="ml-3">
      <button
        onClick={() => onToggle(book.id)}
        className="flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-left text-[13px] text-[var(--foreground)] hover:bg-[var(--muted)]/40"
      >
        {open ? <ChevronDown className="w-3 h-3 shrink-0" /> : <ChevronRight className="w-3 h-3 shrink-0" />}
        <span className="truncate">{book.name}</span>
        {book.edition && (
          <span className="ml-auto shrink-0 rounded-full bg-[var(--muted)] px-1.5 py-0.5 text-[9px] text-[var(--muted-foreground)]">
            {book.edition}
          </span>
        )}
      </button>
      {open &&
        book.chapters.map((chapter) => (
          <ChapterNode
            key={chapter.id}
            bookName={book.name}
            chapter={chapter}
            expanded={expanded}
            selectedId={selectedId}
            onToggle={onToggle}
            onSelectSection={onSelectSection}
            tr={tr}
          />
        ))}
    </div>
  );
}, (prev, next) =>
  prev.book === next.book &&
  prev.expanded === next.expanded &&
  prev.selectedId === next.selectedId &&
  prev.onToggle === next.onToggle &&
  prev.onSelectSection === next.onSelectSection &&
  prev.tr === next.tr
);

const ChapterNode = memo(function ChapterNode({
  bookName,
  chapter,
  expanded,
  selectedId,
  onToggle,
  onSelectSection,
  tr,
}: {
  bookName: string;
  chapter: TextbookChapter;
  expanded: Set<string>;
  selectedId: string | undefined;
  onToggle: (id: string) => void;
  onSelectSection: (s: TextbookSection, trail: string[]) => void;
  tr: (cn: string, en: string) => string;
}) {
  const open = expanded.has(chapter.id);
  return (
    <div className="ml-3">
      <button
        onClick={() => onToggle(chapter.id)}
        className="flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-left text-xs text-[var(--foreground)]/90 hover:bg-[var(--muted)]/40"
      >
        {open ? <ChevronDown className="w-3 h-3 shrink-0" /> : <ChevronRight className="w-3 h-3 shrink-0" />}
        <span className="truncate">{chapter.name}</span>
      </button>
      {open && (
        <div className="ml-3 space-y-0.5">
          {chapter.sections.map((section) => {
            const active = section.id === selectedId;
            return (
              <button
                key={section.id}
                onClick={() =>
                  onSelectSection(section, [bookName, chapter.name, section.name])
                }
                className={`flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-left text-xs ${
                  active
                    ? "bg-[var(--primary)]/15 font-medium text-[var(--foreground)]"
                    : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]/40 hover:text-[var(--foreground)]"
                }`}
              >
                <span className="truncate">{section.name}</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}, (prev, next) =>
  prev.chapter === next.chapter &&
  prev.expanded === next.expanded &&
  prev.selectedId === next.selectedId &&
  prev.onToggle === next.onToggle &&
  prev.onSelectSection === next.onSelectSection &&
  prev.tr === next.tr
);
