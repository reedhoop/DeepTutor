import { apiUrl, apiFetch } from "./api";

export interface TextbookSection {
  id: string;
  name: string;
}

export interface TextbookChapter {
  id: string;
  name: string;
  sections: TextbookSection[];
}

export interface TextbookBook {
  id: string;
  name: string;
  edition: string;
  chapters: TextbookChapter[];
}

export interface TextbookSubject {
  id: string;
  name: string;
  books: TextbookBook[];
}

export interface TextbookTree {
  subjects: TextbookSubject[];
}

/** One teachable objective that belongs to a chapter/section node. */
export interface KnowledgePointItem {
  id: string;
  name: string;
  label: string; // "Concept" | "Skill"
  type: string; // "concept" | "skill"
}

/** Full curriculum card for a single KGraph node (GET /api/v1/kg/concept/{id}). */
export interface KgConceptResult {
  id: string;
  name: string;
  label: string;
  available: boolean;
  definition: string;
  aliases: string[];
  importance: string;
  examples: unknown[];
  prerequisites: { id: string; name: string; label: string }[];
  knowledge_points: KnowledgePointItem[];
  path: unknown[];
  evidence: { evidences: string[]; relations: string[] };
}

async function request<T>(path: string): Promise<T> {
  const res = await apiFetch(apiUrl(`/api/v1/kgraph${path}`));
  if (!res.ok) {
    let detail = "";
    try {
      const data = await res.json();
      detail = data?.detail || "";
    } catch {
      /* ignore */
    }
    throw new Error(`textbook api ${path} → ${res.status}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

/** Load the full K12 curriculum tree (subject → book → chapter → section). */
export function fetchTextbookTree(): Promise<TextbookTree> {
  return request<TextbookTree>("/textbook-tree");
}

/**
 * Fetch a single KGraph node's curriculum card (incl. the teachable
 * ``knowledge_points`` that belong to it). Used by the textbook navigator to
 * show a chapter/section's real content in the preview pane.
 */
export async function fetchKgConcept(nodeId: string): Promise<KgConceptResult> {
  const res = await apiFetch(apiUrl(`/api/v1/kg/concept/${encodeURIComponent(nodeId)}`));
  if (!res.ok) {
    let detail = "";
    try {
      const data = await res.json();
      detail = data?.detail || "";
    } catch {
      /* ignore */
    }
    throw new Error(`kg concept ${nodeId} → ${res.status}: ${detail}`);
  }
  return res.json() as Promise<KgConceptResult>;
}
