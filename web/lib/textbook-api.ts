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
