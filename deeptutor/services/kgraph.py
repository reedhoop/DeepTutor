"""K12-KGraph curriculum knowledge index + query (DeepTutor integration).

Loads the cloned K12-KGraph dataset (``global_KG`` topology + subject-specific
definitions/evidence) and builds in-memory indexes that back the
``curriculum_knowledge`` tool.

Pure Python / JSON — no torch / datasets. The optional semantic fallback uses
the already-configured free SiliconFlow ``BAAI/bge-m3`` embedding (see
``model_catalog.json``); node-name vectors are computed once and cached on disk
(under ``data/``, which is gitignored and rebuildable).
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
def _default_data_dir() -> Path:
    # deeptutor/services/kgraph.py -> parents[2] == DeepTutor ; .parent == 00_aiStudy
    return Path(__file__).resolve().parents[2].parent / "K12-KGraph-data"


def _default_cache_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "knowledge_bases" / "k12_kg"


DATA_DIR = Path(os.environ.get("K12_KGRAPH_DATA_DIR", str(_default_data_dir()))).resolve()
CACHE_DIR = Path(
    os.environ.get("K12_KGRAPH_CACHE_DIR", str(_default_cache_dir()))
).resolve()
VECTOR_CACHE = CACHE_DIR / "node_vectors.json"

# Node labels whose text carries real semantic signal. Structural nodes
# (Book/Chapter/Section) only have a short name and would pollute kNN, so we
# skip them when building/loading the embedding index (P2-1).
EMBED_LABELS = frozenset({"Concept", "Skill", "Exercise", "Experiment"})

# Edge types used for traversal / teaching paths.
PREREQ = "prerequisites_for"
IS_PART_OF = "is_part_of"

# Teachable labels whose nodes are mastery objectives. Mirrors
# ``deeptutor.capabilities.mastery.kgraph_bridge.TEACHABLE`` so the textbook
# navigator's chapter preview shows exactly the objectives the mastery path
# (built by ``section_to_module``) will contain.
TEACHABLE = frozenset({"Concept", "Skill"})

_LABEL_TO_TYPE: dict[str, str] = {
    "Concept": "concept",
    "Skill": "skill",
}

# --------------------------------------------------------------------------- #
# Normalisation + helpers
# --------------------------------------------------------------------------- #
def _norm(s: str) -> str:
    """Light normalisation for lexical matching (strip whitespace, case)."""
    s = str(s).strip().lower()
    s = re.sub(r"\s+", "", s)
    return s


def _normalise_evidence(v: Any) -> str:
    """Normalise an edge's evidence/relations value to a display string.

    The value is usually a plain string, but is occasionally a dict of the
    form ``{"text": "...", "page": "..."}``. Accept both shapes.
    """
    if not v:
        return ""
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, dict):
        text = str(v.get("text") or "").strip()
        page = str(v.get("page") or "").strip()
        if text and page:
            return f"{text}（{page}）"
        return text or page
    return str(v).strip()


def is_confident(cands: list[dict[str, Any]]) -> bool:
    """Strategy-B confidence gate — SINGLE SOURCE OF TRUTH.

    Shared by the on-demand ``curriculum_knowledge`` tool and the passive
    course-KB seed so they never disagree about what counts as a confident
    match. Do NOT copy this logic elsewhere — import ``is_confident``.

    A match is confident when:
      * it is an exact (name/alias) hit, OR
      * it is the sole candidate with score >= 0.7, OR
      * the top candidate scores >= 0.8 AND leads the runner-up by >= 0.12
        (a clear winner, not a near-tie that would mislead the tutor).
    """
    if not cands:
        return False
    top = cands[0]
    if top.get("method") == "exact":
        return True
    if len(cands) == 1:
        return (top.get("score") or 0.0) >= 0.7
    gap = (top.get("score") or 0.0) - (cands[1].get("score") or 0.0)
    return (top.get("score") or 0.0) >= 0.8 and gap >= 0.12


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


# Subject is encoded in the node id prefix (math_/physics_/chemistry_/biology_).
_SUBJECT_PREFIXES = ("math", "physics", "chemistry", "biology")


def _subject_of_id(nid: str) -> str:
    for s in _SUBJECT_PREFIXES:
        if nid.startswith(s + "_"):
            return s
    return ""


# Grade-level encoding in node IDs:  math_8b_rjb_cpt11
#   → subject=math, grade=8(八年级), semester=b(下册)
_GRADE_NUM_CN = {
    "1": "一年级", "2": "二年级", "3": "三年级",
    "4": "四年级", "5": "五年级", "6": "六年级",
    "7": "七年级", "8": "八年级", "9": "九年级",
}
_SEMESTER_CN = {"a": "上册", "b": "下册"}
_ID_GRADE_RE: re.Pattern | None = None


def _get_id_grade_re() -> re.Pattern:
    global _ID_GRADE_RE
    if _ID_GRADE_RE is None:
        prefixes = "|".join(_SUBJECT_PREFIXES)
        _ID_GRADE_RE = re.compile(rf"^({prefixes})_(\d)([ab])_", re.IGNORECASE)
    return _ID_GRADE_RE


def grade_info_of_id(nid: str) -> dict[str, str]:
    """Parse grade/semester from a KGraph node ID.

    Returns a dict with keys ``grade`` (e.g. ``"八年级"``),
    ``semester`` (e.g. ``"下册"``), ``grade_semester`` (e.g. ``"八年级下册"``).
    Returns all-empty dict when the ID does not match the expected pattern.
    """
    m = _get_id_grade_re().match(nid)
    if not m:
        return {}
    g_num, sem = m.group(2), m.group(3).lower()
    grade_cn = _GRADE_NUM_CN.get(g_num, f"{g_num}年级")
    sem_cn = _SEMESTER_CN.get(sem, "")
    return {
        "grade": grade_cn,
        "semester": sem_cn,
        "grade_semester": f"{grade_cn}{sem_cn}" if sem_cn else grade_cn,
    }


# --------------------------------------------------------------------------- #
# Index
# --------------------------------------------------------------------------- #
class KGIndex:
    """In-memory index over the K12-KGraph dataset.

    Effective merged-node schema (the in-memory ``nodes[id]`` dict):

        {
          "id": "math_8b_rjb_cpt11",          # id prefix encodes subject
          "label": "Concept" | "Skill" | "Exercise" | "Experiment"
                   | "Section" | "Chapter" | "Book",
          "name": "勾股定理",
          "properties": {                      # merged from subject_specific_KG
              "definition": "...",            # Concept only; Skill uses "description"
              "description": "...",           # Skill only (P0-2 fallback)
              "aliases": ["毕达哥拉斯定理"],    # ~11% coverage (P0-3)
              "importance": "掌握",
              "examples": ["..."],
              # Exercise-only: stem / answer / analysis / difficulty / type (P2-1)
          },
          # evidence/relations are EDGE attributes, NOT node properties (P0-1):
          # aggregated in load() from subject edges into _node_evidence /
          # _node_relations, keyed by node id, exposed via evidence_data().
          # subject is DERIVED from the id prefix via _subject_of_id() (P1-3).
        }

    Edges: global_KG edges give the full topology (23,278, incl. tests_concept
    / leads_to with no evidence); subject_specific_KG edges (22,471) are a
    *property-bearing subset* of the global edges. load() merges BOTH — global
    first for topological completeness, then subject edges for evidence/relations
    and richer node properties (P1-2). Evidence is joined by (source, target,
    type) implicitly because both edge sets share those keys.
    """

    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, Any]] = {}  # id -> merged node
        self.name_index: dict[str, str] = {}  # norm_term -> id
        self.terms: list[tuple[str, str]] = []  # (norm_term, id) for scan
        self.adj: dict[str, dict[str, list[str]]] = defaultdict(
            lambda: defaultdict(list)
        )  # type -> source -> [target]
        self.adj_rev: dict[str, dict[str, list[str]]] = defaultdict(
            lambda: defaultdict(list)
        )
        self._vectors: dict[str, list[float]] | None = None
        # P0-1 fix: aggregated teaching evidence / relations, sourced from
        # subject-edge properties (evidence is an EDGE attribute, not a node
        # attribute). Keyed by node id; populated in load().
        self._node_evidence: dict[str, list[str]] = {}
        self._node_relations: dict[str, list[str]] = {}

    # -- loading ---------------------------------------------------------- #
    def load(self) -> "KGIndex":
        g_dir = DATA_DIR / "K12-KGraph" / "global_KG"
        with open(g_dir / "nodes.json", encoding="utf-8") as f:
            nodes = json.load(f)
        with open(g_dir / "edges.json", encoding="utf-8") as f:
            edges = json.load(f)

        for n in nodes:
            nid = n.get("id")
            if not nid:
                continue
            self.nodes[nid] = {
                "id": nid,
                "label": n.get("label", ""),
                "name": n.get("name", ""),
                "properties": {},
            }

        for e in edges:
            t, s, tg = e.get("type"), e.get("source"), e.get("target")
            if not (t and s and tg):
                continue
            self.adj[t][s].append(tg)
            self.adj_rev[t][tg].append(s)

        sp_dir = DATA_DIR / "K12-KGraph" / "subject_specific_KG"
        if sp_dir.exists():
            for f in sorted(sp_dir.glob("*.json")):
                with open(f, encoding="utf-8") as fh:
                    data = json.load(fh)
                subject_nodes = data.get("nodes") if isinstance(data, dict) else data
                for n in subject_nodes or []:
                    if not isinstance(n, dict):
                        continue
                    nid = n.get("id")
                    if not nid:
                        continue
                    props = n.get("properties", {}) or {}
                    if nid in self.nodes:
                        self.nodes[nid]["properties"] = props
                        # prefer the subject file's richer name if present
                        if n.get("name"):
                            self.nodes[nid]["name"] = n["name"]
                    else:
                        self.nodes[nid] = {
                            "id": nid,
                            "label": n.get("label", ""),
                            "name": n.get("name", ""),
                            "properties": props,
                        }

                # Merge subject-file EDGES — they carry the rich curriculum
                # topology (is_a / prerequisites_for / appears_in / relates_to / …)
                # and were previously dropped on load, leaving the graph sparse.
                for e in (data.get("edges") if isinstance(data, dict) else []) or []:
                    et, es, etg = e.get("type"), e.get("source"), e.get("target")
                    if not (et and es and etg):
                        continue
                    # P1-2: subject edges may duplicate global edges — dedup so
                    # adjacency lists stay unique (evidence aggregation above is
                    # independent of this and still runs for every edge).
                    if etg not in self.adj[et][es]:
                        self.adj[et][es].append(etg)
                    if es not in self.adj_rev[et][etg]:
                        self.adj_rev[et][etg].append(es)
                    # P0-1 fix: evidence/relations live on EDGES (subject files),
                    # not nodes. Aggregate every evidence/relation from edges
                    # touching a node so evidence_data() can return it. The
                    # value is usually a string, but occasionally a dict of the
                    # form {"text": "...", "page": "..."} — normalise both.
                    eprops = e.get("properties") or {}
                    ev = _normalise_evidence(eprops.get("evidence"))
                    rel = _normalise_evidence(eprops.get("relations"))
                    if ev or rel:
                        for ref in (es, etg):
                            if ev:
                                bucket = self._node_evidence.setdefault(ref, [])
                                if ev not in bucket:
                                    bucket.append(ev)
                            if rel:
                                bucket = self._node_relations.setdefault(ref, [])
                                if rel not in bucket:
                                    bucket.append(rel)
                    # Edges may reference nodes absent from the node list — seed
                    # them from the edge's source_name/target_name so traversal
                    # and name matching still resolve.
                    for ref, rname in (
                        (es, e.get("source_name")),
                        (etg, e.get("target_name")),
                    ):
                        if ref not in self.nodes:
                            self.nodes[ref] = {
                                "id": ref,
                                "label": "",
                                "name": rname or "",
                                "properties": {},
                            }

        for nid, n in self.nodes.items():
            name = n.get("name", "")
            if name:
                self._add_term(name, nid)
            for al in n.get("properties", {}).get("aliases") or []:
                if al:
                    self._add_term(al, nid)

        logger.info(
            "K12-KGraph index loaded: %d nodes, %d search terms",
            len(self.nodes),
            len(self.terms),
        )
        return self

    def _add_term(self, term: str, nid: str) -> None:
        nt = _norm(term)
        if nt and nt not in self.name_index:
            self.name_index[nt] = nid
        if nt:
            self.terms.append((nt, nid))

    # -- resolution (matching strategy B) ---------------------------------- #
    async def resolve(
        self,
        concept: str,
        top_k: int = 5,
        subject: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return ranked candidate dicts: {id, name, score, method}.

        If ``subject`` is given (one of math/physics/chemistry/biology), only
        candidates whose node id carries that subject prefix are kept (P1-3) —
        disambiguates multi-meaning terms such as 函数 across subjects.
        """
        q = _norm(concept)
        if not q:
            return []
        # Cache the *static* exact + substring + fuzzy scan only. KGIndex.terms is
        # a process-wide immutable singleton, so repeated concepts in a chat turn
        # skip the full O(N) traversal. The semantic fallback is intentionally
        # NOT cached: it depends on the external embedding endpoint / vector
        # availability, which can change between calls (and must stay live for
        # tests that disable it). Subject filtering stays out of the cache key.
        cache = self.__dict__.setdefault("_resolve_cache", {})
        key = (q, top_k)
        if key not in cache:
            if len(cache) >= 4096:  # bound memory: evict before inserting
                cache.clear()
            cache[key] = self._match_static(q, top_k)
        ranked = cache[key]
        if ranked:
            return self._filter_subject(ranked, subject)
        return self._filter_subject(await self._semantic(q, top_k), subject)

    def _match_static(self, q: str, top_k: int) -> list[dict[str, Any]]:
        """Exact + substring + fuzzy ranking (no embedding). Cached by ``resolve``."""
        cands: dict[str, tuple[str, float]] = {}

        # 1) exact normalised match (names + aliases)
        if q in self.name_index:
            cands[self.name_index[q]] = ("exact", 1.0)

        # 2) substring (both directions)
        for term, nid in self.terms:
            if not term or len(term) < 2:
                continue
            if q in term:
                sc = 0.85
            elif term in q:
                # term is a fragment of the query — only meaningful when the
                # query is (almost) all about this term, otherwise it's a stray
                # substring inside a longer unrelated query (e.g. "导体" inside
                # "量子纠缠超导体xyz"). Require strong overlap before accepting.
                ratio = len(term) / len(q)
                if ratio < 0.5:
                    continue
                sc = 0.7
            else:
                continue
            if nid not in cands or sc > cands[nid][1]:
                cands[nid] = ("substring", sc)
        if cands:
            return self._rank(cands, top_k)

        # 3) fuzzy (edit-distance ratio)
        for term, nid in self.terms:
            if not term:
                continue
            r = SequenceMatcher(None, q, term).ratio()
            if r >= 0.55:
                if nid not in cands or r > cands[nid][1]:
                    cands[nid] = ("fuzzy", r)
        if cands:
            return self._rank(cands, top_k)

        # 4) static miss → caller falls back to embedding-based semantic search
        return []

    @staticmethod
    def _filter_subject(
        cands: list[dict[str, Any]], subject: str | None
    ) -> list[dict[str, Any]]:
        if not subject:
            return cands
        return [c for c in cands if _subject_of_id(c["id"]) == subject]

    def _rank(
        self, cands: dict[str, tuple[str, float]], top_k: int
    ) -> list[dict[str, Any]]:
        items = sorted(cands.items(), key=lambda kv: -kv[1][1])
        out: list[dict[str, Any]] = []
        for nid, (method, score) in items[:top_k]:
            out.append(
                {
                    "id": nid,
                    "name": self.nodes.get(nid, {}).get("name", ""),
                    "score": score,
                    "method": method,
                }
            )
        return out

    # -- semantic fallback ------------------------------------------------ #
    def _vector_matrix(self) -> "tuple[list[str], Any] | None":
        """Cached row-normalized node-vector matrix for fast cosine search.

        Returns ``None`` if vectors are not loaded or cannot be stacked into a
        dense matrix (e.g. ragged dimensions), signalling the caller to fall
        back to the scalar ``_cosine`` path.
        """
        vecs = self._vectors
        if vecs is None:
            return None
        if getattr(self, "_vec_cache_ref", None) is vecs:
            return self._vec_ids, self._vec_matrix
        try:
            import numpy as np

            ids = list(vecs.keys())
            M = np.asarray(list(vecs.values()), dtype=np.float32)
            if M.ndim != 2:
                return None
            norms = np.linalg.norm(M, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            Mn = M / norms
        except Exception:  # noqa: BLE001 - ragged / non-numeric vectors
            return None
        self._vec_ids = ids
        self._vec_matrix = Mn
        self._vec_cache_ref = vecs
        return ids, Mn

    async def _semantic(self, q: str, top_k: int) -> list[dict[str, Any]]:
        vecs = await self._ensure_vectors()
        if not vecs:
            logger.warning(
                "KGraph semantic search skipped: node vectors not loaded "
                "(is K12_KGRAPH_DATA_DIR set and the vector cache built?)"
            )
            return []
        qv = await self._embed([q])
        if not qv:
            logger.warning(
                "KGraph semantic search skipped: embedding unavailable "
                "(is the SiliconFlow bge-m3 endpoint configured?)"
            )
            return []
        qv = qv[0]

        SEMANTIC_MIN = 0.40  # reject pure-noise matches
        # Fast path: one matrix-vector product over the whole KGraph cache.
        matrix = self._vector_matrix()
        if matrix is not None:
            ids, Mn = matrix
            try:
                import numpy as np

                qn = np.asarray(qv, dtype=np.float32)
                qn = qn / (np.linalg.norm(qn) + 1e-12)
                sims = Mn @ qn  # Mn is row-normalized → dot == cosine
                idx = np.where(sims >= SEMANTIC_MIN)[0]
                if idx.size:
                    order = idx[np.argsort(-sims[idx])][:top_k]
                    return [
                        {
                            "id": ids[int(i)],
                            "name": self.nodes.get(ids[int(i)], {}).get("name", ""),
                            "score": float(sims[i]),
                            "method": "semantic",
                        }
                        for i in order
                    ]
            except Exception:  # noqa: BLE001 - numpy path failed; use scalar fallback
                logger.warning("semantic numpy path failed, falling back to scalar")

        # Scalar fallback (robustness / no-numpy environments).
        scored: list[tuple[float, str]] = []
        for nid, v in vecs.items():
            sc = _cosine(qv, v)
            if sc >= SEMANTIC_MIN:
                scored.append((sc, nid))
        if not scored:
            return []
        scored.sort(reverse=True)
        out: list[dict[str, Any]] = []
        for sc, nid in scored[:top_k]:
            out.append(
                {
                    "id": nid,
                    "name": self.nodes.get(nid, {}).get("name", ""),
                    "score": sc,
                    "method": "semantic",
                }
            )
        return out

    async def _ensure_vectors(self) -> dict[str, list[float]]:
        if self._vectors is not None:
            return self._vectors
        if VECTOR_CACHE.exists():
            try:
                with open(VECTOR_CACHE, encoding="utf-8") as f:
                    raw = json.load(f)
                # P2-1: keep only vectors for labels with real semantic signal;
                # structural nodes (Book/Chapter/Section) would pollute kNN.
                self._vectors = {
                    k: v for k, v in raw.items()
                    if self.nodes.get(k, {}).get("label") in EMBED_LABELS
                }
                logger.info("loaded %d node vectors from cache", len(self._vectors))
                return self._vectors
            except Exception as exc:  # noqa: BLE001
                logger.warning("node vector cache load failed: %s", exc)
        self._vectors = await self._build_vectors()
        return self._vectors

    async def _build_vectors(self) -> dict[str, list[float]]:
        from deeptutor.services.embedding import (
            get_embedding_client,
            get_embedding_config,
        )

        cfg = get_embedding_config()
        client = get_embedding_client(cfg)
        ids = [i for i in self.nodes if self.nodes[i].get("label") in EMBED_LABELS]
        # Embed name + a definition snippet: the definition often restates the
        # concept literally (e.g. 勾股定理's definition contains "a²+b²=c²"),
        # which makes semantic matching far more discriminative than name-only.
        texts = [
            f"{self.nodes[i].get('name', '')}：{(self.nodes[i].get('properties', {}).get('definition') or '')[:120]}"
            or i
            for i in ids
        ]
        vecs: dict[str, list[float]] = {}
        batch = 64
        for i in range(0, len(texts), batch):
            chunk = texts[i : i + batch]
            v = await client.embed(chunk)
            for j, vid in enumerate(ids[i : i + batch]):
                vecs[vid] = v[j]
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with open(VECTOR_CACHE, "w", encoding="utf-8") as f:
            json.dump(vecs, f)
        logger.info("built & cached %d node vectors", len(vecs))
        return vecs

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        from deeptutor.services.embedding import (
            get_embedding_client,
            get_embedding_config,
        )

        cfg = get_embedding_config()
        client = get_embedding_client(cfg)
        return await client.embed(texts)

    # -- structured queries ----------------------------------------------- #
    def get_node(self, nid: str) -> dict[str, Any] | None:
        return self.nodes.get(nid)

    def definition_data(self, nid: str) -> dict[str, Any]:
        n = self.nodes.get(nid, {})
        p = n.get("properties", {})
        # P0-2 fix: Skill nodes carry `description`, not `definition`.
        definition = p.get("definition") or ""
        if not definition and n.get("label") == "Skill":
            definition = p.get("description") or ""
        return {
            "id": nid,
            "name": n.get("name", ""),
            "label": n.get("label", ""),
            "definition": definition,
            "aliases": p.get("aliases") or [],
            "importance": p.get("importance", ""),
            "examples": p.get("examples") or [],
        }

    def prerequisites_data(self, nid: str, levels: int = 1) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        cur = [nid]
        for _ in range(levels):
            nxt: list[str] = []
            for c in cur:
                for p in self.adj_rev[PREREQ].get(c, []):
                    if p in seen:
                        continue
                    seen.add(p)
                    out.append(self.definition_data(p))
                    nxt.append(p)
            cur = nxt
        return out

    def path_data(self, nid: str) -> list[dict[str, Any]]:
        """Curriculum location of a concept.

        Primary signal is ``appears_in`` (Concept/Skill → Section/Chapter node),
        which is far denser (10k+ edges) than ``is_part_of``. We also walk any
        upward ``is_part_of`` chain from the concept itself. Returns ordered
        breadcrumb entries, each tagged with the relation that produced it.
        """
        out: list[dict[str, Any]] = []
        seen: set[str] = set()

        # 1) Sections / chapters the concept appears_in.
        for sid in self.adj.get("appears_in", {}).get(nid, []):
            if sid in seen:
                continue
            seen.add(sid)
            n = self.nodes.get(sid)
            if n:
                out.append(
                    {
                        "id": sid,
                        "name": n.get("name", ""),
                        "label": n.get("label", ""),
                        "relation": "appears_in",
                    }
                )

        # 2) Upward is_part_of chain from the concept (Concept → Chapter → Book).
        cur = nid
        chain_seen: set[str] = set()
        while cur and cur not in chain_seen:
            chain_seen.add(cur)
            parents = self.adj_rev.get(IS_PART_OF, {}).get(cur, [])
            if not parents:
                break
            cur = parents[0]
            if cur in seen:
                continue
            seen.add(cur)
            n = self.nodes.get(cur)
            if n:
                out.append(
                    {
                        "id": cur,
                        "name": n.get("name", ""),
                        "label": n.get("label", ""),
                        "relation": "is_part_of",
                    }
                )
        return out

    def knowledge_points_data(self, nid: str) -> list[dict[str, Any]]:
        """Teachable knowledge points that belong to ``nid``.

        A knowledge point belongs to ``nid`` when a ``Concept``/``Skill`` node
        has an ``appears_in`` or ``is_part_of`` edge pointing *to* ``nid``. This
        is the same collection rule used by
        :func:`deeptutor.capabilities.mastery.kgraph_bridge.section_to_module`,
        so a chapter/section preview shows exactly the objectives the mastery
        path will contain. Returns them ordered by id for stable rendering.
        """
        kids_set = set(self.adj_rev.get("appears_in", {}).get(nid, []))
        kids_set |= set(self.adj_rev.get("is_part_of", {}).get(nid, []))
        out: list[dict[str, Any]] = []
        for k in sorted(kids_set):
            node = self.get_node(k)
            if not node:
                continue
            label = node.get("label", "")
            if label not in TEACHABLE:
                continue
            out.append(
                {
                    "id": k,
                    "name": node.get("name", k),
                    "label": label,
                    "type": _LABEL_TO_TYPE.get(label, "concept"),
                }
            )
        return out

    def evidence_data(self, nid: str) -> dict[str, Any]:
        """Aggregated teaching evidence for a concept (P0-1 fix).

        Evidence is NOT a node property — it lives on the subject-graph EDGES
        (``properties.evidence`` / ``properties.relations``). ``load()``
        aggregates every evidence/relation string from edges touching this node
        into ``_node_evidence`` / ``_node_relations``. Returns both the joined
        string (``evidence``) and the raw lists (``evidences`` / ``relations``)
        so callers can render either way.
        """
        n = self.nodes.get(nid, {})
        evidences = self._node_evidence.get(nid, [])
        relations = self._node_relations.get(nid, [])
        return {
            "id": nid,
            "name": n.get("name", ""),
            "evidence": "\n".join(evidences),
            "evidences": evidences,
            "relations": relations,
        }


_kg: KGIndex | None = None


def get_kg() -> KGIndex:
    """Lazily load + return the singleton index."""
    global _kg
    if _kg is None:
        _kg = KGIndex().load()
    return _kg


def is_available() -> bool:
    """True when the cloned K12-KGraph dataset is present on disk.

    Used by the chat/question pipelines to decide whether to auto-mount the
    ``curriculum_knowledge`` tool — avoids mounting a tool whose backing data
    is missing.
    """
    return (DATA_DIR / "K12-KGraph").is_dir()
