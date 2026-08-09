import { apiUrl, apiFetch } from "./api";

export interface ModuleInit {
  id: string;
  name: string;
  order: number;
  pass_threshold?: number;
  knowledge_points: {
    id: string;
    name: string;
    type: string;
    module_id: string;
  }[];
}

export interface LearningKnowledgePoint {
  id: string;
  name: string;
  type: string;
}

export interface LearningModule {
  id: string;
  name: string;
  order: number;
  pass_threshold: number;
  knowledge_points: LearningKnowledgePoint[];
}

export interface ProgressDetail {
  book_id: string;
  modules: LearningModule[];
  mastery_levels: Record<string, number>;
  current_module_id?: string;
  current_stage?: string;
  diagnostic?: unknown;
}

export async function fetchProgress(bookId: string): Promise<ProgressDetail> {
  const res = await apiFetch(apiUrl(`/api/mastery-paths/progress/${bookId}`));
  if (!res.ok) throw new Error(`Failed to fetch progress: ${res.status}`);
  return res.json() as Promise<ProgressDetail>;
}

export async function initModules(bookId: string, modules: ModuleInit[]) {
  const res = await apiFetch(
    apiUrl(`/api/mastery-paths/progress/${bookId}/init-modules`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ modules }),
    },
  );
  if (!res.ok) throw new Error(`Failed to init modules: ${res.status}`);
  return res.json();
}

// ── Mastery map (the dashboard view) ──────────────────────────────────────
// Mirrors deeptutor/learning/policy.py map_summary + next_objective.

export type ObjectiveStatus = "new" | "learning" | "mastered";

export interface MapKnowledgePoint {
  id: string;
  name: string;
  type: string;
  status: ObjectiveStatus;
  mastery: number;
  mastery_source: "system" | "learner" | "";
  override_note: string;
}

export interface MapModule {
  id: string;
  name: string;
  order: number;
  mastered: number;
  total: number;
  knowledge_points: MapKnowledgePoint[];
}

export interface MasteryMap {
  /** What to call this path — see policy.path_display_name. */
  name: string;
  counts: { mastered: number; learning: number; new: number; total: number };
  due_reviews: number;
  complete: boolean;
  modules: MapModule[];
}

export interface NextStep {
  action: string;
  knowledge_point_id: string;
  knowledge_point_name: string;
  knowledge_point_type: string;
  status: string;
  gate: string;
  mastery: number;
  threshold: number;
  reason: string;
  /** The outstanding question's text, when `action` is `answer_pending`. */
  pending_prompt: string;
  /** Session that owns an outstanding question; empty for non-pending steps. */
  session_id: string;
}

export interface MasteryMapResult {
  book_id: string;
  name: string;
  path_revision: number;
  next: NextStep;
  map: MasteryMap;
}

export async function fetchMasteryMap(
  pathId: string,
  init?: RequestInit,
): Promise<MasteryMapResult> {
  const res = await apiFetch(
    apiUrl(`/api/mastery-paths/progress/${encodeURIComponent(pathId)}/map`),
    init,
  );
  if (!res.ok) throw new Error(`Failed to fetch mastery map: ${res.status}`);
  return res.json() as Promise<MasteryMapResult>;
}

/** Rename a path. An empty name restores the derived display name. */
export async function renameProgress(pathId: string, name: string) {
  const res = await apiFetch(
    apiUrl(`/api/mastery-paths/progress/${encodeURIComponent(pathId)}`),
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    },
  );
  if (!res.ok) throw new Error(`Failed to rename path: ${res.status}`);
  return res.json() as Promise<{ status: string; name: string }>;
}

// ── Activity feed ─────────────────────────────────────────────────────────
// Mirrors deeptutor/learning/models.py MasteryEvent. Every committed change to
// a path emits one, numbered by the path's revision — which is what lets the
// dashboard follow along with a tutoring session running in another tab.

export interface MasteryEvent {
  id: number;
  revision: number;
  event_type: string;
  payload: Record<string, unknown>;
  session_id: string;
  turn_id: string;
  created_at: number;
}

export async function fetchProgressEvents(
  pathId: string,
  afterRevision = 0,
  init?: RequestInit,
): Promise<MasteryEvent[]> {
  const res = await apiFetch(
    apiUrl(
      `/api/mastery-paths/progress/${encodeURIComponent(pathId)}/events?after_revision=${afterRevision}`,
    ),
    init,
  );
  if (!res.ok) throw new Error(`Failed to fetch path events: ${res.status}`);
  return (await res.json()).events as MasteryEvent[];
}

