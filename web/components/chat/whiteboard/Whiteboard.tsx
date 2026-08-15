"use client";

import i18n from "i18next";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  Circle,
  Eraser,
  Grid3x3,
  Minus,
  MoveUpRight,
  PanelTop,
  PenTool,
  Redo2,
  Send,
  Sparkles,
  Square,
  Trash2,
  Type,
  Undo2,
  X,
  type LucideIcon,
} from "lucide-react";

/** Chinese-first inline translation helper (mirrors the other ER surfaces). */
const tr = (zh: string, en: string) =>
  i18n.language?.toLowerCase().startsWith("zh") ? zh : en;

const CANVAS_W = 1200;
const CANVAS_H = 750;
const MAX_HISTORY = 12;

const COLORS = [
  "#111827", // ink black
  "#dc2626", // red (marking)
  "#2563eb", // blue (tutor ink)
  "#16a34a", // green
  "#d97706", // orange
  "#7c3aed", // violet
];

const SIZES = [
  { label: tr("细", "Thin"), value: 2 },
  { label: tr("中", "Medium"), value: 4 },
  { label: tr("粗", "Thick"), value: 7 },
];

type Tool =
  | "pen"
  | "highlighter"
  | "line"
  | "rect"
  | "ellipse"
  | "arrow"
  | "text"
  | "eraser";

interface WhiteboardProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Called with a PNG data URL when the user sends the board to the tutor. */
  onInsert: (dataUrl: string) => void;
}

interface ToolDef {
  id: Tool;
  icon: LucideIcon;
  label: string;
}

const TOOLS: ToolDef[] = [
  { id: "pen", icon: PenTool, label: tr("画笔", "Pen") },
  { id: "highlighter", icon: Sparkles, label: tr("高亮", "Highlighter") },
  { id: "line", icon: Minus, label: tr("直线", "Line") },
  { id: "rect", icon: Square, label: tr("矩形", "Rectangle") },
  { id: "ellipse", icon: Circle, label: tr("椭圆", "Ellipse") },
  { id: "arrow", icon: MoveUpRight, label: tr("箭头", "Arrow") },
  { id: "text", icon: Type, label: tr("文本", "Text") },
  { id: "eraser", icon: Eraser, label: tr("橡皮", "Eraser") },
];

