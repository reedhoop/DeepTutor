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
  fetchKgConcept,
  type KnowledgePointItem,
  type TextbookBook,
  type TextbookChapter,
  type TextbookSection,
  type TextbookStage,
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
  const [selectedChapter, setSelectedChapter] = useState<TextbookChapter | null>(null);
  const [chapterPath, setChapterPath] = useState<string[]>([]);
  const [starting, setStarting] = useState(false);
  // Knowledge points for the active node (chapter or section), fetched from
  // /api/v1/kg/concept/{id}. Now the preview pane always shows real content
  // even when a chapter has no section-level granularity in the tree.
  const [kp, setKp] = useState<{
    loading: boolean;
    error: string | null;
    points: KnowledgePointItem[];
  }>({ loading: false, error: null, points: [] });
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
        // Expand the first subject + first book + first chapter so both
        // columns are populated on first paint (right pane shows the
        // first chapter's preview, tree shows its sections).
        const first = t.subjects[0];
        // Prefer the first stage group (小学 → 初中 → 高中) when the API
        // provides stage metadata; fall back to the flat first book.
        const firstBook = first
          ? (() => {
              const stageId = first.stages?.[0]?.book_ids?.[0];
              if (stageId) return first.books.find((b) => b.id === stageId) ?? first.books[0];
              return first.books[0];
            })()
          : undefined;
        const firstChapter = firstBook?.chapters[0];
        if (first && firstBook) {
          const exp = new Set([first.id, firstBook.id]);
          if (firstChapter) exp.add(firstChapter.id);
          setExpanded(exp);
          if (firstChapter) {
            setSelectedChapter(firstChapter);
            setChapterPath([first.name, firstBook.name, firstChapter.name]);
          }
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
    (
      section: TextbookSection,
      chapter: TextbookChapter,
      trail: string[],
    ) => {
      setSelected(section);
      setSelectionPath(trail);
      setSelectedChapter(null);
      setChapterPath([]);
      setStartError(null);
      // Make sure the parent chapter is expanded so the section is visible
      // in the tree, even if the user navigated to it via the preview pane.
      setExpanded((prev) => {
        if (prev.has(chapter.id)) return prev;
        const next = new Set(prev);
        next.add(chapter.id);
        return next;
      });
    },
    [],
  );

  const selectChapter = useCallback(
    (chapter: TextbookChapter, trail: string[]) => {
      setSelectedChapter(chapter);
      setChapterPath(trail);
      setSelected(null);
      setSelectionPath([]);
      setStartError(null);
      // Auto-expand the chapter so its sections are visible in the tree.
      setExpanded((prev) => {
        if (prev.has(chapter.id)) return prev;
        const next = new Set(prev);
        next.add(chapter.id);
        return next;
      });
    },
    [],
  );

  const handleStart = useCallback(async () => {
    // KGraph stores teachable KPs at two levels:
    //   • section-level for biology/chemistry/physics and 初中+ math — a
    //     chapter id returns 404 there, so fall back to the first section.
    //   • chapter-level for 小学 math (1–6年级) — those chapters have no
    //     sections and own KPs directly, so send the chapter id as-is.
    const targetId =
      selected?.id ??
      (selectedChapter
        ? selectedChapter.sections[0]?.id ?? selectedChapter.id
        : null);
    if (!targetId) return;
    setStarting(true);
    setStartError(null);
    try {
      await startKgraphPath(targetId);
      router.push(
        `/space/learning?path=${encodeURIComponent(`kgraph_${targetId}`)}`,
      );
    } catch (e) {
      setStartError((e as Error)?.message || tr("创建学习路径失败", "Failed to start the path"));
      setStarting(false);
    }
  }, [selected, selectedChapter, router, tr]);

  // Fetch the active node's knowledge points so the preview pane always shows
  // real content. KGraph stores KPs at section level — chapter nodes have no
  // direct KPs but expose a `path` of is_part_of sub-sections, which the UI
  // surfaces as a "pick a section" hint when the chapter is selected.
  const activeNodeId = selected?.id ?? selectedChapter?.id ?? null;
  useEffect(() => {
    if (!activeNodeId) {
      setKp({ loading: false, error: null, points: [] });
      return;
    }
    let cancelled = false;
    setKp((prev) => ({ ...prev, loading: true, error: null }));
    fetchKgConcept(activeNodeId)
      .then((c) => {
        if (!cancelled) setKp({ loading: false, error: null, points: c.knowledge_points });
      })
      .catch((e) => {
        if (!cancelled)
          setKp({
            loading: false,
            error: e?.message || tr("加载知识点失败", "Failed to load knowledge points"),
            points: [],
          });
      });
    return () => {
      cancelled = true;
    };
  }, [activeNodeId, tr]);

  const totalSections = useMemo(() => {
    if (!tree) return 0;
    let n = 0;
    for (const s of tree.subjects)
      for (const b of s.books) for (const c of b.chapters) n += c.sections.length;
    return n;
  }, [tree]);

  // The Start button is enabled when the active node has something to learn.
  // Section view already targets that section. Chapter view has two shapes:
  //   • chapter with sections  -> start from the first section
  //   • chapter without sections (小学 math) -> chapter owns KPs directly, so
  //     it's learnable once the KP fetch resolves with points.
  const canStart = selected
    ? true
    : selectedChapter
    ? selectedChapter.sections.length > 0 || kp.points.length > 0
    : false;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
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
      <div className="flex min-h-0 flex-1">
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
                selectedChapterId={selectedChapter?.id}
                onToggle={toggle}
                onSelectChapter={selectChapter}
                onSelectSection={selectSection}
                tr={tr}
              />
            ))
          )}
        </div>
      </aside>

      {/* Detail */}
      <section className="flex-1 overflow-y-auto">
        {!selected && !selectedChapter ? (
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
              {(selected ? selectionPath : chapterPath).map((p, i, arr) => (
                <span key={i} className="flex items-center gap-1">
                  {i > 0 && <ChevronRight className="w-3 h-3 opacity-50" />}
                  <span className={i === arr.length - 1 ? "text-[var(--foreground)]" : ""}>
                    {p}
                  </span>
                </span>
              ))}
            </nav>

            <h2 className="mt-3 text-lg font-semibold text-[var(--foreground)]">
              {selected?.name ?? selectedChapter?.name}
            </h2>

            {/* Chapter-only: when the chapter has sections, list them so the
                user can drill into a specific section. */}
            {!selected && selectedChapter && selectedChapter.sections.length > 0 && (
              <div className="mt-5">
                <p className="text-xs text-[var(--muted-foreground)]">
                  {tr(
                    `本章包含 ${selectedChapter.sections.length} 节，点选一节可生成学习路径。`,
                    `This chapter contains ${selectedChapter.sections.length} sections. Pick one to generate a mastery path.`,
                  )}
                </p>
                <div className="mt-3 divide-y divide-[var(--border)] overflow-hidden rounded-lg border border-[var(--border)]">
                  {selectedChapter.sections.map((s) => (
                    <button
                      key={s.id}
                      onClick={() =>
                        selectSection(s, selectedChapter, [...chapterPath, s.name])
                      }
                      className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-[var(--foreground)]/90 hover:bg-[var(--muted)]/40"
                    >
                      <ChevronRight className="w-3.5 h-3.5 shrink-0 opacity-50" />
                      <span className="truncate">{s.name}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Knowledge points for the active node (chapter or section).
                Chapters with no section data still own teachable KPs via their
                appears_in / is_part_of edges — this is the real content the
                preview pane should always show. */}
            <div className="mt-5">
              <p className="text-xs font-medium text-[var(--foreground)]/80">
                {selected
                  ? tr("本节知识点", "Knowledge points in this section")
                  : tr("本章知识点", "Knowledge points in this chapter")}
              </p>

              {kp.loading ? (
                <div className="mt-2 flex items-center gap-2 text-xs text-[var(--muted-foreground)]">
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  {tr("加载知识点…", "Loading knowledge points…")}
                </div>
              ) : kp.error ? (
                <p className="mt-2 flex items-center gap-1.5 text-xs text-red-500">
                  <AlertTriangle className="w-3.5 h-3.5" />
                  {kp.error}
                </p>
              ) : kp.points.length > 0 ? (
                <ul className="mt-2 space-y-1.5">
                  {kp.points.map((p) => (
                    <li
                      key={p.id}
                      className="flex items-center gap-2 rounded-md border border-[var(--border)] bg-[var(--card)]/50 px-3 py-2"
                    >
                      <span
                        className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium ${
                          p.label === "Skill"
                            ? "bg-blue-500/10 text-blue-600 dark:text-blue-400"
                            : "bg-[var(--primary)]/10 text-[var(--primary)]"
                        }`}
                      >
                        {p.label === "Skill"
                          ? tr("技能", "Skill")
                          : tr("概念", "Concept")}
                      </span>
                      <span className="truncate text-sm text-[var(--foreground)]/90">
                        {p.name}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-2 text-xs leading-relaxed text-[var(--muted-foreground)]">
                  {tr(
                    "该内容暂无可学习的知识点。",
                    "No teachable knowledge points in this content.",
                  )}
                </p>
              )}
            </div>

            <button
              onClick={handleStart}
              disabled={starting || !canStart}
              className="mt-5 flex items-center gap-2 rounded-lg bg-[var(--primary)] px-4 py-2.5 text-sm font-medium text-[var(--primary-foreground)] shadow-md shadow-[var(--primary)]/15 transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60 cursor-pointer"
            >
              {starting ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <GraduationCap className="w-4 h-4" />
              )}
              {starting
                ? tr("正在生成路径…", "Building path…")
                : selected
                ? tr("开始学习这一节", "Start learning this section")
                : tr("开始学习本章", "Start learning this chapter")}
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
              {selected
                ? tr(
                    "→ 本节涵盖知识点、前置链和练习题，请进入学习工作区查看。",
                    "→ The knowledge points, prerequisites and exercises live in the learning workspace.",
                  )
                : selectedChapter && selectedChapter.sections.length > 0
                ? tr(
                    "→ 选一节进入，或从本章第一节开始学习。",
                    "→ Pick a section to dive in, or start from the first section of this chapter.",
                  )
                : tr(
                    "→ 本章知识点可直接开始学习。",
                    "→ This chapter's knowledge points can be started directly.",
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
  selectedChapterId,
  onToggle,
  onSelectChapter,
  onSelectSection,
  tr,
}: {
  subject: TextbookSubject;
  expanded: Set<string>;
  selectedId: string | undefined;
  selectedChapterId: string | undefined;
  onToggle: (id: string) => void;
  onSelectChapter: (c: TextbookChapter, trail: string[]) => void;
  onSelectSection: (s: TextbookSection, c: TextbookChapter, trail: string[]) => void;
  tr: (cn: string, en: string) => string;
}) {
  const open = expanded.has(subject.id);

  // Stage (学段) grouping: subject → 小学/初中/高中 → book. Falls back to
  // the flat book list when the API response has no stage metadata.
  const stageGroups = useMemo(() => {
    if (!subject.stages?.length) return null;
    return subject.stages
      .map((stage) => {
        const books = stage.book_ids
          .map((id) => subject.books.find((b) => b.id === id))
          .filter((b): b is TextbookBook => Boolean(b));
        return books.length ? { stage, books } : null;
      })
      .filter((g): g is { stage: TextbookStage; books: TextbookBook[] } => Boolean(g));
  }, [subject]);

  const renderBook = (book: TextbookBook) => (
    <BookNode
      key={book.id}
      subjectName={subject.name}
      book={book}
      expanded={expanded}
      selectedId={selectedId}
      selectedChapterId={selectedChapterId}
      onToggle={onToggle}
      onSelectChapter={onSelectChapter}
      onSelectSection={onSelectSection}
      tr={tr}
    />
  );

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
        (stageGroups
          ? stageGroups.map(({ stage, books }) => (
              <div key={stage.id} className="ml-2 mt-1">
                <div className="flex items-center gap-1.5 rounded px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-[var(--muted-foreground)]/80">
                  {stageLabel(stage, tr)}
                  <span className="font-normal normal-case text-[10px] text-[var(--muted-foreground)]/60">
                    {books.length} {tr("册", "books")}
                  </span>
                </div>
                {books.map(renderBook)}
              </div>
            ))
          : subject.books.map(renderBook))}
    </div>
  );
}, (prev, next) =>
  prev.subject === next.subject &&
  prev.expanded === next.expanded &&
  prev.selectedId === next.selectedId &&
  prev.selectedChapterId === next.selectedChapterId &&
  prev.onToggle === next.onToggle &&
  prev.onSelectChapter === next.onSelectChapter &&
  prev.onSelectSection === next.onSelectSection &&
  prev.tr === next.tr
);

/** i18n label for a stage group; falls back to the server-provided name. */
function stageLabel(stage: TextbookStage, tr: (cn: string, en: string) => string): string {
  const map: Record<string, [string, string]> = {
    primary: ["小学", "Primary"],
    junior: ["初中", "Junior High"],
    senior: ["高中", "Senior High"],
  };
  const pair = map[stage.id];
  return pair ? tr(pair[0], pair[1]) : stage.name || stage.id;
}

const BookNode = memo(function BookNode({
  subjectName,
  book,
  expanded,
  selectedId,
  selectedChapterId,
  onToggle,
  onSelectChapter,
  onSelectSection,
  tr,
}: {
  subjectName: string;
  book: TextbookBook;
  expanded: Set<string>;
  selectedId: string | undefined;
  selectedChapterId: string | undefined;
  onToggle: (id: string) => void;
  onSelectChapter: (c: TextbookChapter, trail: string[]) => void;
  onSelectSection: (s: TextbookSection, c: TextbookChapter, trail: string[]) => void;
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
            subjectName={subjectName}
            bookName={book.name}
            chapter={chapter}
            expanded={expanded}
            selectedId={selectedId}
            selectedChapterId={selectedChapterId}
            onToggle={onToggle}
            onSelectChapter={onSelectChapter}
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
  prev.selectedChapterId === next.selectedChapterId &&
  prev.onToggle === next.onToggle &&
  prev.onSelectChapter === next.onSelectChapter &&
  prev.onSelectSection === next.onSelectSection &&
  prev.tr === next.tr
);

const ChapterNode = memo(function ChapterNode({
  subjectName,
  bookName,
  chapter,
  expanded,
  selectedId,
  selectedChapterId,
  onToggle,
  onSelectChapter,
  onSelectSection,
  tr,
}: {
  subjectName: string;
  bookName: string;
  chapter: TextbookChapter;
  expanded: Set<string>;
  selectedId: string | undefined;
  selectedChapterId: string | undefined;
  onToggle: (id: string) => void;
  onSelectChapter: (c: TextbookChapter, trail: string[]) => void;
  onSelectSection: (s: TextbookSection, c: TextbookChapter, trail: string[]) => void;
  tr: (cn: string, en: string) => string;
}) {
  const open = expanded.has(chapter.id);
  const isSelectedChapter = chapter.id === selectedChapterId;
  return (
    <div className="ml-3">
      <div
        className={`flex items-center rounded-md transition-colors ${
          isSelectedChapter
            ? "bg-[var(--primary)]/15"
            : "hover:bg-[var(--muted)]/40"
        }`}
      >
        <button
          onClick={() => onToggle(chapter.id)}
          aria-label={open ? tr("折叠", "Collapse") : tr("展开", "Expand")}
          className="px-1.5 py-1.5 text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
        >
          {open ? <ChevronDown className="w-3 h-3 shrink-0" /> : <ChevronRight className="w-3 h-3 shrink-0" />}
        </button>
        <button
          onClick={() => onSelectChapter(chapter, [subjectName, bookName, chapter.name])}
          className={`flex-1 truncate py-1.5 pr-2 text-left text-xs ${
            isSelectedChapter
              ? "font-medium text-[var(--foreground)]"
              : "text-[var(--foreground)]/90"
          }`}
        >
          {chapter.name}
        </button>
      </div>
      {open && (
        <div className="ml-3 space-y-0.5">
          {chapter.sections.map((section) => {
            const active = section.id === selectedId;
            return (
              <button
                key={section.id}
                onClick={() =>
                  onSelectSection(section, chapter, [bookName, chapter.name, section.name])
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
  prev.selectedChapterId === next.selectedChapterId &&
  prev.onToggle === next.onToggle &&
  prev.onSelectChapter === next.onSelectChapter &&
  prev.onSelectSection === next.onSelectSection &&
  prev.tr === next.tr
);