// ── One objective's evidence trail ────────────────────────────────────────
// Mirrors deeptutor/learning/policy.py objective_report.

export interface ObjectiveAttempt {
  question_id: string;
  prompt: string;
  answer: string;
  is_correct: boolean;
  error_type: string;
  at: number;
}

export interface ObjectiveReview {
  due_at: number | null;
  interval_index: number;
  consecutive_correct: number;
  consecutive_wrong: number;
}

export interface ObjectiveErrorRecord {
  id: string;
  error_type: string;
  status: string;
  self_attribution: string;
  retries: number;
  created_at: number;
}

export interface ObjectiveReport {
  id: string;
  name: string;
  type: string;
  module_name: string;
  status: ObjectiveStatus;
  gate: "quantitative" | "qualitative";
  mastered: boolean;
  assessed_mastered: boolean;
  mastery_source: "system" | "learner" | "";
  override_note: string;
  mastery: number;
  threshold: number;
  attempts: ObjectiveAttempt[];
  correct_count: number;
  explanation: string;
  review: ObjectiveReview | null;
  errors: ObjectiveErrorRecord[];
}

export async function fetchObjectiveReport(
  pathId: string,
  objectiveId: string,
  init?: RequestInit,
): Promise<ObjectiveReport> {
  const res = await apiFetch(
    apiUrl(
      `/api/mastery-paths/progress/${encodeURIComponent(pathId)}/objectives/${encodeURIComponent(objectiveId)}`,
    ),
    init,
  );
  if (!res.ok) throw new Error(`Failed to fetch objective: ${res.status}`);
  return (await res.json()).objective as ObjectiveReport;
}

export interface ProgressSummary {
  book_id: string;
  name: string;
  modules_count: number;
  kp_count: number;
  current_stage: string;
  avg_mastery_pct: number;
  updated_at: number;
}

export interface ProgressListResult {
  summaries: ProgressSummary[];
  errors: { book_id: string; error: string }[];
}

export async function fetchAllProgress(): Promise<ProgressListResult> {
  const res = await apiFetch(apiUrl("/api/mastery-paths/progress"));
  if (!res.ok) throw new Error(`Failed to fetch all progress: ${res.status}`);
  return res.json();
}

// ── Study archive (ER-13) ─────────────────────────────────────────────────
// Aggregated, read-only growth view across all mastery paths. Mirrors
// deeptutor/_local/study_archive_router.study_archive.

export interface StudyBookStat {
  book_id: string;
  name: string;
  updated_at: number;
  avg_mastery_pct: number;
  mastered_count: number;
  kp_count: number;
  quiz_count: number;
  error_count: number;
}

export interface StudyWeakPoint {
  knowledge_point_id: string;
  name: string;
  module_id: string;
  mastery: number;
  error_count: number;
  score: number;
  reason: string;
}

export interface StudyArchive {
  books: StudyBookStat[];
  timeline: StudyBookStat[];
  weak_points: StudyWeakPoint[];
  overall: {
    path_count: number;
    kp_count: number;
    mastered_count: number;
    avg_mastery_pct: number;
    quiz_count: number;
    error_count: number;
  };
}

export async function fetchStudyArchive(): Promise<StudyArchive> {
  const res = await apiFetch(apiUrl("/api/v1/study/archive"));
  if (!res.ok) throw new Error(`Failed to fetch study archive: ${res.status}`);
  return res.json();
}

// ── Motivation (ER-14) ─────────────────────────────────────────────────────
// Lightweight gamification — streak, badges, points — derived read-only from
// practice/mastery data. Mirrors deeptutor/_local/motivation_overlay.motivation.
// Badge display names/descriptions/icons live in the frontend catalogue
// (web/app/(utility)/space/motivation/page.tsx) keyed by `id`; the backend only
// returns logical state so the strings stay properly localisable.

export interface MotivationStreak {
  current: number;
  longest: number;
  active_days: number;
  last_active: string | null;
  today_active: boolean;
  recent: { date: string; active: boolean }[];
}

export interface MotivationPoints {
  total: number;
  breakdown: {
    quiz_attempts: number;
    correct: number;
    mastered: number;
    active_days: number;
    badges: number;
  };
}

export interface MotivationBadge {
  id: string;
  earned: boolean;
  /** 0..1 progress toward this badge (1 when earned). */
  progress: number;
  /** Epoch seconds when first earned, if known. */
  earned_at?: number;
}

export interface Motivation {
  has_data: boolean;
  streak: MotivationStreak;
  points: MotivationPoints;
  badges: MotivationBadge[];
}

