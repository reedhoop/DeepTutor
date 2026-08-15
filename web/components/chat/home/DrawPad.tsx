"use client";

import i18n from "i18next";

import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  Eraser,
  Pencil,
  Redo2,
  Trash2,
  X,
  Check,
  type LucideIcon,
} from "lucide-react";

/** Chinese-first inline translation helper. Kept local (not routed through
 *  react-i18next) so the DrawPad UI does not require new keys in
 *  web/locales/{en,zh}/app.json and stays clear of the i18n parity gate. */
const tr = (zh: string, en: string) =>
  i18n.language?.toLowerCase().startsWith("zh") ? zh : en;

const COLORS = ["#111827", "#dc2626", "#2563eb", "#16a34a", "#d97706", "#7c3aed"];
const SIZES = [
  { label: tr("细", "Thin"), value: 2 },
  { label: tr("中", "Medium"), value: 4 },
  { label: tr("粗", "Thick"), value: 8 },
];

const CANVAS_W = 480;
const CANVAS_H = 300;
const MAX_UNDO = 25;

export interface DrawPadProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Called with a PNG data URL when the user clicks "插入对话". */
  onInsert: (dataUrl: string) => void;
}

export function DrawPad({ open, onOpenChange, onInsert }: DrawPadProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const drawingRef = useRef(false);
  const lastRef = useRef<{ x: number; y: number } | null>(null);
  const undoStackRef = useRef<ImageData[]>([]);
  const [color, setColor] = useState(COLORS[0]);
  const [size, setSize] = useState(SIZES[1].value);
  const [eraser, setEraser] = useState(false);
  const [undoVersion, setUndoVersion] = useState(0);
  const [dirty, setDirty] = useState(false);

  // Initialise the canvas with a white background once mounted/opened.
  const paintBackground = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
  }, []);

  useEffect(() => {
    if (open) {
      // Defer one frame so the canvas element exists and has layout.
      requestAnimationFrame(() => {
        paintBackground();
        undoStackRef.current = [];
        lastRef.current = null;
        drawingRef.current = false;
        setUndoVersion((v) => v + 1);
        setDirty(false);
      });
    }
  }, [open, paintBackground]);

  const snapshot = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    undoStackRef.current.push(
      ctx.getImageData(0, 0, canvas.width, canvas.height),
    );
    if (undoStackRef.current.length > MAX_UNDO) undoStackRef.current.shift();
  }, []);

  const pointFromEvent = useCallback((e: React.PointerEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current!;
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;
    return {
      x: (e.clientX - rect.left) * scaleX,
      y: (e.clientY - rect.top) * scaleY,
    };
  }, []);

  const startStroke = useCallback(
    (e: React.PointerEvent<HTMLCanvasElement>) => {
      const canvas = canvasRef.current;
      const ctx = canvas?.getContext("2d");
      if (!canvas || !ctx) return;
      // Snapshot the pre-stroke state so every stroke is individually undoable.
      snapshot();
      canvas.setPointerCapture(e.pointerId);
      drawingRef.current = true;
      const p = pointFromEvent(e);
      lastRef.current = p;
      // Draw a dot so a single tap registers.
      ctx.fillStyle = eraser ? "#ffffff" : color;
      ctx.beginPath();
      ctx.arc(p.x, p.y, eraser ? size * 2 : size / 2, 0, Math.PI * 2);
      ctx.fill();
      setDirty(true);
    },
    [snapshot, pointFromEvent, eraser, color, size],
  );

  const moveStroke = useCallback(
    (e: React.PointerEvent<HTMLCanvasElement>) => {
      if (!drawingRef.current) return;
      const canvas = canvasRef.current;
      const ctx = canvas?.getContext("2d");
      if (!canvas || !ctx || !lastRef.current) return;
      const p = pointFromEvent(e);
      ctx.strokeStyle = eraser ? "#ffffff" : color;
      ctx.lineWidth = eraser ? size * 4 : size;
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      ctx.beginPath();
      ctx.moveTo(lastRef.current.x, lastRef.current.y);
      ctx.lineTo(p.x, p.y);
      ctx.stroke();
      lastRef.current = p;
    },
    [pointFromEvent, eraser, color, size],
  );

  const endStroke = useCallback(
    (e: React.PointerEvent<HTMLCanvasElement>) => {
      if (!drawingRef.current) return;
      const canvas = canvasRef.current;
      canvas?.releasePointerCapture?.(e.pointerId);
      drawingRef.current = false;
      lastRef.current = null;
    },
    [],
  );

  // True when the canvas has any non-white pixel. `dirty` gates the
  // insert/clear buttons; recomputing it on undo keeps it correct after
  // "clear → undo restores ink" or "erase everything" edge cases.
  const isCanvasBlank = useCallback((): boolean => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return true;
    const { data } = ctx.getImageData(0, 0, canvas.width, canvas.height);
    for (let i = 0; i < data.length; i += 4) {
      if (data[i] !== 255 || data[i + 1] !== 255 || data[i + 2] !== 255) {
        return false;
      }
    }
    return true;
  }, []);

  const handleUndo = useCallback(() => {
    const stack = undoStackRef.current;
    if (stack.length === 0) return;
    const prev = stack.pop()!;
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    ctx.putImageData(prev, 0, 0);
    setUndoVersion((v) => v + 1);
    setDirty(!isCanvasBlank());
  }, [isCanvasBlank]);

  const handleClear = useCallback(() => {
    snapshot();
    paintBackground();
    setDirty(false);
    setUndoVersion((v) => v + 1);
  }, [paintBackground, snapshot]);

  const handleInsert = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas || !dirty) return;
    const dataUrl = canvas.toDataURL("image/png");
    onInsert(dataUrl);
    onOpenChange(false);
  }, [dirty, onInsert, onOpenChange]);

  const canUndo = undoStackRef.current.length > 0;

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="absolute bottom-full left-0 z-[60] mb-2 w-[min(520px,92vw)]"
          style={{ transformOrigin: "bottom left" }}
          initial={{ opacity: 0, y: 6, scale: 0.97 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 4, scale: 0.98 }}
          transition={{ duration: 0.16, ease: [0.16, 1, 0.3, 1] }}
          onKeyDown={(e) => {
            if (e.key === "Escape") onOpenChange(false);
          }}
        >
          <div className="overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--popover)] shadow-2xl backdrop-blur-md">
            <div className="flex items-center justify-between border-b border-[var(--border)]/60 px-3 py-2">
              <div className="flex items-center gap-2 text-[13px] font-medium text-[var(--foreground)]">
                <Pencil size={15} strokeWidth={1.8} className="text-[var(--primary)]" />
                {tr("画给我看 · 手绘画板", "Draw it for me")}
              </div>
              <button
                type="button"
                onClick={() => onOpenChange(false)}
                aria-label={tr("关闭画板", "Close drawing pad")}
                className="flex h-7 w-7 items-center justify-center rounded-lg text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)]/55 hover:text-[var(--foreground)]"
              >
                <X size={16} strokeWidth={1.9} />
              </button>
            </div>

            <div className="px-3 pb-3 pt-3">
              <div className="overflow-hidden rounded-xl border border-[var(--border)]/70 bg-white">
                <canvas
                  ref={canvasRef}
                  width={CANVAS_W}
                  height={CANVAS_H}
                  onPointerDown={startStroke}
                  onPointerMove={moveStroke}
                  onPointerUp={endStroke}
                  onPointerLeave={endStroke}
                  onPointerCancel={endStroke}
                  className="block w-full cursor-crosshair touch-none"
                  style={{ aspectRatio: `${CANVAS_W} / ${CANVAS_H}` }}
                />
              </div>

              <div className="mt-3 flex flex-wrap items-center gap-2">
                <div className="flex items-center gap-1.5">
                  {COLORS.map((c) => (
                    <button
                      key={c}
                      type="button"
                      aria-label={tr("选择颜色", "Pick color")}
                      onClick={() => {
                        setColor(c);
                        setEraser(false);
                      }}
                      className={`h-6 w-6 rounded-full border transition-transform active:scale-90 ${
                        !eraser && color === c
                          ? "border-[var(--primary)] ring-2 ring-[var(--primary)]/30"
                          : "border-black/10"
                      }`}
                      style={{ backgroundColor: c }}
                    />
                  ))}
                </div>

                <div className="flex items-center gap-1 rounded-lg bg-[var(--muted)]/40 p-0.5">
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

                <ToolButton
                  icon={Eraser}
                  label={tr("橡皮", "Eraser")}
                  active={eraser}
                  onClick={() => setEraser((v) => !v)}
                />
                <ToolButton
                  icon={Redo2}
                  label={tr("撤销", "Undo")}
                  disabled={!canUndo}
                  onClick={handleUndo}
                />
                <ToolButton
                  icon={Trash2}
                  label={tr("清空", "Clear")}
                  disabled={!dirty}
                  onClick={handleClear}
                />

                <button
                  type="button"
                  onClick={handleInsert}
                  disabled={!dirty}
                  className={`ml-auto inline-flex h-8 items-center gap-1.5 rounded-lg px-3 text-[13px] font-medium transition-colors active:scale-95 disabled:cursor-not-allowed disabled:opacity-40 ${
                    dirty
                      ? "bg-[var(--primary)] text-[var(--primary-foreground)] hover:bg-[var(--primary)]/90"
                      : "bg-[var(--muted)] text-[var(--muted-foreground)]"
                  }`}
                >
                  <Check size={15} strokeWidth={2} />
                  {tr("插入对话", "Insert into chat")}
                </button>
              </div>
              <p className="mt-2 text-[11px] leading-snug text-[var(--muted-foreground)]">
                {tr(
                  "手绘草图会作为图片发给导师，导师可基于图形继续提问。",
                  "Your sketch is sent to the tutor as an image so it can ask follow-up questions about it.",
                )}
              </p>
            </div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
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
      aria-label={label}
      title={label}
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
