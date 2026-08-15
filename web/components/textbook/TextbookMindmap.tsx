"use client";

import { useEffect, useRef } from "react";
import type { Markmap } from "markmap-view";
import type { TextbookTree } from "@/lib/textbook-api";

/** "all" shows the whole curriculum at subject → book level (bird's-eye);
 *  a concrete subject id drills down to book → chapter → section. */
export type MindmapScope = "all" | string;

/**
 * Convert the K12 curriculum tree into a nested Markdown outline that markmap
 * can render as a mind map.
 *
 *  - scope "all":   `# 学科` → `## 书（版）`          (overview, ~9 nodes)
 *  - scope subject: `# 学科` → `## 书` → `### 章` → `- 节`  (full drill-down)
 */
function treeToMarkdown(tree: TextbookTree, scope: MindmapScope): string {
  const subjects =
    scope === "all"
      ? tree.subjects
      : tree.subjects.filter((s) => s.id === scope);

  const lines: string[] = [];
  for (const subject of subjects) {
    lines.push(`# ${subject.name}`);
    for (const book of subject.books) {
      const bookLabel = book.edition ? `${book.name}（${book.edition}）` : book.name;
      lines.push(`## ${bookLabel}`);
      // Bird's-eye view stops at the book level to keep the map readable.
      if (scope === "all") continue;
      for (const chapter of book.chapters) {
        lines.push(`### ${chapter.name}`);
        for (const section of chapter.sections) {
          lines.push(`- ${section.name}`);
        }
      }
    }
  }
  return lines.join("\n");
}

/**
 * Renders the textbook curriculum as an interactive, zoomable mind map using
 * markmap. Pure presentational component — it only consumes the tree that the
 * textbook page already fetched; no new API call, no backend dependency.
 *
 * markmap touches `document`/`window`, so its modules are dynamically imported
 * inside an effect (never at module top-level) to stay SSR-safe.
 */
export default function TextbookMindmap({
  tree,
  scope = "all",
}: {
  tree: TextbookTree;
  scope?: MindmapScope;
}) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const mmRef = useRef<Markmap | null>(null);
  const roRef = useRef<ResizeObserver | null>(null);
  const markdown = treeToMarkdown(tree, scope);

  // d3-zoom (used internally by markmap) reads svg.width.baseVal.value inside
  // its defaultExtent. A responsive SVG sized only via CSS (w-full/h-full, i.e.
  // width:100%) has no numeric width attribute, so reading .value throws
  // "Could not resolve relative length" — and markmap's fit() triggers exactly
  // that path. Give the SVG explicit numeric width/height attributes so the
  // value resolves; CSS keeps the element responsive.
  const syncSize = () => {
    const svg = svgRef.current;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    if (rect.width && rect.height) {
      svg.setAttribute("width", String(Math.round(rect.width)));
      svg.setAttribute("height", String(Math.round(rect.height)));
    }
  };

  // Create the markmap instance once; reuse it across data updates.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [{ Transformer }, { Markmap }] = await Promise.all([
        import("markmap-lib"),
        import("markmap-view"),
      ]);
      if (cancelled || !svgRef.current || mmRef.current) return;
      // Set explicit numeric width/height BEFORE markmap attaches d3-zoom,
      // otherwise its first fit() throws "Could not resolve relative length".
      syncSize();
      mmRef.current = Markmap.create(svgRef.current, {
        autoFit: true,
        duration: 300,
        paddingX: 14,
        spacingVertical: 10,
        spacingHorizontal: 130,
        fitRatio: 0.92,
      });
      // Keep the numeric extent correct as the container resizes.
      const ro = new ResizeObserver(syncSize);
      ro.observe(svgRef.current);
      roRef.current = ro;
    })();
    return () => {
      cancelled = true;
      roRef.current?.disconnect();
      roRef.current = null;
    };
  }, []);

  // Push new data whenever the tree or scope changes.
  useEffect(() => {
    let active = true;
    (async () => {
      const { Transformer } = await import("markmap-lib");
      if (!active || !mmRef.current) return;
      const { root } = new Transformer().transform(markdown);
      mmRef.current.setData(root);
      mmRef.current.fit();
    })();
    return () => {
      active = false;
    };
  }, [markdown]);

  // Destroy the instance on unmount.
  useEffect(() => {
    return () => {
      try {
        mmRef.current?.destroy?.();
      } catch {
        /* ignore */
      }
      mmRef.current = null;
    };
  }, []);

  return <svg ref={svgRef} className="h-full w-full" />;
}