export async function fetchMotivation(): Promise<Motivation> {
  const res = await apiFetch(apiUrl("/api/v1/study/motivation"));
  if (!res.ok) throw new Error(`Failed to fetch motivation: ${res.status}`);
  return res.json();
}

export async function deleteProgress(bookId: string) {
  const res = await apiFetch(
    apiUrl(`/api/mastery-paths/progress/${encodeURIComponent(bookId)}`),
    { method: "DELETE" },
  );
  if (!res.ok) throw new Error(`Failed to delete progress: ${res.status}`);
  return res.json();
}

export async function redoProgress(bookId: string) {
  const res = await apiFetch(
    apiUrl(`/api/mastery-paths/progress/${encodeURIComponent(bookId)}/redo`),
    { method: "POST" },
  );
  if (!res.ok) throw new Error(`Failed to redo progress: ${res.status}`);
  return res.json();
}

/** Drop an outstanding question, keeping every mastery level already earned. */
export async function skipPendingQuestion(bookId: string) {
  const res = await apiFetch(
    apiUrl(
      `/api/mastery-paths/progress/${encodeURIComponent(bookId)}/skip-question`,
    ),
    { method: "POST" },
  );
  if (!res.ok) throw new Error(`Failed to skip question: ${res.status}`);
  return res.json();
}

export async function importFromBook(
  bookId: string,
  chapters: { title: string; knowledge_points: string[] }[],
) {
  const res = await apiFetch(
    apiUrl(
      `/api/mastery-paths/progress/${encodeURIComponent(bookId)}/import-from-book`,
    ),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chapters }),
    },
  );
  if (!res.ok) throw new Error(`Failed to import from book: ${res.status}`);
  return res.json();
}

export async function generateModulesFromNotebook(
  bookId: string,
  notebookId: string,
  records: { id: string; type: string; title: string; output: string }[],
): Promise<{ modules: ModuleInit[] }> {
  const res = await apiFetch(
    apiUrl(
      `/api/mastery-paths/progress/${encodeURIComponent(bookId)}/generate-from-notebook`,
    ),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ notebook_id: notebookId, records }),
    },
  );
  if (!res.ok)
    throw new Error(`Failed to generate modules from notebook: ${res.status}`);
  return res.json();
}

// ── Mastery Path V2 product surface ──────────────────────────────────────

export type TopicSourceKind =
  | "goal"
  | "book"
  | "notebook"
  | "knowledge_base"
  | "file"
  | "chat";

export interface TopicSource {
  id: string;
  kind: TopicSourceKind;
  source_id: string;
  label: string;
  excerpt: string;
  position: number;
  available: boolean;
  metadata: Record<string, unknown>;
  created_at: number;
}

export interface TopicSourceInput {
  id?: string;
  kind: TopicSourceKind;
  source_id?: string;
  label: string;
  excerpt?: string;
  available?: boolean;
  metadata?: Record<string, unknown>;
}

export interface TopicMetadata {
  path_id: string;
  goal: string;
  description: string;
  emoji: string;
  map_seed: number;
  status: "active" | "archived";
  created_at: number;
  updated_at: number;
}

export interface TopicReview {
  id: string;
  knowledge_point_id: string;
  knowledge_point_name: string;
  knowledge_type: string;
  due_at: number;
  priority: number;
  due: boolean;
}

export interface MasteryTopic {
  path_id: string;
  name: string;
  metadata: TopicMetadata;
  sources: TopicSource[];
  path_revision: number;
  next: NextStep;
  map: MasteryMap;
  reviews: TopicReview[];
  session_count: number;
  updated_at: number;
}

/** One selected document the generated outline did not account for. */
export interface TopicCoverageGap {
  /** The source it came from — a knowledge base name, or a file's own label. */
  label: string;
  document: string;
}

/**
 * How much of the learner's selected material the outline accounts for.
 *
 * `reported: false` means the model named no materials at all, so nothing can
 * be concluded — showing every document as missed would send the learner
 * regenerating an outline that may already cover them.
 */
export interface TopicCoverage {
  documents: number;
  covered: number;
  missing: TopicCoverageGap[];
  reported: boolean;
}

export interface TopicDraft {
  description: string;
  modules: ModuleInit[];
  /** Server-hydrated source states (for example KB retrieval availability). */
  sources?: TopicSourceInput[];
  /** Regions this material justifies — scales with the documents selected. */
  module_limit?: number;
  coverage?: TopicCoverage;
}

