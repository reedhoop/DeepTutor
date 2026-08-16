"""Prewarm K12-KGraph node_vectors.json for the prod instance.

Builds the semantic vector cache for all K12-KGraph nodes (first semantic
search would otherwise trigger this synchronously inside a chat turn and
block the response for 10-30 minutes). Run this once in a normal terminal:

  D:\\00_aiStudy\\DeepTutor-prod\\.venv\\Scripts\\python.exe scripts\\prewarm_node_vectors.py

It reads the same env (K12_KGRAPH_DATA_DIR / K12_KGRAPH_CACHE_DIR) and the same
embedding catalog as the backend service, so the cache lands exactly where the
service expects it. When it prints DONE, the real node_vectors.json overwrites
the empty placeholder and semantic KG search starts working.
"""
import asyncio
import os
import sys
import time

# Mirror the backend service env (install_prod_service.py sets these).
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("K12_KGRAPH_DATA_DIR", os.path.join(REPO, "K12-KGraph-data"))
os.environ.setdefault(
    "K12_KGRAPH_CACHE_DIR",
    os.path.join(REPO, "data", "knowledge_bases", "k12_kg"),
)
# Make the app resolve data/settings relative to this repo.
os.environ.setdefault("DEEPTUTOR_HOME", REPO)


async def main() -> int:
    from deeptutor.services.kgraph import get_kg

    kg = get_kg()
    print(f"[prewarm] KG loaded; embedding all semantic nodes ...", flush=True)
    t0 = time.time()
    vecs = await kg._ensure_vectors()
    print(f"[prewarm] DONE: {len(vecs)} vectors in {time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
