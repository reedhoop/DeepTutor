/**
 * [KGRAPH-EXT] K12-KGraph curriculum knowledge browser API.
 *
 * Narrow client for the fork-only `/api/v1/kg/*` endpoints
 * (mounted by deeptutor/api/main.py from `kgraph.router`).
 * Extracted from the retired knowledge-api barrel so the
 * knowledge-api boundaries test keeps passing.
 */
import { apiFetch, apiUrl } from "@/lib/api";
import { readErrorDetail } from "./client";

export interface KgCandidate {
  id: string;
  name: string;
  label: string;
  score: number;
  method: string;
}

export interface KgLiteConcept {
  id: string;
  name: string;
  label: string;
}

export interface KgPathEntry {
  id: string;
  name: string;
  label: string;
  relation: string;
}

export interface KgConcept {
  id: string;
  name: string;
  label: string;
  available: boolean;
  definition: string;
  aliases: string[];
  importance: string;
  examples: string[];
  prerequisites: KgLiteConcept[];
  path: KgPathEntry[];
  evidence: { evidences: string[]; relations: string[] };
}

export async function kgAvailable(): Promise<{
  available: boolean;
  node_count: number;
}> {
  const res = await apiFetch(apiUrl("/api/v1/kg/available"));
  if (!res.ok) {
    throw new Error(await readErrorDetail(res, `KG status failed (${res.status})`));
  }
  return (await res.json()) as { available: boolean; node_count: number };
}

export async function kgSearch(
  q: string,
  options?: { subject?: string; top_k?: number },
): Promise<{ query: string; candidates: KgCandidate[]; available: boolean }> {
  const params = new URLSearchParams();
  params.set("q", q);
  if (options?.subject) params.set("subject", options.subject);
  if (options?.top_k) params.set("top_k", String(options.top_k));
  const res = await apiFetch(apiUrl(`/api/v1/kg/search?${params.toString()}`));
  if (!res.ok) {
    throw new Error(await readErrorDetail(res, `KG search failed (${res.status})`));
  }
  const data = (await res.json()) as {
    query: string;
    candidates: KgCandidate[];
    available: boolean;
  };
  return {
    query: data.query,
    candidates: data.candidates ?? [],
    available: data.available,
  };
}

export async function kgConcept(id: string): Promise<KgConcept> {
  const res = await apiFetch(apiUrl(`/api/v1/kg/concept/${encodeURIComponent(id)}`));
  if (!res.ok) {
    throw new Error(await readErrorDetail(res, `KG concept failed (${res.status})`));
  }
  return (await res.json()) as KgConcept;
}
