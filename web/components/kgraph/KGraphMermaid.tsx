"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, Network, AlertTriangle } from "lucide-react";

import { apiFetch, apiUrl } from "@/lib/api";
import Mermaid from "@/components/Mermaid";

interface KGraphVizNode {
  id: string;
  name: string;
  kind?: string;
  bucket?: string;
}

interface KGraphVizEdge {
  from: string;
  to: string;
}

interface KGraphVizResult {
  available: boolean;
  mermaid?: string;
  nodes?: KGraphVizNode[];
  edges?: KGraphVizEdge[];
  mode?: string;
  center_id?: string | null;
  error?: string;
  reason?: string;
  note?: string;
}

type LoadState = "loading" | "ok" | "empty" | "error";

/**
 * Renders a KGraph subgraph as a Mermaid diagram (ER-1).
 *
 * Pass either ``nodeId`` (a single KGraph concept) or ``pathId`` (a mastery
 * path — its objectives are connected by prerequisite edges and coloured by
 * mastery). The component owns only view state; the graph is computed by
 * ``GET /api/v1/kg/visualize`` which calls the ``_local`` Mermaid builder.
 */
export function KGraphMermaid({
  nodeId,
  pathId,
  className = "",
}: {
  nodeId?: string;
  pathId?: string;
  className?: string;
}) {
  const { i18n } = useTranslation();
  const zh = i18n.language?.toLowerCase().startsWith("zh");
  const tr = (cn: string, en: string) => (zh ? cn : en);

  const [state, setState] = useState<LoadState>("loading");
  const [data, setData] = useState<KGraphVizResult | null>(null);

  useEffect(() => {
    if (!nodeId && !pathId) {
      setState("empty");
      return;
    }
    let cancelled = false;
    setState("loading");
    const params = new URLSearchParams();
    if (nodeId) params.set("node_id", nodeId);
    if (pathId) params.set("path_id", pathId);

    (async () => {
      try {
        const resp = await apiFetch(
          apiUrl(`/api/v1/kg/visualize?${params.toString()}`),
        );
        const json = (await resp.json()) as KGraphVizResult;
        if (cancelled) return;
        if (!resp.ok) {
          setData(json);
          setState("error");
          return;
        }
        if (!json.available || !json.mermaid) {
          setData(json);
          setState("empty");
          return;
        }
        setData(json);
        setState("ok");
      } catch (err) {
        if (cancelled) return;
        setData({
          available: false,
          reason: err instanceof Error ? err.message : String(err),
        });
        setState("error");
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [nodeId, pathId]);

  if (state === "loading") {
    return (
      <div
        className={`my-2 flex items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--muted)]/40 px-4 py-3 text-sm text-[var(--muted-foreground)] ${className}`}
      >
        <Loader2 className="h-4 w-4 animate-spin" />
        {tr("加载知识图谱…", "Loading knowledge graph…")}
      </div>
    );
  }

  if (state === "empty") {
    return (
      <div
        className={`my-2 rounded-lg border border-dashed border-[var(--border)] bg-[var(--muted)]/30 px-4 py-3 text-sm text-[var(--muted-foreground)] ${className}`}
      >
        <div className="flex items-center gap-2">
          <Network className="h-4 w-4 opacity-60" />
          {tr(
            "知识图谱暂不可用：未加载 K12-KGraph 数据集。",
            "Knowledge graph unavailable: K12-KGraph dataset is not loaded.",
          )}
        </div>
      </div>
    );
  }

  if (state === "error") {
    return (
      <div
        className={`my-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-600 ${className}`}
      >
        <div className="flex items-center gap-2">
          <AlertTriangle className="h-4 w-4" />
          {tr("知识图谱加载失败。", "Failed to load knowledge graph.")}
        </div>
        {data?.reason && (
          <p className="mt-1 text-xs text-red-500">{data.reason}</p>
        )}
      </div>
    );
  }

  return (
    <div className={className}>
      <Mermaid chart={data!.mermaid!} />
    </div>
  );
}

export default KGraphMermaid;