export interface GenerateTopicInput {
  name: string;
  goal: string;
  sources: TopicSourceInput[];
  /** Documents a previous draft missed, to be covered by this one. */
  must_cover?: string[];
}

export interface CreateTopicInput extends GenerateTopicInput {
  description?: string;
  emoji?: string;
  modules: ModuleInit[];
}

export interface TopicSession {
  session_id: string;
  title: string;
  created_at: number;
  updated_at: number;
  status: string;
  active_turn_id: string;
  message_count: number;
  last_message: string;
  pinned: boolean;
  archived: boolean;
  has_pending_question: boolean;
}

async function masteryJson<T>(
  path: string,
  init?: RequestInit,
  action = "load mastery data",
): Promise<T> {
  const res = await apiFetch(apiUrl(path), init);
  if (!res.ok) {
    let detail = "";
    try {
      const payload = (await res.json()) as { detail?: string };
      detail = payload.detail ? `: ${payload.detail}` : "";
    } catch {
      // The status remains actionable when an upstream proxy returns HTML.
    }
    throw new Error(`Failed to ${action} (${res.status})${detail}`);
  }
  return res.json() as Promise<T>;
}

export async function fetchMasteryTopics(
  init?: RequestInit,
): Promise<MasteryTopic[]> {
  const result = await masteryJson<{ topics: MasteryTopic[] }>(
    "/api/mastery-paths/topics",
    init,
    "load topics",
  );
  if (!Array.isArray(result.topics)) {
    throw new Error(
      "Failed to load topics: the server returned an invalid response",
    );
  }
  return result.topics;
}

/** Just enough to name a topic. See ``fetchMasteryTopicIndex``. */
export interface MasteryTopicLabel {
  path_id: string;
  name: string;
  emoji: string;
}

/**
 * The id → name map, without each topic's knowledge map and source excerpts.
 *
 * The sidebar groups study conversations under their topic and reloads on
 * every stream end, so it wants the labels and nothing else; `fetchMasteryTopics`
 * would ship kilobytes per topic to render a header.
 */
export async function fetchMasteryTopicIndex(
  init?: RequestInit,
): Promise<MasteryTopicLabel[]> {
  const result = await masteryJson<{ topics: MasteryTopicLabel[] }>(
    "/api/mastery-paths/topics/index",
    init,
    "load topic index",
  );
  return Array.isArray(result.topics) ? result.topics : [];
}

/** One question the learner could ask here — "" when there is none to offer. */
export async function fetchMasteryAskHint(
  pathId: string,
  sessionId: string,
  init?: RequestInit,
): Promise<string> {
  const query = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : "";
  const result = await masteryJson<{ hint?: string }>(
    `/api/mastery-paths/topics/${encodeURIComponent(pathId)}/ask-hint${query}`,
    init,
    "load ask hint",
  );
  return typeof result.hint === "string" ? result.hint : "";
}

export function fetchMasteryTopic(
  pathId: string,
  init?: RequestInit,
): Promise<MasteryTopic> {
  return masteryJson(
    `/api/mastery-paths/topics/${encodeURIComponent(pathId)}`,
    init,
    "load topic",
  );
}

export function generateMasteryTopicDraft(
  input: GenerateTopicInput,
): Promise<TopicDraft> {
  return masteryJson(
    "/api/mastery-paths/topics/draft",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    },
    "generate learning route",
  );
}

export function createMasteryTopic(
  input: CreateTopicInput,
): Promise<MasteryTopic> {
  return masteryJson(
    "/api/mastery-paths/topics",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    },
    "create topic",
  );
}

export function updateMasteryTopicMap(
  pathId: string,
  modules: ModuleInit[],
): Promise<MasteryTopic> {
  return masteryJson(
    `/api/mastery-paths/topics/${encodeURIComponent(pathId)}/map`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ modules }),
    },
    "update route",
  );
}

export function setMasteryObjectiveOverride(
  pathId: string,
  objectiveId: string,
  mastered: boolean,
  note = "",
): Promise<{ status: string; path_revision: number; map: MasteryMap }> {
  return masteryJson(
    `/api/mastery-paths/topics/${encodeURIComponent(pathId)}/objectives/${encodeURIComponent(objectiveId)}/override`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mastered, note }),
    },
    mastered ? "mark objective mastered" : "restore objective assessment",
  );
}

