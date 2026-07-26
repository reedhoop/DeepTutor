"use client";

import dynamic from "next/dynamic";
import {
  type KeyboardEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useChatRouteSession } from "@/features/chat/controllers/useChatRouteSession";

import {
  BarChart3,
  BrainCircuit,
  Clapperboard,
  Code2,
  Compass,
  Database,
  FileSearch,
  Globe,
  GraduationCap,
  Image as ImageIcon,
  Lightbulb,
  MessageSquare,
  MessagesSquare,
  Microscope,
  Presentation,
  PenLine,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import type { SelectedRecord } from "@/lib/notebook-selection-types";
import type { SelectedHistorySession } from "@/components/chat/HistorySessionPicker";
import type { SelectedQuestionEntry } from "@/components/chat/QuestionBankPicker";
import ChatComposer from "@/components/chat/home/ChatComposer";
import type { ContextBudget } from "@/components/chat/home/ContextBudgetChip";
import { ChatMessageList } from "@/features/chat/messages";
import { TurnNavigator } from "@/components/chat/home/TurnNavigator";
import SessionLoadingView from "@/components/chat/home/SessionLoadingView";
// Imported eagerly so the drawer shell is always mounted off-screen —
// clicking a chip becomes a single CSS class flip, no chunk fetch + double
// render. The heavy renderers inside still load lazily.
import FilePreviewDrawer from "@/components/chat/preview/FilePreviewDrawer";
import { buildSessionActivity } from "@/components/chat/home/SessionActivityPanel";
import Tooltip from "@/components/common/Tooltip";
import SessionViewerPanel, {
  type SessionViewerPanelHandle,
} from "@/components/chat/home/SessionViewerPanel";
import {
  QuizFollowupProvider,
  useQuizFollowupController,
} from "@/context/QuizFollowupContext";
import {
  GeogebraTabProvider,
  useGeogebraTabOpener,
} from "@/context/GeogebraTabContext";
import { BookmarkPlus, Download, PanelRight } from "lucide-react";
import {
  useChatStateAdapter,
  type MessageAttachment,
  type MessageRequestSnapshot,
} from "@/features/chat/ChatStateAdapter";
import { useAppShell } from "@/context/AppShellContext";
import type { FilePreviewSource } from "@/components/chat/preview/previewerFor";
import type { LLMSelection, StreamEvent } from "@/features/chat/model/protocol";
import {
  extractBase64FromDataUrl,
  readFileAsDataUrl,
} from "@/lib/file-attachments";
import { classifyFile, isSvgFilename } from "@/lib/doc-attachments";
import { useAttachmentLimits } from "@/lib/attachment-limits";
import { useChatAutoScroll } from "@/hooks/useChatAutoScroll";
import { useMeasuredHeight } from "@/hooks/useMeasuredHeight";
import {
  fetchSessionAskHint,
  updateSessionOrganization,
} from "@/lib/session-api";
import {
  DEFAULT_QUIZ_CONFIG,
  buildQuizWSConfig,
  type DeepQuestionFormConfig,
} from "@/lib/quiz-types";
import {
  DEFAULT_VISUALIZE_CONFIG,
  buildVisualizeWSConfig,
  type VisualizeFormConfig,
} from "@/lib/visualize-types";
import {
  buildResearchWSConfig,
  createEmptyResearchConfig,
  validateResearchConfig,
  type DeepResearchFormConfig,
  type OutlineItem,
} from "@/lib/research-types";
import { listKnowledgeBases } from "@/features/knowledge/api/catalog";
import { getSubagentSettings } from "@/lib/subagents-api";
import { useLLMOptions } from "@/hooks/useLLMOptions";
import {
  getEnabledOptionalTools,
  invalidateEnabledOptionalToolsCache,
} from "@/lib/tools-settings";
import {
  ALL_TOOLS,
  getChatCapability,
  type ToolName,
} from "@/features/capabilities/presentation";
import { useCapabilityCatalog } from "@/features/capabilities/useCapabilityCatalog";
import { browserStorage } from "@/shared/storage";
import { downloadChatMarkdown } from "@/lib/chat-export";
import { buildChatOutline, scrollToChatTurn } from "@/lib/chat-outline";
import { buildConversationNotebookSave } from "@/lib/conversation-notebook-save";
import { isPlaceholderSessionTitle } from "@/lib/session-title";
import type { SpaceMemoryFile } from "@/lib/space-items";
import {
  selectedBooksToPayload,
  type SelectedBookReference,
} from "@/lib/book-references";

const NotebookRecordPicker = dynamic(
  () => import("@/components/notebook/NotebookRecordPicker"),
  {
    ssr: false,
  },
);
const HistorySessionPicker = dynamic(
  () => import("@/components/chat/HistorySessionPicker"),
  {
    ssr: false,
  },
);
const MyAgentsPicker = dynamic(
  () => import("@/components/chat/MyAgentsPicker"),
  {
    ssr: false,
  },
);
const QuestionBankPicker = dynamic(
  () => import("@/components/chat/QuestionBankPicker"),
  {
    ssr: false,
  },
);
const MemoryPicker = dynamic(() => import("@/components/chat/MemoryPicker"), {
  ssr: false,
});
const BookReferencePicker = dynamic(
  () => import("@/components/chat/BookReferencePicker"),
  {
    ssr: false,
  },
);
const ReadingReferencePicker = dynamic(
  () => import("@/components/chat/ReadingReferencePicker"),
  {
    ssr: false,
  },
);
const SaveToNotebookModal = dynamic(
  () => import("@/components/notebook/SaveToNotebookModal"),
  {
    ssr: false,
  },
);
// Activity-panel config card hosts the capability-specific form (Quiz /
// Animator / Visualize / Research). Lazy-loaded so capabilities that
// don't need a form (Chat / Solve) don't ship the form JS.
const CapabilityConfigCard = dynamic(
  () => import("@/components/chat/home/CapabilityConfigCard"),
  { ssr: false },
);
const QuizConfigPanel = dynamic(
  () => import("@/components/quiz/QuizConfigPanel"),
  { ssr: false },
);
const VisualizeConfigPanel = dynamic(
  () => import("@/components/visualize/VisualizeConfigPanel"),
  { ssr: false },
);
const ResearchConfigPanel = dynamic(
  () => import("@/components/research/ResearchConfigPanel"),
  { ssr: false },
);

/* ------------------------------------------------------------------ */
/*  Type & data definitions                                           */
/* ------------------------------------------------------------------ */

type ToolName =
  | "brainstorm"
  | "geogebra_analysis"
  | "web_search"
  | "code_execution"
  | "reason"
  | "paper_search"
  | "imagegen"
  | "videogen";

interface ToolDef {
  name: ToolName;
  label: string;
  icon: LucideIcon;
}

const ALL_TOOLS: ToolDef[] = [
  { name: "brainstorm", label: "Brainstorm", icon: Lightbulb },
  { name: "geogebra_analysis", label: "GeoGebra", icon: Compass },
  { name: "web_search", label: "Web Search", icon: Globe },
  { name: "code_execution", label: "Code", icon: Code2 },
  { name: "reason", label: "Reason", icon: Sparkles },
  { name: "paper_search", label: "Arxiv Search", icon: FileSearch },
  { name: "imagegen", label: "Image Gen", icon: ImageIcon },
  { name: "videogen", label: "Video Gen", icon: Clapperboard },
];

interface CapabilityDef {
  value: string;
  label: string;
  description: string;
  icon: LucideIcon;
  allowedTools: ToolName[];
  defaultTools: ToolName[];
  // Loop-engine capabilities run on the chat agent loop (solve / mastery) rather
  // than a bespoke pipeline. They are collapsed into the "More" flyout in the
  // capability picker instead of listed directly. Driven by the loop-capability
  // registry on the backend; mirrored here as a static flag.
  loopEngine?: boolean;
}

const CAPABILITIES: CapabilityDef[] = [
  {
    value: "",
    label: "Chat",
    description: "Flexible conversation with any tool",
    icon: MessageSquare,
    allowedTools: [
      "brainstorm",
      "geogebra_analysis",
      "web_search",
      "code_execution",
      "reason",
      "paper_search",
      "imagegen",
      "videogen",
    ],
    defaultTools: [],
  },
  {
    value: "deep_solve",
    label: "Solve",
    description: "Multi-step reasoning & problem solving",
    icon: BrainCircuit,
    allowedTools: ["web_search", "code_execution", "reason"],
    defaultTools: ["web_search", "code_execution", "reason"],
    loopEngine: true,
  },
  {
    value: "deep_question",
    label: "Quiz",
    description: "Auto-validated question generation",
    icon: PenLine,
    allowedTools: ["web_search", "code_execution"],
    defaultTools: ["web_search", "code_execution"],
  },
  {
    value: "deep_research",
    label: "Research",
    description: "Comprehensive multi-agent research",
    icon: Microscope,
    allowedTools: ["web_search", "paper_search", "code_execution"],
    defaultTools: ["web_search", "paper_search", "code_execution"],
  },
  {
    value: "visualize",
    label: "Visualize",
    description:
      "Generate charts, diagrams, interactive pages, or math animations",
    icon: BarChart3,
    allowedTools: [],
    defaultTools: [],
  },
  {
    value: "mastery_path",
    label: "Mastery Path",
    description: "Mastery-based tutoring with a hard gate",
    icon: GraduationCap,
    // The mastery tools (status/quiz/grade/assess/build) auto-mount server-side
    // when this capability is active; rag auto-mounts when a KB is attached.
    // These are only the extra optional tools the tutor may also reach for.
    allowedTools: ["web_search", "code_execution"],
    defaultTools: [],
    loopEngine: true,
  },
  {
    value: "socratic_tutor",
    label: "Socratic Tutoring",
    description: "Guide by questioning, never hand over the answer",
    icon: MessagesSquare,
    // Socratic tutoring reuses the full chat tool surface and shapes the
    // tutor's replies via a guardrail system block (no dedicated tools).
    allowedTools: ["web_search", "code_execution", "reason"],
    defaultTools: [],
    loopEngine: true,
  },
  {
    value: "feynman_tutor",
    label: "Feynman Tutoring",
    description: "Learn by explaining in your own words; the tutor checks clarity, gaps, and misunderstandings",
    icon: Presentation,
    // Feynman tutoring reuses the full chat tool surface and shapes the
    // tutor's replies via a Feynman-style system block (no dedicated tools).
    allowedTools: ["web_search", "code_execution", "reason"],
    defaultTools: [],
    loopEngine: true,
  },
];

interface KnowledgeBase {
  name: string;
  is_default?: boolean;
  metadata?: {
    /** Connected-source kind, e.g. "obsidian" | "subagent". */
    type?: string;
    /** Backend of a connected subagent: "claude_code" | "codex" | "partner". */
    agent_kind?: string;
  };
}

interface PendingAttachment {
  type: string;
  filename: string;
  base64?: string;
  previewUrl?: string;
  size?: number;
  mimeType?: string;
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                           */
/* ------------------------------------------------------------------ */

function getCapability(value: string | null): CapabilityDef {
  return CAPABILITIES.find((c) => c.value === (value || "")) ?? CAPABILITIES[0];
}

/**
 * Read the context-window measurement a finished turn attached to its
 * `result` event. Scanned newest-first because one turn can emit several
 * results (a consulted subagent emits its own) and only the chat loop's
 * closing one carries the budget; older backends emit none at all, and the
 * measurement is allowed to degrade to "absent" rather than fail a turn.
 */
function readContextBudget(
  events: StreamEvent[] | undefined,
): ContextBudget | null {
  if (!events) return null;
  for (let i = events.length - 1; i >= 0; i -= 1) {
    const ev = events[i];
    if (ev.type !== "result") continue;
    const meta = ev.metadata?.metadata as Record<string, unknown> | undefined;
    const budget = meta?.context_budget as ContextBudget | undefined;
    if (
      budget &&
      typeof budget.window === "number" &&
      typeof budget.used_tokens === "number" &&
      Array.isArray(budget.segments)
    ) {
      return budget;
    }
  }
  return null;
}

/* ------------------------------------------------------------------ */
/*  Chat page                                                         */
/* ------------------------------------------------------------------ */

export default function ChatPage() {
  const params = useParams<{ sessionId?: string[] }>();
  const router = useRouter();
  const { t } = useTranslation();
  const sessionIdParam = params.sessionId?.[0] ?? null;
  const { setActiveSessionId, language: appLanguage } = useAppShell();

  const {
    state,
    setTools,
    setCapability,
    setKBs,
    setLLMSelection,
    setMasteryPathId,
    setPersonaSelection,
    sendMessage,
    cancelStreamingTurn,
    submitUserReply,
    regenerateLastMessage,
    deleteTurn,
    editMessage,
    switchBranch,
    newSession,
    loadSession,
    showCachedSession,
    renameSessionTitle,
  } = useUnifiedChat();

  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  // A connected agent to preselect once it loads, from `?agent=<name>` on the
  // URL (the partner list page links here to drop straight into a chat with a
  // partner). Captured once at first client render — the URL is rewritten to
  // `/home/<sessionId>` as soon as the new session is created, dropping the
  // query — so we can't read it later from the live search params.
  const pendingAgentRef = useRef<string | null | undefined>(undefined);
  if (pendingAgentRef.current === undefined) {
    pendingAgentRef.current =
      typeof window === "undefined"
        ? null
        : new URLSearchParams(window.location.search).get("agent");
  }
  const agentPreselectDoneRef = useRef(false);
  const {
    options: llmOptions,
    activeDefault: activeLLMDefault,
    loading: llmOptionsLoading,
    error: llmOptionsError,
    refresh: refreshLLMOptions,
  } = useLLMOptions();
  // User-toggleable tools the user has enabled in /settings#tools. This is
  // the single source of truth for which optional tools the chat agent may
  // use; the chat composer no longer exposes a picker.
  const [userEnabledTools, setUserEnabledTools] = useState<string[] | null>(
    null,
  );
  const [attachments, setAttachments] = useState<PendingAttachment[]>([]);
  const attachmentLimits = useAttachmentLimits();
  const [dragging, setDragging] = useState(false);
  const [attachmentError, setAttachmentError] = useState<string | null>(null);
  const [previewSource, setPreviewSource] = useState<FilePreviewSource | null>(
    null,
  );
  // Right-side panels — Activity (floating cards) and Viewer (full sidebar
  // with tabs for file previews + web pages). Each independently togglable
  // and persisted across reloads.
  //
  // We initialise both to `false` so the SSR-rendered HTML matches the
  // first client render exactly (no hydration mismatch). The persisted
  // preference is then applied in a post-mount effect below.
  // Single right-side panel: the Activity/Viewer. Its home view is the
  // session activity; files and web pages open as tabs alongside it.
  const [viewerPanelOpen, setViewerPanelOpen] = useState(false);
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (browserStorage.readRaw("local", "dt:chat:viewer-panel") === "1") {
      setViewerPanelOpen(true);
    }
  }, []);
  const setViewerOpen = useCallback((next: boolean) => {
    setViewerPanelOpen(next);
    if (typeof window !== "undefined") {
      browserStorage.writeRaw(
        "local",
        "dt:chat:viewer-panel",
        next ? "1" : "0",
      );
    }
  }, []);
  const toggleViewerPanel = useCallback(() => {
    setViewerPanelOpen((prev) => {
      const next = !prev;
      if (typeof window !== "undefined") {
        browserStorage.writeRaw(
          "local",
          "dt:chat:viewer-panel",
          next ? "1" : "0",
        );
      }
      return next;
    });
  }, []);
  /**
   * Force the panel open on its Activity home. Used by the send-gate when the
   * user tries to send while the active capability still needs its config
   * confirmed — the config card lives on the Activity home, so we open the
   * panel and switch to it. Also used by the capability-switch auto-open
   * effect below.
   */
  const viewerPanelRef = useRef<SessionViewerPanelHandle | null>(null);
  const ensureActivityPanelOpen = useCallback(() => {
    setViewerOpen(true);
    viewerPanelRef.current?.focusActivityHome();
  }, [setViewerOpen]);
  const attachmentErrorTimer = useRef<ReturnType<typeof setTimeout> | null>(
    null,
  );
  const [capMenuOpen, setCapMenuOpen] = useState(false);
  const [quizConfig, setQuizConfig] = useState<DeepQuestionFormConfig>({
    ...DEFAULT_QUIZ_CONFIG,
  });
  const [quizValidationErrors, setQuizValidationErrors] = useState<string[]>(
    [],
  );
  const [quizPdf, setQuizPdf] = useState<File | null>(null);
  const [visualizeConfig, setVisualizeConfig] = useState<VisualizeFormConfig>({
    ...DEFAULT_VISUALIZE_CONFIG,
  });
  const [researchConfig, setResearchConfig] = useState<DeepResearchFormConfig>(
    createEmptyResearchConfig(),
  );
  // Capability-config confirmation gate.
  //
  // For capabilities that need explicit configuration (Quiz, Visualize,
  // Research), the user must click *Confirm* in the right-side Activity
  // panel before sending. Any subsequent edit to the underlying config
  // invalidates the confirmation, so the user re-confirms once they've
  // adjusted settings. Capability switches also reset this flag.
  const [capabilityConfigConfirmed, setCapabilityConfigConfirmed] =
    useState(false);
  // Per-session persistence of the capability-config form. The form lives
  // in local React state, so anything that remounts the page (browser
  // back/forward to /chat/<id>, URL-driven session swap, etc.) would
  // otherwise wipe a confirmed-and-already-sent setup back to defaults.
  // Storing the form by sessionId in localStorage keeps the selections —
  // and the Confirmed badge — stable for the rest of the session.
  const capabilityConfigStorageKey = useMemo(() => {
    const sid = state.sessionId || sessionIdParam || "";
    return sid ? `dt:chat:capability-config:${sid}` : null;
  }, [state.sessionId, sessionIdParam]);
  const lastHydratedConfigKeyRef = useRef<string | null>(null);
  // Hydrate the form configs on first encounter of each session id, so
  // the user's prior selections come back when they return to a session.
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (!capabilityConfigStorageKey) return;
    if (lastHydratedConfigKeyRef.current === capabilityConfigStorageKey) return;
    lastHydratedConfigKeyRef.current = capabilityConfigStorageKey;
    const raw = browserStorage.readRaw("local", capabilityConfigStorageKey);
    if (!raw) return;
    try {
      const parsed = JSON.parse(raw) as {
        quizConfig?: DeepQuestionFormConfig;
        visualizeConfig?: VisualizeFormConfig;
        researchConfig?: DeepResearchFormConfig;
        capabilityConfigConfirmed?: boolean;
      };
      if (parsed.quizConfig) setQuizConfig(parsed.quizConfig);
      if (parsed.visualizeConfig) setVisualizeConfig(parsed.visualizeConfig);
      if (parsed.researchConfig) setResearchConfig(parsed.researchConfig);
      if (typeof parsed.capabilityConfigConfirmed === "boolean") {
        setCapabilityConfigConfirmed(parsed.capabilityConfigConfirmed);
      }
    } catch {
      /* corrupted entry — ignore */
    }
  }, [capabilityConfigStorageKey]);
  // Persist on every change. Write is synchronous and small, and
  // localStorage already de-dupes identical writes at the browser level.
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (!capabilityConfigStorageKey) return;
    browserStorage.writeRaw(
      "local",
      capabilityConfigStorageKey,
      JSON.stringify({
        quizConfig,
        visualizeConfig,
        researchConfig,
        capabilityConfigConfirmed,
      }),
    );
  }, [
    capabilityConfigStorageKey,
    quizConfig,
    visualizeConfig,
    researchConfig,
    capabilityConfigConfirmed,
  ]);
  const [showSaveModal, setShowSaveModal] = useState(false);
  const [showNotebookPicker, setShowNotebookPicker] = useState(false);
  const [showBookPicker, setShowBookPicker] = useState(false);
  const [showReadingPicker, setShowReadingPicker] = useState(false);
  const [showHistoryPicker, setShowHistoryPicker] = useState(false);
  const [showAgentsPicker, setShowAgentsPicker] = useState(false);
  const [showQuestionBankPicker, setShowQuestionBankPicker] = useState(false);
  // Session persona selector (toolbar chip / `/persona` / @space entry all
  // open the same dropdown). The selection itself lives in the unified chat
  // context (state.personaSelection) so it follows the session.
  const [personaSelectorOpen, setPersonaSelectorOpen] = useState(false);
  const [showMemoryPicker, setShowMemoryPicker] = useState(false);
  const [spaceMenuOpen, setSpaceMenuOpen] = useState(false);
  const [selectedNotebookRecords, setSelectedNotebookRecords] = useState<
    SelectedRecord[]
  >([]);
  const [selectedBookReferences, setSelectedBookReferences] = useState<
    SelectedBookReference[]
  >([]);
  const [selectedReadingReferences, setSelectedReadingReferences] = useState<
    SelectedReadingReference[]
  >([]);
  const [selectedHistorySessions, setSelectedHistorySessions] = useState<
    SelectedHistorySession[]
  >([]);
  // Imported-agent conversation references. Same shape as history sessions —
  // they fold into the same history_references payload (see below), so the
  // backend treats them identically; the separate state only keeps the
  // composer's "My Agents" group distinct from "Chat History".
  const [selectedAgentSessions, setSelectedAgentSessions] = useState<
    SelectedHistorySession[]
  >([]);
  const [selectedQuestionEntries, setSelectedQuestionEntries] = useState<
    SelectedQuestionEntry[]
  >([]);
  const [selectedMemoryFiles, setSelectedMemoryFiles] = useState<
    SpaceMemoryFile[]
  >([]);
  const dragCounter = useRef(0);
  const capMenuRef = useRef<HTMLDivElement>(null);
  const capBtnRef = useRef<HTMLButtonElement>(null);
  const spaceMenuRef = useRef<HTMLDivElement>(null);
  const spaceBtnRef = useRef<HTMLButtonElement>(null);
  const initialLoadRef = useRef(false);
  // Session-loading overlay: shown while navigating from chat-history →
  // session detail. Holds an AbortController so the user can cancel.
  const [sessionLoading, setSessionLoading] = useState(false);
  const loadAbortRef = useRef<AbortController | null>(null);
  // Bridge ref: ``ChatComposer`` writes a prefill function into this on
  // mount; ``ChatMessageList`` reads it via ``handlePrefillComposer`` so an
  // ``AskUserOptions`` chip click can drop text into the composer textarea.
  const prefillInputRef = useRef<((text: string) => void) | null>(null);
  const handlePrefillComposer = useCallback((text: string) => {
    prefillInputRef.current?.(text);
  }, []);

  // A clickable node inside an inlined visualization SVG (data-prompt) — and the
  // html widget's sendPrompt bridge — dispatch this window event; mirror it into
  // the composer as a prefilled follow-up (user confirms before sending).
  useEffect(() => {
    const onVizPrompt = (e: Event) => {
      const text = (e as CustomEvent<string>).detail;
      if (typeof text === "string" && text) handlePrefillComposer(text);
    };
    window.addEventListener("dt:visualize-prompt", onVizPrompt);
    return () => window.removeEventListener("dt:visualize-prompt", onVizPrompt);
  }, [handlePrefillComposer]);

  const activeCap = useMemo(
    () =>
      capabilities.find(
        (capability) => capability.value === (state.activeCapability || ""),
      ) ?? getChatCapability(state.activeCapability),
    [capabilities, state.activeCapability],
  );
  const isQuizMode = activeCap.value === "deep_question";
  const isVisualizeMode = activeCap.value === "visualize";
  const isResearchMode = activeCap.value === "deep_research";
  const capabilityNeedsConfig = isQuizMode || isVisualizeMode || isResearchMode;
  const returnedResearchTurnRef = useRef<string | null>(null);

  // Deep Research is a one-shot workflow: once its confirmed-outline turn
  // reaches a terminal event, ordinary composer messages should discuss the
  // report in chat context. Keeping the mode selected caused follow-ups such
  // as "why did this stop?" to become brand-new research outlines. The Retry
  // button still submits the preserved outline explicitly as deep_research.
  useEffect(() => {
    if (state.isStreaming || state.activeCapability !== "deep_research") return;
    const latestAssistant = [...state.messages]
      .reverse()
      .find((message) => message.role === "assistant");
    if (
      !latestAssistant ||
      !shouldReturnToChatAfterResearch(latestAssistant.events)
    ) {
      return;
    }
    const terminal = [...(latestAssistant.events ?? [])]
      .reverse()
      .find((event) => event.type === "done");
    const turnKey = String(terminal?.turn_id || latestAssistant.id || "");
    if (!turnKey || returnedResearchTurnRef.current === turnKey) return;
    returnedResearchTurnRef.current = turnKey;
    setCapability(null);
    setCapabilityConfigConfirmed(false);
  }, [
    setCapability,
    state.activeCapability,
    state.isStreaming,
    state.messages,
  ]);

  // Edit-invalidates-confirm wrappers — flipping any field after the user
  // hit *Confirm* should restore the gate so they re-confirm intentionally.
  // `useCallback` keeps identities stable so the memoized ChatComposer /
  // CapabilityConfigCard don't churn on every keystroke.
  const handleChangeQuizConfig = useCallback((next: DeepQuestionFormConfig) => {
    setQuizConfig(next);
    setQuizValidationErrors([]);
    setCapabilityConfigConfirmed(false);
  }, []);
  const handleUploadQuizPdf = useCallback((file: File | null) => {
    setQuizPdf(file);
    setCapabilityConfigConfirmed(false);
  }, []);
  const handleChangeVisualizeConfig = useCallback(
    (next: VisualizeFormConfig) => {
      setVisualizeConfig(next);
      setCapabilityConfigConfirmed(false);
    },
    [],
  );
  const handleChangeResearchConfig = useCallback(
    (next: DeepResearchFormConfig) => {
      setResearchConfig(next);
      setCapabilityConfigConfirmed(false);
    },
    [],
  );
  const handleConfirmCapabilityConfig = useCallback(() => {
    setCapabilityConfigConfirmed(true);
  }, []);

  /**
   * Auto-open the right-side Activity panel when the user switches into a
   * capability that requires manual configuration (Quiz / Animator /
   * Visualize / Research). We only fire on the transition from "doesn't
   * need config" → "needs config" so we don't fight the user if they
   * close the panel themselves while still in a config-needing mode.
   *
   * Tracking via a ref (instead of deps) avoids re-firing whenever the
   * panel toggles — the open-state flip should be one-shot per cap
   * transition.
   */
  const lastCapabilityNeedsConfigRef = useRef(capabilityNeedsConfig);
  useEffect(() => {
    const prev = lastCapabilityNeedsConfigRef.current;
    lastCapabilityNeedsConfigRef.current = capabilityNeedsConfig;
    if (!prev && capabilityNeedsConfig) {
      ensureActivityPanelOpen();
    }
  }, [capabilityNeedsConfig, ensureActivityPanelOpen]);
  const hasMessages = state.messages.length > 0;
  // A line the user might type next, written by the task model against the
  // conversation's own tail — general prediction, not a question to ask,
  // unlike the mastery/reading composers' hint. Empty conversations already
  // get their own richer suggestions from StarterSuggestions below, so this
  // only ever runs once there is something to continue. Cleared on session
  // switch so a prior chat's guess never lingers as this one's placeholder.
  const [askHint, setAskHint] = useState("");
  useEffect(() => {
    setAskHint("");
  }, [state.sessionId]);
  useEffect(() => {
    if (state.isStreaming || !hasMessages || !state.sessionId) return;
    let cancelled = false;
    void fetchSessionAskHint(state.sessionId).then((hint) => {
      if (!cancelled) setAskHint(hint);
    });
    return () => {
      cancelled = true;
    };
  }, [state.isStreaming, hasMessages, state.sessionId, state.messages.length]);
  // Time-of-day greeting: seeded once on mount from the user's local clock so
  // the heading stays stable while they're on the page. State (not useMemo)
  // because the random pick would otherwise mismatch SSR ↔ client hydration.
  const [welcomeGreeting, setWelcomeGreeting] = useState<string>(
    "What would you like to learn?",
  );
  useEffect(() => {
    const hour = new Date().getHours();
    let bucket: string[];
    if (hour >= 5 && hour < 12) {
      bucket = [
        "Good morning.",
        "Morning — let's learn something.",
        "What would you like to learn?",
      ];
    } else if (hour >= 12 && hour < 17) {
      bucket = [
        "Good afternoon.",
        "Afternoon — what's on your mind?",
        "What would you like to learn?",
      ];
    } else if (hour >= 17 && hour < 22) {
      bucket = [
        "Good evening.",
        "Evening — what shall we explore?",
        "What would you like to learn?",
      ];
    } else {
      bucket = [
        "It's late today.",
        "Burning the midnight oil?",
        "What would you like to learn?",
      ];
    }
    setWelcomeGreeting(bucket[Math.floor(Math.random() * bucket.length)]);
  }, []);
  const firstUserTitle = useMemo(
    () =>
      state.messages
        .find((msg) => msg.role === "user")
        ?.content.trim()
        .replace(/\s+/g, " ")
        .slice(0, 80) || "",
    [state.messages],
  );
  const persistedSessionTitle = state.sessionTitle.trim();
  const displaySessionTitle = isPlaceholderSessionTitle(persistedSessionTitle)
    ? firstUserTitle || t("New chat")
    : persistedSessionTitle;
  const canRenameSession = Boolean(state.sessionId);
  const titleInputRef = useRef<HTMLInputElement | null>(null);
  const skipTitleCommitRef = useRef(false);
  const [sessionTitleDraft, setSessionTitleDraft] =
    useState(displaySessionTitle);
  const [sessionTitleEditing, setSessionTitleEditing] = useState(false);
  const [sessionTitleSaving, setSessionTitleSaving] = useState(false);
  const [sessionTitleError, setSessionTitleError] = useState<string | null>(
    null,
  );
  useEffect(() => {
    if (sessionTitleEditing) return;
    setSessionTitleDraft(displaySessionTitle);
  }, [displaySessionTitle, sessionTitleEditing]);
  useEffect(() => {
    if (!sessionTitleEditing) return;
    window.requestAnimationFrame(() => {
      titleInputRef.current?.focus();
      titleInputRef.current?.select();
    });
  }, [sessionTitleEditing]);
  const startSessionTitleEdit = useCallback(() => {
    if (!canRenameSession) return;
    skipTitleCommitRef.current = false;
    setSessionTitleError(null);
    setSessionTitleDraft(displaySessionTitle);
    setSessionTitleEditing(true);
  }, [canRenameSession, displaySessionTitle]);
  const cancelSessionTitleEdit = useCallback(() => {
    skipTitleCommitRef.current = true;
    setSessionTitleDraft(displaySessionTitle);
    setSessionTitleError(null);
    setSessionTitleEditing(false);
  }, [displaySessionTitle]);
  const commitSessionTitleEdit = useCallback(async () => {
    if (skipTitleCommitRef.current) {
      skipTitleCommitRef.current = false;
      return;
    }
    const next = sessionTitleDraft.trim();
    if (!next) {
      setSessionTitleDraft(displaySessionTitle);
      setSessionTitleEditing(false);
      return;
    }
    if (!canRenameSession || next === persistedSessionTitle) {
      setSessionTitleDraft(next || displaySessionTitle);
      setSessionTitleEditing(false);
      return;
    }
    setSessionTitleSaving(true);
    setSessionTitleError(null);
    try {
      await renameSessionTitle(next);
      setSessionTitleEditing(false);
    } catch (error) {
      console.error("Failed to rename session:", error);
      setSessionTitleError(t("Rename failed"));
      titleInputRef.current?.focus();
    } finally {
      setSessionTitleSaving(false);
    }
  }, [
    canRenameSession,
    displaySessionTitle,
    persistedSessionTitle,
    renameSessionTitle,
    sessionTitleDraft,
    t,
  ]);
  const handleSessionTitleKeyDown = useCallback(
    (event: KeyboardEvent<HTMLInputElement>) => {
      if (event.key === "Enter") {
        event.preventDefault();
        void commitSessionTitleEdit();
      } else if (event.key === "Escape") {
        event.preventDefault();
        cancelSessionTitleEdit();
      }
    },
    [cancelSessionTitleEdit, commitSessionTitleEdit],
  );
  const { ref: composerRef, height: composerHeight } =
    useMeasuredHeight<HTMLDivElement>();
  const researchValidation = useMemo(
    () => validateResearchConfig(researchConfig),
    [researchConfig],
  );
  const notebookReferenceGroups = useMemo(() => {
    const groups = new Map<string, { notebookName: string; count: number }>();
    selectedNotebookRecords.forEach((record) => {
      const existing = groups.get(record.notebookId);
      if (existing) {
        existing.count += 1;
      } else {
        groups.set(record.notebookId, {
          notebookName: record.notebookName,
          count: 1,
        });
      }
    });
    return Array.from(groups.entries()).map(([notebookId, value]) => ({
      notebookId,
      ...value,
    }));
  }, [selectedNotebookRecords]);
  const notebookReferencesPayload = useMemo(() => {
    const grouped = new Map<string, string[]>();
    selectedNotebookRecords.forEach((record) => {
      const current = grouped.get(record.notebookId) || [];
      current.push(record.id);
      grouped.set(record.notebookId, current);
    });
    return Array.from(grouped.entries()).map(([notebook_id, record_ids]) => ({
      notebook_id,
      record_ids,
    }));
  }, [selectedNotebookRecords]);
  const bookReferencesPayload = useMemo(
    () => selectedBooksToPayload(selectedBookReferences),
    [selectedBookReferences],
  );
  const readingReferencesPayload = useMemo(
    () => selectedReadingsToPayload(selectedReadingReferences),
    [selectedReadingReferences],
  );
  // Chat-history and imported-agent references are both just session ids and
  // share one backend field. Merge + de-dupe them here.
  const historyReferencesPayload = useMemo(
    () =>
      Array.from(
        new Set([
          ...selectedHistorySessions.map((session) => session.sessionId),
          ...selectedAgentSessions.map((session) => session.sessionId),
        ]),
      ),
    [selectedHistorySessions, selectedAgentSessions],
  );
  const questionNotebookReferencesPayload = useMemo(
    () => selectedQuestionEntries.map((entry) => entry.id),
    [selectedQuestionEntries],
  );
  const memoryReferencesPayload = useMemo(
    () => [...selectedMemoryFiles],
    [selectedMemoryFiles],
  );
  const { modalMessages: chatSaveMessages, payload: chatSavePayload } =
    useMemo(
      () =>
        buildConversationNotebookSave(state.messages, {
          source: "chat",
          fallbackTitle: "Chat Session",
          activeCapability: state.activeCapability,
          language: state.language,
          sessionId: state.sessionId,
        }),
      [
        state.activeCapability,
        state.language,
        state.messages,
        state.sessionId,
      ],
    );
  const lastMessage = state.messages[state.messages.length - 1];
  const {
    containerRef: messagesContainerRef,
    endRef: messagesEndRef,
    shouldAutoScrollRef,
    scrollToBottom,
    handleScroll: handleMessagesScroll,
  } = useChatAutoScroll({
    hasMessages,
    isStreaming: state.isStreaming,
    composerHeight,
    messageCount: state.messages.length,
    lastMessageContent: lastMessage?.content,
    lastEventCount: lastMessage?.events?.length,
  });

  // ─── Turn navigator ───
  // One tick per question the user asked, rendered in the transcript's
  // left gutter (see ``TurnNavigator``). The outline is derived from the
  // same visible-path walk the message list uses, so switching an edit
  // branch reshapes both together.
  const chatOutline = useMemo(
    () => buildChatOutline(state.messages, state.selectedBranches),
    [state.messages, state.selectedBranches],
  );
  /** Bring a question back on screen and mark where the user landed. */
  const jumpToTurn = useCallback(
    (key: string) => {
      const container = messagesContainerRef.current;
      // 56 px clears the scrollport's top fade so the bubble lands fully
      // opaque rather than half-dissolved under the mask.
      if (scrollToChatTurn(container, key, { topOffset: 56, flash: true })) {
        // Release the streaming pin: otherwise the next content delta snaps
        // the reader straight back to the bottom they just left.
        shouldAutoScrollRef.current = false;
      }
    },
    [messagesContainerRef, shouldAutoScrollRef],
  );
  /** Leave history and start following the live end of the turn again. */
  const resumeFollowingLatest = useCallback(() => {
    shouldAutoScrollRef.current = true;
    scrollToBottom("instant");
  }, [scrollToBottom, shouldAutoScrollRef]);

  const copyAssistantMessage = useCallback(async (content: string) => {
    if (!content.trim()) return;
    try {
      await navigator.clipboard.writeText(content);
    } catch (error) {
      console.error("Failed to copy assistant message:", error);
    }
  }, []);
  /* ---- URL-driven session loading ---- */

  const navigateToHome = useCallback(() => {
    router.replace("/chat", { scroll: false });
  }, [router]);

  /** Abort in-flight load + navigate home. */
  const cancelSessionLoad = useCallback(() => {
    loadAbortRef.current?.abort();
    loadAbortRef.current = null;
    setSessionLoading(false);
    navigateToHome();
  }, [navigateToHome]);

  /**
   * Shared helper: kick off a load. The user can cancel via the ✕ button;
   * otherwise the loading overlay stays until the API responds (no timeout).
   *
   * A session we already hold in memory is painted right away and refreshed
   * in the background — switching back to a conversation read earlier in this
   * visit costs nothing, and the overlay is reserved for the case where we
   * genuinely have nothing to show.
   */
  const startSessionLoad = useCallback(
    (sid: string) => {
      loadAbortRef.current?.abort();
      const ctrl = new AbortController();
      loadAbortRef.current = ctrl;
      const cached = showCachedSession(sid);
      setSessionLoading(!cached);

      void loadSession(sid, { signal: ctrl.signal, revalidate: cached })
        .then(() => {
          if (!ctrl.signal.aborted) {
            loadAbortRef.current = null;
            setSessionLoading(false);
            // Settle at the bottom once the transcript is really laid out.
            // The layout-effect pin runs as the messages first render, when
            // lazily-loaded images (ChatMessages `loading="lazy"`) and the
            // `next/dynamic` capability viewers have not contributed their
            // heights yet, so its `scrollHeight` is short and the viewport
            // stops above the true bottom. One frame later those are in.
            //
            // Only on a cold open. A cached session is already painted at
            // the bottom and this resolves after a background revalidate —
            // re-arming there would yank a reader who had scrolled up.
            if (!cached) {
              shouldAutoScrollRef.current = true;
              requestAnimationFrame(() => {
                requestAnimationFrame(() => {
                  // A newer session may have superseded this one while the
                  // two frames elapsed; that load owns the viewport now.
                  if (!ctrl.signal.aborted) scrollToBottom("instant");
                });
              });
            }
          }
        })
        .catch(() => {
          if (!ctrl.signal.aborted) {
            loadAbortRef.current = null;
            setSessionLoading(false);
            // A background refresh that fails leaves the cached copy on
            // screen; only a cold open has nothing to fall back to.
            if (!cached) navigateToHome();
          }
        });
    },
    [
      loadSession,
      navigateToHome,
      showCachedSession,
      scrollToBottom,
      shouldAutoScrollRef,
    ],
  );

  // Initial mount — load the session from the URL.
  // Uses a ref-based flag so Strict Mode double-mount doesn't break the flow:
  // when React tears down + re-mounts in dev, we reset initialLoadRef in
  // cleanup so the second mount restarts the load cleanly. The abort is
  // deliberately OMITTED from cleanup — cancelSessionLoad handles
  // user-initiated cancellation.
  useEffect(() => {
    if (initialLoadRef.current) return;
    initialLoadRef.current = true;
    if (sessionIdParam) {
      startSessionLoad(sessionIdParam);
    } else {
      newSession();
    }
    return () => {
      initialLoadRef.current = false;
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // When URL param changes (sidebar navigation), load the corresponding session
  const prevSessionIdParam = useRef(sessionIdParam);
  useEffect(() => {
    if (sessionIdParam === prevSessionIdParam.current) return;
    prevSessionIdParam.current = sessionIdParam;
    // Abort any in-flight session load from the previous param
    loadAbortRef.current?.abort();
    loadAbortRef.current = null;
    if (sessionIdParam) {
      if (sessionIdParam === state.sessionId) {
        setSessionLoading(false);
        return;
      }
      startSessionLoad(sessionIdParam);
    } else {
      newSession();
      setSessionLoading(false);
    }
  }, [sessionIdParam, startSessionLoad, newSession, state.sessionId]);

  // When a new session_id is assigned by the server, update the URL
  useEffect(() => {
    if (state.sessionId && !sessionIdParam) {
      router.replace(`/chat/${state.sessionId}`, { scroll: false });
    }
  }, [state.sessionId, sessionIdParam, router]);

  useEffect(() => {
    setActiveSessionId(state.sessionId || sessionIdParam || null);
  }, [state.sessionId, sessionIdParam, setActiveSessionId]);

  const refreshKnowledgeBases = useCallback(
    async (options?: { force?: boolean }) => {
      try {
        const list = await listKnowledgeBases({ force: options?.force });
        setKnowledgeBases(list);
      } catch {
        setKnowledgeBases([]);
      }
    },
    [],
  );

  /* Load KBs.
   *
   * Switching sessions remounts this page (the session id is a route
   * segment), so these mount-time loads run again on every switch. They read
   * through the shared client cache rather than forcing a refetch: forcing
   * would put a handful of session-independent requests on the wire in
   * parallel with the session fetch itself, and they'd compete for the same
   * six connections — that, not the conversation's length, is what used to
   * make opening a chat feel slow. The focus/visibility listener below is
   * what keeps these values fresh. */
  useEffect(() => {
    void refreshKnowledgeBases();
  }, [refreshKnowledgeBases]);

  const refreshUserEnabledTools = useCallback(
    async (options?: { force?: boolean }) => {
      try {
        const list = await getEnabledOptionalTools({ force: options?.force });
        setUserEnabledTools(list);
      } catch {
        setUserEnabledTools([]);
      }
    },
    [],
  );

  /* Load user tool prefs */
  useEffect(() => {
    void refreshUserEnabledTools();
  }, [refreshUserEnabledTools]);

  useEffect(() => {
    if (state.llmSelection || !activeLLMDefault) return;
    setLLMSelection(activeLLMDefault);
  }, [activeLLMDefault, setLLMSelection, state.llmSelection]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const refresh = () => {
      void refreshKnowledgeBases({ force: true });
      void refreshLLMOptions({ force: true, background: true });
      // Picks up toggles the user changed in another tab (/settings#tools).
      invalidateEnabledOptionalToolsCache();
      void refreshUserEnabledTools({ force: true });
    };
    const refreshWhenVisible = () => {
      if (document.visibilityState === "visible") refresh();
    };
    window.addEventListener("focus", refresh);
    window.addEventListener("pageshow", refresh);
    document.addEventListener("visibilitychange", refreshWhenVisible);
    return () => {
      window.removeEventListener("focus", refresh);
      window.removeEventListener("pageshow", refresh);
      document.removeEventListener("visibilitychange", refreshWhenVisible);
    };
  }, [refreshKnowledgeBases, refreshLLMOptions, refreshUserEnabledTools]);

  /* Composer setup requested by the URL that opened this page. Runs once:
     from here on the composer is the user's to change. */
  useEffect(() => {
    setCapabilityConfigs(loadCapabilityPlaygroundConfigs());
  }, []);

  /* URL query params (capability, tool, persistent mastery path) */
  useEffect(() => {
    if (typeof window === "undefined") return;
    const p = new URLSearchParams(window.location.search);
    const qc = p.get("capability");
    const qt = p.getAll("tool");
    const masteryPathId = p.get("mastery_path_id")?.trim();
    if (masteryPathId) setMasteryPathId(masteryPathId);
    if (qc !== null) handleSelectCapability(qc || "");
    else if (qt.length) {
      const valid = qt.filter((t): t is ToolName =>
        ALL_TOOLS.some((d) => d.name === t),
      );
      if (valid.length) setTools(Array.from(new Set(valid)));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isCapabilityCatalogLoading]);

  /* What a conversation inherits from the course it opens in: its mode, its
     persona, and its material.

     The server has always been willing to supply these (`_apply_course_defaults`
     in turn_runtime) — but only for a payload that omits the fields, and this
     composer always sends all three, so the branch never ran for anyone using
     the app. Doing it here instead also puts the inheritance where the learner
     can see it: the mode chip and the knowledge-base selection visibly become
     the course's before they type, and stay theirs to override.

     Applied once, and only to a conversation launched into the course with
     nothing said yet: an explicit `?capability=` is the learner being specific
     and outranks the course, and a transcript already underway keeps whatever
     it has been running as. */
  useEffect(() => {
    if (courseDefaultsAppliedRef.current) return;
    const launched = launchCourseRef.current;
    if (!launched || !courses.length || hasMessages) return;
    const course = courses.find((item) => item.id === launched);
    if (!course) return;
    courseDefaultsAppliedRef.current = true;
    const explicitCapability = readChatLaunchIntent(
      window.location.search,
    ).capability;
    if (explicitCapability === null && course.default_capability) {
      handleSelectCapability(course.default_capability);
    }
    if (course.default_persona) setPersonaSelection(course.default_persona);
    // The course's own reading is what a conversation inside it should be able
    // to search. Only seeds an untouched selection — never clears one the
    // learner already made.
    const courseKbs = course.resources
      .filter((resource) => resource.kind === "knowledge_base")
      .map((resource) => resource.ref_id);
    if (courseKbs.length && state.knowledgeBases.length === 0) {
      setKBs(courseKbs);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [courses, hasMessages]);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      const t = e.target as Node;
      if (
        capMenuRef.current &&
        !capMenuRef.current.contains(t) &&
        capBtnRef.current &&
        !capBtnRef.current.contains(t)
      )
        setCapMenuOpen(false);
      if (
        spaceMenuRef.current &&
        !spaceMenuRef.current.contains(t) &&
        spaceBtnRef.current &&
        !spaceBtnRef.current.contains(t)
      )
        setSpaceMenuOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  // Keep state.enabledTools = (user's toggleable set) ∩ (capability's allowed
  // set). Re-runs when the user flips a toggle in /settings#tools or when
  // the active capability changes. The composer no longer owns this — the
  // /settings#tools page is the single switchboard.
  useEffect(() => {
    if (userEnabledTools === null) return;
    const allowed = new Set(activeCap.allowedTools);
    const next = userEnabledTools.filter((tool) =>
      allowed.has(tool as ToolName),
    );
    const current = state.enabledTools;
    const same =
      current.length === next.length &&
      current.every((tool, idx) => tool === next[idx]);
    if (!same) setTools(next);
  }, [activeCap.allowedTools, setTools, state.enabledTools, userEnabledTools]);

  /* ---- handlers ---- */

  /* Changing the course from the composer. An existing conversation is moved
     right away rather than at the next turn: the sidebar groups by this, so a
     move the learner made but never "confirmed" by typing would look like it
     did not take. A conversation with no session yet has nothing to write to —
     its binding rides along with the first turn's `_course_id`. */
  const handleSelectCourse = useCallback(
    (nextCourseId: string) => {
      setCourseId(nextCourseId);
      const sid = state.sessionId;
      if (!sid) return;
      void updateSessionOrganization(sid, {
        course_id: nextCourseId,
      }).catch(() => {
        // The turn's own `_course_id` still carries the change, so a failed
        // eager write costs the sidebar an immediate regroup, nothing more.
      });
    },
    [setCourseId, state.sessionId],
  );

  const handleSelectCapability = useCallback(
    (value: string) => {
      const cap =
        capabilities.find((capability) => capability.value === value) ??
        capabilities[0] ??
        getChatCapability("");
      setCapability(cap.value || null);
      // Per-capability tool selection now derives from the user's saved
      // settings (/settings#tools) intersected with the capability's
      // allow-list.
      const baseline =
        userEnabledTools === null ? cap.allowedTools : userEnabledTools;
      const enabledToolsForCap = baseline.filter((tool) =>
        cap.allowedTools.includes(tool as ToolName),
      );
      setTools(enabledToolsForCap);
      // Switching capability invalidates any prior config confirmation —
      // the new capability has its own form that needs explicit confirm.
      setCapabilityConfigConfirmed(false);
      setCapMenuOpen(false);
    },
    [capabilities, setCapability, setTools, userEnabledTools],
  );

  const fileToAttachment = fileToPendingAttachment;

  const showAttachmentError = useCallback((message: string) => {
    setAttachmentError(message);
    if (attachmentErrorTimer.current) {
      clearTimeout(attachmentErrorTimer.current);
    }
    attachmentErrorTimer.current = setTimeout(() => {
      setAttachmentError(null);
      attachmentErrorTimer.current = null;
    }, 4000);
  }, []);

  const filterAndReportFiles = useCallback(
    (files: File[]): File[] => {
      const { accepted, rejected } = selectAttachmentFiles(
        files,
        attachments.reduce((total, item) => total + (item.size ?? 0), 0),
        attachmentLimits,
      );
      if (rejected.length) {
        const first = rejected[0];
        let msg: string;
        if (first.reason === "too_large") {
          msg = t("File too large: {{name}}", { name: first.name });
        } else if (first.reason === "quota") {
          msg = t("Too many files, skipped some");
        } else {
          msg = t("Unsupported file type: {{name}}", { name: first.name });
        }
        showAttachmentError(msg);
      }
      return accepted;
    },
    [attachments, attachmentLimits, showAttachmentError, t],
  );

  const handlePaste = useCallback(
    async (event: React.ClipboardEvent) => {
      const items = Array.from(event.clipboardData.items);
      const files = items
        .filter((item) => item.kind === "file")
        .map((item) => item.getAsFile())
        .filter((f): f is File => f !== null);
      const accepted = filterAndReportFiles(files);
      if (!accepted.length) return;
      event.preventDefault();
      const next = await Promise.all(accepted.map(fileToAttachment));
      setAttachments((prev) => [...prev, ...next]);
    },
    [fileToAttachment, filterAndReportFiles],
  );

  const removeAttachment = useCallback((index: number) => {
    setAttachments((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const handlePreviewPendingAttachment = useCallback(
    (index: number) => {
      const a = attachments[index];
      if (!a) return;
      setPreviewSource({
        filename: a.filename,
        mimeType: a.mimeType,
        type: a.type,
        base64: a.base64,
        size: a.size,
      });
    },
    [attachments],
  );

  // Fold all messages once per state.messages change to power the
  // SessionActivityPanel on the right (tools, KBs, space refs, attachments).
  const sessionActivity = useMemo(
    () => buildSessionActivity(state.messages),
    [state.messages],
  );

  // Context-window readout for the composer chip: the newest turn that was
  // actually measured. Walking newest-first is what keeps the number steady
  // while a new turn streams — the in-flight assistant message has no result
  // event yet, so the walk falls through to the last completed turn and the
  // chip flips exactly once, when the new measurement lands.
  const contextBudget = useMemo(() => {
    for (let i = state.messages.length - 1; i >= 0; i -= 1) {
      const msg = state.messages[i];
      if (msg.role !== "assistant") continue;
      const budget = readContextBudget(msg.events);
      if (budget) return budget;
    }
    return null;
  }, [state.messages]);

  /**
   * Capability-config card rendered at the bottom of the Activity panel.
   *
   * Returns null for capabilities that don't need explicit configuration
   * (Chat / Solve) — the Activity panel falls back to its standard
   * sections (tools, KBs, space, attachments) plus the empty-state card.
   *
   * For Quiz / Animator / Visualize / Research, we wrap the matching bare
   * ConfigPanel in a `CapabilityConfigCard` that provides the header,
   * Confirm button, and validation-error display. The Confirm gate is
   * wired through `capabilityConfigConfirmed` / `handleConfirmCapabilityConfig`.
   */
  const capabilityConfigSection = useMemo(() => {
    if (!capabilityNeedsConfig) return null;
    if (isQuizMode) {
      return (
        <CapabilityConfigCard
          capability="deep_question"
          confirmed={capabilityConfigConfirmed}
          canConfirm={quizValidationErrors.length === 0}
          validationErrors={quizValidationErrors}
          onConfirm={handleConfirmCapabilityConfig}
        >
          <QuizConfigPanel
            value={quizConfig}
            onChange={handleChangeQuizConfig}
            uploadedPdf={quizPdf}
            onUploadPdf={handleUploadQuizPdf}
          />
        </CapabilityConfigCard>
      );
    }
    if (isVisualizeMode) {
      return (
        <CapabilityConfigCard
          capability="visualize"
          confirmed={capabilityConfigConfirmed}
          canConfirm
          onConfirm={handleConfirmCapabilityConfig}
        >
          <VisualizeConfigPanel
            value={visualizeConfig}
            onChange={handleChangeVisualizeConfig}
          />
        </CapabilityConfigCard>
      );
    }
    // Research: forward validation errors so the user sees what's missing
    // before they hit Confirm. `canConfirm` only flips false when there's
    // an actual error (e.g. mode/depth not selected).
    const researchErrorMessages = Object.values(researchValidation.errors);
    return (
      <CapabilityConfigCard
        capability="deep_research"
        confirmed={capabilityConfigConfirmed}
        canConfirm={researchErrorMessages.length === 0}
        validationErrors={researchErrorMessages}
        onConfirm={handleConfirmCapabilityConfig}
      >
        <ResearchConfigPanel
          value={researchConfig}
          errors={researchValidation.errors}
          onChange={handleChangeResearchConfig}
        />
      </CapabilityConfigCard>
    );
  }, [
    capabilityNeedsConfig,
    isQuizMode,
    isVisualizeMode,
    capabilityConfigConfirmed,
    handleConfirmCapabilityConfig,
    quizConfig,
    quizValidationErrors,
    quizPdf,
    handleChangeQuizConfig,
    handleUploadQuizPdf,
    visualizeConfig,
    handleChangeVisualizeConfig,
    researchConfig,
    researchValidation.errors,
    handleChangeResearchConfig,
  ]);

  // Clicking an attachment (from the Activity home or from a chat message)
  // routes into the panel as a new file tab. It auto-opens and the
  // preference is persisted so a follow-up click feels instant.
  const handlePreviewMessageAttachment = useCallback((a: MessageAttachment) => {
    viewerPanelRef.current?.openFileTab(a);
  }, []);

  // Event-delegated link interception inside the messages container. When
  // the user clicks an http(s) link in an assistant message, we open it as
  // a Viewer tab instead of letting the browser navigate / open a new tab.
  // Cmd/ctrl/shift + click keep their standard meaning (open in browser).
  const handleMessagesClick = useCallback((event: React.MouseEvent) => {
    if (event.defaultPrevented) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey)
      return;
    if (event.button !== 0) return;
    const target = event.target as HTMLElement | null;
    if (!target) return;
    const anchor = target.closest<HTMLAnchorElement>("a[href]");
    if (!anchor) return;
    const href = anchor.getAttribute("href");
    if (!href) return;
    if (!/^https?:\/\//i.test(href)) return;
    event.preventDefault();
    viewerPanelRef.current?.openWebTab(href);
  }, []);

  const handleClosePreview = useCallback(() => {
    setPreviewSource(null);
  }, []);

  const handleDragEnter = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter.current += 1;
    if (e.dataTransfer.types.includes("Files")) setDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter.current -= 1;
    if (dragCounter.current === 0) setDragging(false);
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  }, []);

  const handleDrop = useCallback(
    async (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setDragging(false);
      dragCounter.current = 0;
      const accepted = filterAndReportFiles(Array.from(e.dataTransfer.files));
      if (!accepted.length) return;
      const next = await Promise.all(accepted.map(fileToAttachment));
      setAttachments((prev) => [...prev, ...next]);
    },
    [fileToAttachment, filterAndReportFiles],
  );

  const handleAddFiles = useCallback(
    async (files: File[]) => {
      const accepted = filterAndReportFiles(files);
      if (!accepted.length) return;
      const next = await Promise.all(accepted.map(fileToAttachment));
      setAttachments((prev) => [...prev, ...next]);
    },
    [fileToAttachment, filterAndReportFiles],
  );

  // Connected subagents are stored as ``type: subagent`` KBs. Derive the
  // selected one before the send callback so the callback can depend on the
  // current selection instead of capturing an undeclared-later value.
  const agentNameSet = useMemo(
    () =>
      new Set(
        knowledgeBases
          .filter((kb) => kb.metadata?.type === "subagent")
          .map((kb) => kb.name),
      ),
    [knowledgeBases],
  );
  const selectedAgent = useMemo(
    () => state.knowledgeBases.find((name) => agentNameSet.has(name)) ?? null,
    [state.knowledgeBases, agentNameSet],
  );
  // How many times DeepTutor may consult the selected agent this turn. Seeded
  // from the configured default; the composer's stepper overrides it per turn.
  const [subagentBudget, setSubagentBudget] = useState<number | null>(null);
  useEffect(() => {
    void getSubagentSettings()
      .then((settings) => setSubagentBudget(settings.consult_budget))
      .catch(() => undefined);
  }, []);

  const handleSend = useCallback(
    async (content: string) => {
      if (
        (!content &&
          !attachments.length &&
          !selectedBookReferences.length &&
          !selectedReadingReferences.length &&
          !selectedNotebookRecords.length &&
          !selectedHistorySessions.length &&
          !selectedQuestionEntries.length &&
          !selectedMemoryFiles.length) ||
        state.isStreaming
      )
        return;

      const quizPrompt = content.trim().toLowerCase();
      const isPlaceholderQuizPrompt = new Set([
        "开始",
        "开始生成",
        "生成",
        "生成题目",
        "start",
        "generate",
      ]).has(quizPrompt);
      const hasQuizSource = Boolean(content.trim()) && !isPlaceholderQuizPrompt;
      if (
        isQuizMode &&
        quizConfig.mode === "custom" &&
        !hasQuizSource &&
        !attachments.length &&
        !selectedBookReferences.length &&
        !selectedNotebookRecords.length &&
        !selectedHistorySessions.length &&
        !selectedQuestionEntries.length &&
        !selectedMemoryFiles.length
      ) {
        setQuizValidationErrors([
          t(
            "Please provide a topic, for example: generate questions about limits.",
          ),
        ]);
        ensureActivityPanelOpen();
        return;
      }

      let extraAttachments = attachments.map((a) => ({
        type: a.type,
        filename: a.filename,
        base64: a.base64,
        mime_type: a.mimeType,
      }));
      let config: Record<string, unknown> | undefined;

      if (isQuizMode) {
        config = buildQuizWSConfig(quizConfig);
        if (quizConfig.mode === "mimic" && quizPdf) {
          const b64 = extractBase64FromDataUrl(
            await readFileAsDataUrl(quizPdf),
          );
          extraAttachments = [
            ...extraAttachments,
            {
              type: "pdf",
              filename: quizPdf.name,
              base64: b64,
              mime_type: "application/pdf",
            },
          ];
        }
      }
      if (isVisualizeMode) config = buildVisualizeWSConfig(visualizeConfig);
      if (isResearchMode) {
        if (!researchValidation.valid) return;
        config = buildResearchWSConfig(researchConfig);
      }
      // When a connected agent is selected, carry the per-turn consult budget
      // (how many times DeepTutor may ask it) so the subagent capability uses it.
      if (selectedAgent && subagentBudget) {
        config = { ...(config ?? {}), subagent_consult_budget: subagentBudget };
      }