export function Whiteboard({ open, onOpenChange, onInsert }: WhiteboardProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [tool, setTool] = useState<Tool>("pen");
  const [color, setColor] = useState(COLORS[0]);
  const [size, setSize] = useState(SIZES[1].value);
  const [grid, setGrid] = useState(true);
  const [hasInk, setHasInk] = useState(false);
  const [undoCount, setUndoCount] = useState(0);
  const [redoCount, setRedoCount] = useState(0);

  // Drawing state (kept in refs so pointer handlers stay stable).
  const drawingRef = useRef(false);
  const pointerIdRef = useRef<number | null>(null);
  const startRef = useRef<{ x: number; y: number } | null>(null);
  const lastRef = useRef<{ x: number; y: number } | null>(null);
  const previewRef = useRef<ImageData | null>(null); // pre-stroke snapshot for shape preview
  const undoStackRef = useRef<ImageData[]>([]);
  const redoStackRef = useRef<ImageData[]>([]);
  const [textDraft, setTextDraft] = useState<{
    x: number;
    y: number;
    value: string;
  } | null>(null);
  const textDraftRef = useRef<HTMLInputElement | null>(null);

  // Sync history counts after any stack mutation.
  const syncHistory = useCallback(() => {
    setUndoCount(undoStackRef.current.length);
    setRedoCount(redoStackRef.current.length);
  }, []);

  const pushHistory = useCallback(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    undoStackRef.current.push(
      ctx.getImageData(0, 0, canvas.width, canvas.height),
    );
    if (undoStackRef.current.length > MAX_HISTORY) {
      undoStackRef.current.shift();
    }
    redoStackRef.current = [];
    syncHistory();
  }, [syncHistory]);

  // Initialize (or reset) the canvas when the board opens for the first time.
  const initializedRef = useRef(false);
  useEffect(() => {
    if (!open || initializedRef.current) return;
    initializedRef.current = true;
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    undoStackRef.current = [];
    redoStackRef.current = [];
    syncHistory();
    setHasInk(false);
  }, [open, syncHistory]);

  const pointFromEvent = useCallback(
    (e: React.PointerEvent<HTMLCanvasElement>) => {
      const canvas = canvasRef.current!;
      const rect = canvas.getBoundingClientRect();
      return {
        x: ((e.clientX - rect.left) * canvas.width) / rect.width,
        y: ((e.clientY - rect.top) * canvas.height) / rect.height,
      };
    },
    [],
  );

  const strokeStyle = useCallback(
    (activeTool: Tool) =>
      activeTool === "eraser"
        ? "rgba(0,0,0,0)" // destination-out handles erasing; style unused
        : activeTool === "highlighter"
          ? color + "66" // ~40% alpha highlight
          : color,
    [color],
  );

  const beginShape = useCallback(
    (e: React.PointerEvent<HTMLCanvasElement>) => {
      const canvas = canvasRef.current;
      const ctx = canvas?.getContext("2d");
      if (!canvas || !ctx) return;
      const p = pointFromEvent(e);
      // Text tool: place a draft input instead of drawing.
      if (tool === "text") {
        setTextDraft({ x: p.x, y: p.y, value: "" });
        return;
      }
      pushHistory();
      previewRef.current = ctx.getImageData(0, 0, canvas.width, canvas.height);
      canvas.setPointerCapture(e.pointerId);
      pointerIdRef.current = e.pointerId;
      drawingRef.current = true;
      startRef.current = p;
      lastRef.current = p;
      if (tool === "pen" || tool === "highlighter" || tool === "eraser") {
        ctx.globalAlpha = 1;
        ctx.strokeStyle = strokeStyle(tool);
        ctx.fillStyle = strokeStyle(tool);
        ctx.lineWidth =
          tool === "eraser"
            ? size * 6
            : tool === "highlighter"
              ? size * 5
              : size;
        ctx.lineCap = "round";
        ctx.lineJoin = "round";
        ctx.globalCompositeOperation = tool === "eraser" ? "destination-out" : "source-over";
        // Dot so a single tap registers.
        ctx.beginPath();
        ctx.arc(p.x, p.y, ctx.lineWidth / 2, 0, Math.PI * 2);
        ctx.fill();
        ctx.globalCompositeOperation = "source-over";
      }
      // Any stroke start (freehand OR shape tool) marks the board as having ink.
      setHasInk(true);
    },
    [pointFromEvent, pushHistory, size, strokeStyle, tool],
  );

  const drawShapePreview = useCallback(
    (ctx: CanvasRenderingContext2D, from: { x: number; y: number }, to: { x: number; y: number }) => {
      ctx.strokeStyle = color;
      ctx.lineWidth = size;
      ctx.lineCap = "round";
      if (tool === "line") {
        ctx.beginPath();
        ctx.moveTo(from.x, from.y);
        ctx.lineTo(to.x, to.y);
        ctx.stroke();
      } else if (tool === "rect") {
        ctx.strokeRect(
          Math.min(from.x, to.x),
          Math.min(from.y, to.y),
          Math.abs(to.x - from.x),
          Math.abs(to.y - from.y),
        );
      } else if (tool === "ellipse") {
        ctx.beginPath();
        ctx.ellipse(
          (from.x + to.x) / 2,
          (from.y + to.y) / 2,
          Math.abs(to.x - from.x) / 2,
          Math.abs(to.y - from.y) / 2,
          0,
          0,
          Math.PI * 2,
        );
        ctx.stroke();
      } else if (tool === "arrow") {
        ctx.beginPath();
        ctx.moveTo(from.x, from.y);
        ctx.lineTo(to.x, to.y);
        ctx.stroke();
        const angle = Math.atan2(to.y - from.y, to.x - from.x);
        const head = 14;
        ctx.beginPath();
        ctx.moveTo(to.x, to.y);
        ctx.lineTo(
          to.x - head * Math.cos(angle - Math.PI / 6),
          to.y - head * Math.sin(angle - Math.PI / 6),
        );
        ctx.lineTo(
          to.x - head * Math.cos(angle + Math.PI / 6),
          to.y - head * Math.sin(angle + Math.PI / 6),
        );
        ctx.closePath();
        ctx.fill();
      }
    },
    [color, size, tool],
  );

  const movePointer = useCallback(
    (e: React.PointerEvent<HTMLCanvasElement>) => {
      if (!drawingRef.current) return;
      const canvas = canvasRef.current;
      const ctx = canvas?.getContext("2d");
      if (!canvas || !ctx) return;
      const p = pointFromEvent(e);
      if (tool === "pen" || tool === "highlighter" || tool === "eraser") {
        ctx.globalCompositeOperation = tool === "eraser" ? "destination-out" : "source-over";
        ctx.strokeStyle = strokeStyle(tool);
        ctx.lineWidth =
          tool === "eraser"
            ? size * 6
            : tool === "highlighter"
              ? size * 5
              : size;
        ctx.lineCap = "round";
        ctx.lineJoin = "round";
        ctx.beginPath();
        ctx.moveTo(lastRef.current!.x, lastRef.current!.y);
        ctx.lineTo(p.x, p.y);
        ctx.stroke();
        ctx.globalCompositeOperation = "source-over";
        lastRef.current = p;
        setHasInk(true);
      } else if (startRef.current) {
        // Shape tools: restore pre-stroke snapshot, draw live preview.
        if (previewRef.current) ctx.putImageData(previewRef.current, 0, 0);
        drawShapePreview(ctx, startRef.current, p);
      }
    },
    [drawShapePreview, pointFromEvent, size, strokeStyle, tool],
  );

  const endPointer = useCallback(() => {
    if (!drawingRef.current) return;
    const canvas = canvasRef.current;
    if (canvas && pointerIdRef.current != null) {
      canvas.releasePointerCapture(pointerIdRef.current);
    }
    drawingRef.current = false;
    pointerIdRef.current = null;
    startRef.current = null;
    lastRef.current = null;
    previewRef.current = null;
  }, []);

  // Commit a text draft to the canvas.
  const commitText = useCallback(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx || !textDraftRef.current || !textDraft) return;
    const value = textDraftRef.current.value.trim();
    const pos = textDraft;
    if (value) {
      pushHistory();
      ctx.font = `${Math.max(20, size * 5)}px "Segoe UI", system-ui, sans-serif`;
      ctx.fillStyle = color;
      ctx.textBaseline = "top";
      ctx.fillText(value, pos.x, pos.y);
      setHasInk(true);
    }
    setTextDraft(null);
  }, [color, pushHistory, size, textDraft]);

  // True when the canvas is fully transparent (blank). `hasInk` gates the
  // clear/export/send buttons; recomputing it on undo keeps the state correct
  // after "clear → undo restores ink" (mirrors the DrawPad fix).
  const isCanvasBlank = useCallback((): boolean => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return true;
    const { data } = ctx.getImageData(0, 0, canvas.width, canvas.height);
    for (let i = 3; i < data.length; i += 4) {
      if (data[i] !== 0) return false;
    }
    return true;
  }, []);

  const undo = useCallback(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    const prev = undoStackRef.current.pop();
    if (!prev) return;
    const current = ctx.getImageData(0, 0, canvas.width, canvas.height);
    redoStackRef.current.push(current);
    ctx.putImageData(prev, 0, 0);
    syncHistory();
    setHasInk(!isCanvasBlank());
  }, [syncHistory, isCanvasBlank]);

  const redo = useCallback(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    const next = redoStackRef.current.pop();
    if (!next) return;
    const current = ctx.getImageData(0, 0, canvas.width, canvas.height);
    undoStackRef.current.push(current);
    ctx.putImageData(next, 0, 0);
    syncHistory();
    setHasInk(true);
  }, [syncHistory]);

  const clearBoard = useCallback(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    pushHistory();
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    setHasInk(false);
  }, [pushHistory]);

  const exportPng = useCallback((): string => {
    const canvas = canvasRef.current;
    if (!canvas) return "";
    // Export with a white background (and optional grid) so the image is
    // legible for the multimodal tutor.
    const out = document.createElement("canvas");
    out.width = canvas.width;
    out.height = canvas.height;
    const octx = out.getContext("2d")!;
    octx.fillStyle = "#ffffff";
    octx.fillRect(0, 0, out.width, out.height);
    if (grid) {
      octx.strokeStyle = "#e2e8f0";
      octx.lineWidth = 1;
      const step = 50;
      for (let x = step; x < out.width; x += step) {
        octx.beginPath();
        octx.moveTo(x, 0);
        octx.lineTo(x, out.height);
        octx.stroke();
      }
      for (let y = step; y < out.height; y += step) {
        octx.beginPath();
        octx.moveTo(0, y);
        octx.lineTo(out.width, y);
        octx.stroke();
      }
      // Axes
      octx.strokeStyle = "#94a3b8";
      octx.lineWidth = 2;
      octx.beginPath();
      octx.moveTo(out.width / 2, 0);
      octx.lineTo(out.width / 2, out.height);
      octx.stroke();
      octx.beginPath();
      octx.moveTo(0, out.height / 2);
      octx.lineTo(out.width, out.height / 2);
      octx.stroke();
    }
    octx.drawImage(canvas, 0, 0);
    return out.toDataURL("image/png");
  }, [grid]);

  const sendToTutor = useCallback(() => {
    const dataUrl = exportPng();
    if (!dataUrl) return;
    onInsert(dataUrl);
    onOpenChange(false);
  }, [exportPng, onInsert, onOpenChange]);

  // Close text draft on Escape.
  useEffect(() => {
    if (!open || !textDraft) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setTextDraft(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, textDraft]);

  // Text draft input auto-focus.
  useEffect(() => {
    if (textDraft) textDraftRef.current?.focus();
  }, [textDraft]);

  return (
    <div className="flex h-full w-full flex-col bg-[var(--background)]">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-1.5 border-b border-[var(--border)]/60 bg-[var(--card)] px-3 py-2">
        <span className="mr-1 flex items-center gap-1.5 text-[12.5px] font-medium text-[var(--foreground)]">
          <PanelTop size={15} strokeWidth={1.8} className="text-[var(--primary)]" />
          {tr("白板", "Whiteboard")}
        </span>
        <div className="flex items-center gap-0.5 rounded-lg bg-[var(--muted)]/40 p-0.5">
          {TOOLS.map((td) => {
            const Icon = td.icon;
            return (
              <button
                key={td.id}
                type="button"
                onClick={() => setTool(td.id)}
                title={td.label}
                aria-label={td.label}
                className={`flex h-7 w-7 items-center justify-center rounded-md transition-colors ${
                  tool === td.id
                    ? "bg-[var(--card)] text-[var(--primary)] shadow-sm"
                    : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                }`}
              >
                <Icon size={15} strokeWidth={1.8} />
              </button>
            );
          })}
        </div>

        <div className="flex items-center gap-1.5 px-1">
          {COLORS.map((c) => (
            <button
              key={c}
              type="button"
              aria-label={tr("颜色", "Color")}
              onClick={() => setColor(c)}
              className={`h-5 w-5 rounded-full border transition-transform active:scale-90 ${
                color === c
                  ? "border-[var(--primary)] ring-2 ring-[var(--primary)]/30"
                  : "border-black/10"
              }`}
              style={{ backgroundColor: c }}
            />
          ))}
        </div>

        <div className="flex items-center gap-0.5 rounded-lg bg-[var(--muted)]/40 p-0.5">
          {SIZES.map((s) => (
            <button
              key={s.value}
              type="button"
              onClick={() => setSize(s.value)}
              className={`flex h-7 items-center rounded-md px-2 text-[11px] transition-colors ${
                size === s.value
                  ? "bg-[var(--card)] text-[var(--foreground)] shadow-sm"
                  : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
              }`}
            >
              {s.label}
            </button>
          ))}
        </div>

        <div className="ml-auto flex items-center gap-1">
          <ToolButton
            icon={Grid3x3}
            label={tr("网格", "Grid")}
            active={grid}
            onClick={() => setGrid((v) => !v)}
          />
          <ToolButton
            icon={Undo2}
            label={tr("撤销", "Undo")}
            disabled={undoCount === 0}
            onClick={undo}
          />
          <ToolButton
            icon={Redo2}
            label={tr("重做", "Redo")}
            disabled={redoCount === 0}
            onClick={redo}
          />
          <ToolButton
            icon={Trash2}
            label={tr("清空", "Clear")}
            disabled={!hasInk}
            onClick={clearBoard}
          />
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            aria-label={tr("关闭", "Close")}
            className="flex h-7 w-7 items-center justify-center rounded-lg text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)]/55 hover:text-[var(--foreground)]"
          >
            <X size={15} strokeWidth={1.9} />
          </button>
        </div>
      </div>

      {/* Canvas stage: CSS grid background, transparent canvas on top. */}
      <div ref={containerRef} className="relative flex min-h-0 flex-1 items-center justify-center overflow-auto bg-[var(--muted)]/30 p-4">
        <div
          className="relative overflow-hidden rounded-lg border border-[var(--border)]/60 shadow-[0_8px_30px_-12px_rgba(0,0,0,0.25)]"
          style={{
            width: "100%",
            maxWidth: `min(1100px, calc((100vh - 180px) * ${CANVAS_W} / ${CANVAS_H}))`,
            aspectRatio: `${CANVAS_W} / ${CANVAS_H}`,
            backgroundColor: "#ffffff",
            backgroundImage: grid
              ? `linear-gradient(#e2e8f0 1px, transparent 1px), linear-gradient(90deg, #e2e8f0 1px, transparent 1px)`
              : undefined,
            backgroundSize: grid ? "50px 50px" : undefined,
          }}
        >
          <canvas
            ref={canvasRef}
            width={CANVAS_W}
            height={CANVAS_H}
            onPointerDown={beginShape}
            onPointerMove={movePointer}
            onPointerUp={endPointer}
            onPointerLeave={endPointer}
            onPointerCancel={endPointer}
            className="block h-full w-full cursor-crosshair touch-none"
          />
          {textDraft && (
            <input
              ref={textDraftRef}
              value={textDraft.value}
              onChange={(e) =>
                setTextDraft({ ...textDraft, value: e.target.value })
              }
              onKeyDown={(e) => {
                if (e.key === "Enter") commitText();
              }}
              onBlur={commitText}
              placeholder={tr("输入文字，回车确认", "Type text, Enter to commit")}
              className="absolute z-10 min-w-[120px] rounded border border-[var(--primary)]/60 bg-white/95 px-2 py-1 text-[14px] text-[var(--foreground)] outline-none"
              style={{
                left: (textDraft.x / CANVAS_W) * 100 + "%",
                top: (textDraft.y / CANVAS_H) * 100 + "%",
              }}
            />
          )}
        </div>
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between gap-2 border-t border-[var(--border)]/60 bg-[var(--card)] px-3 py-2">
        <span className="text-[11px] text-[var(--muted-foreground)]">
          {tr(
            "自由演算与讲解画布：绘制后一键发给导师，导师可基于图形继续提问。",
            "Free-form working canvas: draw, then send to the tutor as an image.",
          )}
        </span>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => {
              const url = exportPng();
              if (url) {
                const a = document.createElement("a");
                a.href = url;
                a.download = `whiteboard-${Date.now()}.png`;
                a.click();
              }
            }}
            disabled={!hasInk}
            className="h-8 rounded-lg border border-[var(--border)]/60 px-3 text-[12.5px] font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--muted)]/40 disabled:opacity-40"
          >
            {tr("导出 PNG", "Export PNG")}
          </button>
          <button
            type="button"
            onClick={sendToTutor}
            disabled={!hasInk}
            className={`inline-flex h-8 items-center gap-1.5 rounded-lg px-3.5 text-[12.5px] font-medium transition-colors active:scale-95 disabled:cursor-not-allowed disabled:opacity-40 ${
              hasInk
                ? "bg-[var(--primary)] text-[var(--primary-foreground)] hover:bg-[var(--primary)]/90"
                : "bg-[var(--muted)] text-[var(--muted-foreground)]"
            }`}
          >
            <Send size={14} strokeWidth={2} />
            {tr("发送给导师", "Send to tutor")}
          </button>
        </div>
      </div>
    </div>
  );
}

function ToolButton({
  icon: Icon,
  label,
  active,
  disabled,
  onClick,
}: {
  icon: LucideIcon;
  label: string;
  active?: boolean;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={label}
      aria-label={label}
      className={`flex h-7 w-7 items-center justify-center rounded-lg transition-colors active:scale-90 disabled:cursor-not-allowed disabled:opacity-40 ${
        active
          ? "bg-[var(--primary)]/[0.1] text-[var(--primary)]"
          : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]/55 hover:text-[var(--foreground)]"
      }`}
    >
      <Icon size={15} strokeWidth={1.8} />
    </button>
  );
}