export async function fetchMasteryTopicSessions(
  pathId: string,
  init?: RequestInit,
): Promise<TopicSession[]> {
  const result = await masteryJson<{
    path_id: string;
    sessions: TopicSession[];
  }>(
    `/api/mastery-paths/topics/${encodeURIComponent(pathId)}/sessions`,
    init,
    "load topic sessions",
  );
  if (!Array.isArray(result.sessions)) {
    throw new Error(
      "Failed to load topic sessions: the server returned an invalid response",
    );
  }
  return result.sessions;
}

// ── Error book (Stage 3, K12) ───────────────────────────────────────────────
// Mirrors deeptutor/capabilities/mastery/error_book.summarize + the
// /kgraph/variants/{concept_id} teacher view (both live under the
// /api/mastery-paths router on the backend).

export interface ErrorRecordItem {
  id: string;
  knowledge_point_id: string;
  knowledge_point_name: string;
  module_id: string;
  error_type: string;
  error_type_label: string;
  status: string;
  retry_count: number;
  created_at: number;
}

export interface WeakPointItem {
  knowledge_point_id: string;
  name: string;
  module_id: string;
  mastery: number;
  error_count: number;
  consecutive_wrong: number;
  unmet_prereqs: string[];
  score: number;
  reason: string;
}

export interface ErrorBookResult {
  book_id: string;
  total_records: number;
  open_records: number;
  graduated_records: number;
  by_error_type: Record<string, number>;
  weak_points: WeakPointItem[];
  backfill_order: string[];
  records: ErrorRecordItem[];
}

export interface FetchErrorBookOpts {
  errorType?: string;
  status?: string;
  topK?: number;
}

export async function fetchErrorBook(
  bookId: string,
  opts: FetchErrorBookOpts = {},
): Promise<ErrorBookResult> {
  const q = new URLSearchParams();
  if (opts.errorType) q.set("error_type", opts.errorType);
  if (opts.status) q.set("status", opts.status);
  if (opts.topK != null) q.set("top_k", String(opts.topK));
  const qs = q.toString();
  const res = await apiFetch(
    apiUrl(
      `/api/mastery-paths/progress/${encodeURIComponent(bookId)}/error-book${
        qs ? `?${qs}` : ""
      }`,
    ),
  );
  if (!res.ok) throw new Error(`Failed to fetch error book: ${res.status}`);
  return res.json();
}

// A single textbook variant (Exercise -> mastery_quiz params).
export interface VariantExercise {
  knowledge_point_id: string;
  exercise_id: string;
  question: string;
  expected_answer: string;
  question_type: string;
  options: string[];
  difficulty: number | null;
  difficulty_label: string;
  source_type: string;
  analysis: string;
  source: string;
}

export interface VariantResult {
  concept_id: string;
  count: number;
  variants: VariantExercise[];
}

export interface FetchVariantsOpts {
  count?: number;
  difficulty?: number | string;
  bookId?: string;
}

export async function fetchVariants(
  conceptId: string,
  opts: FetchVariantsOpts = {},
): Promise<VariantResult> {
  const q = new URLSearchParams();
  if (opts.count != null) q.set("count", String(opts.count));
  if (opts.difficulty != null) q.set("difficulty", String(opts.difficulty));
  if (opts.bookId) q.set("book_id", opts.bookId);
  const qs = q.toString();
  const res = await apiFetch(
    apiUrl(
      `/api/mastery-paths/kgraph/variants/${encodeURIComponent(conceptId)}${
        qs ? `?${qs}` : ""
      }`,
    ),
  );
  if (!res.ok) throw new Error(`Failed to fetch variants: ${res.status}`);
  return res.json();
}

/**
 * Start a mastery path from one K12-KGraph section.
 *
 * The path is keyed by ``kgraph_{section_id}`` (so the textbook navigator and the
 * learning dashboard agree on the storage key). The backend turns the section's
 * teachable subtree into an ordered ``LearningModule``.
 */
export async function startKgraphPath(sectionId: string): Promise<{
  status: string;
  book_id: string;
  module_id: string;
  kp_count: number;
  with_prereqs: number;
  section_name: string;
}> {
  const bookId = `kgraph_${sectionId}`;
  const res = await apiFetch(
    apiUrl(
      `/api/mastery-paths/progress/${encodeURIComponent(bookId)}/from-kgraph`,
    ),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        section_id: sectionId,
        include_prereqs: true,
        prereq_levels: 2,
      }),
    },
  );
  if (!res.ok) {
    let detail = "";
    try {
      const data = await res.json();
      detail = data?.detail || "";
    } catch {
      /* ignore */
    }
    throw new Error(`Failed to start kgraph path: ${res.status} ${detail}`);
  }
  return res.json();
}
