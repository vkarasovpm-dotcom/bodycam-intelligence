"""SENTINEL Retrieval Agent — semantic rule retrieval via sentence-transformers + FAISS.

Indexes all rules from case_law/police_*.json. For each query, returns top-K
most semantically similar rules with cosine similarity scores.

Index strategy:
  - One FAISS IndexFlatIP (inner product on L2-normalized embeddings = cosine similarity)
    per region (us, eu, it). Italy index includes EU rules (extends).
  - Embeddings precomputed via tools/build_indexes.py and cached to disk.
  - Lazy load on first query; subsequent queries hit warm index.

Model:
  - sentence-transformers/all-MiniLM-L6-v2 (384-dim, ~90MB, ~50ms/encode on CPU)
  - Quality is sufficient for legal triage (not for full legal research).

Usage:
  agent = RetrievalAgent()
  hits = agent.search("officer slapped handcuffed suspect", region="eu", top_k=5)
  # hits is list[RuleHit] with .rule_id, .score, .title, .summary, .subject, ...
"""
from __future__ import annotations
import json
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

# Repository root (parent of agents/)
REPO_ROOT = Path(__file__).resolve().parent.parent
CASE_LAW_DIR = REPO_ROOT / "case_law"
INDEX_DIR = CASE_LAW_DIR / "indexes"

EMBED_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
EMBED_DIM = 384


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class RuleHit:
    rule_id: str
    score: float           # cosine similarity, 0..1
    title: str
    summary: str
    source: str
    severity: str
    subject: str           # officer | citizen
    region: str            # us | eu | it
    triggers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Index loading & embedding
# ---------------------------------------------------------------------------

def _build_text_for_embedding(rule: dict) -> str:
    """Concatenate fields most useful for semantic match.

    Includes title, summary, and triggers (which are essentially synonyms).
    NOT source (case names) — those bias toward citation rather than meaning.
    """
    parts = [rule.get("title", ""), rule.get("summary", "")]
    triggers = rule.get("triggers", [])
    if triggers:
        parts.append("Examples: " + "; ".join(triggers))
    return " | ".join(p for p in parts if p)


def _load_rules_for_region(region: str) -> list[dict]:
    """Load rules. For 'it', merge police_eu.json + police_it.json.
    Each rule gets a '_region' field marking origin (eu or it).
    """
    region = region.lower()
    results: list[dict] = []
    if region == "it":
        # Extends EU
        eu_path = CASE_LAW_DIR / "police_eu.json"
        it_path = CASE_LAW_DIR / "police_it.json"
        with eu_path.open(encoding="utf-8") as f:
            eu = json.load(f)
        with it_path.open(encoding="utf-8") as f:
            it = json.load(f)
        for r in eu.get("rules", []):
            r2 = dict(r); r2["_region"] = "eu"; results.append(r2)
        for r in it.get("rules", []):
            r2 = dict(r); r2["_region"] = "it"; results.append(r2)
    else:
        path = CASE_LAW_DIR / f"police_{region}.json"
        with path.open(encoding="utf-8") as f:
            pack = json.load(f)
        for r in pack.get("rules", []):
            r2 = dict(r); r2["_region"] = region; results.append(r2)
    return results


def _index_paths(region: str) -> tuple[Path, Path]:
    return INDEX_DIR / f"{region}.faiss", INDEX_DIR / f"{region}.meta.json"


# ---------------------------------------------------------------------------
# Singleton model loader (loaded once per process)
# ---------------------------------------------------------------------------

_MODEL = None

def _get_model():
    global _MODEL
    if _MODEL is None:
        from sentence_transformers import SentenceTransformer
        t0 = time.perf_counter()
        _MODEL = SentenceTransformer(EMBED_MODEL_NAME)
        # Optional: warn if took long
        elapsed = time.perf_counter() - t0
        if elapsed > 5 and os.environ.get("SENTINEL_QUIET") != "1":
            print(f"[retrieval] loaded {EMBED_MODEL_NAME} in {elapsed:.1f}s", file=sys.stderr)
    return _MODEL


def encode_texts(texts: list[str]) -> "np.ndarray":
    """Encode and L2-normalize for cosine-via-inner-product."""
    import numpy as np
    model = _get_model()
    emb = model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
    # L2 normalize
    norms = np.linalg.norm(emb, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    emb = emb / norms
    return emb.astype("float32")


# ---------------------------------------------------------------------------
# Index build (used by tools/build_indexes.py and as a fallback on-the-fly)
# ---------------------------------------------------------------------------

def build_index_for_region(region: str, save: bool = True) -> tuple["faiss.IndexFlatIP", list[dict]]:
    """Build a FAISS index from current rule packs."""
    import faiss
    rules = _load_rules_for_region(region)
    if not rules:
        raise ValueError(f"No rules found for region={region}")
    texts = [_build_text_for_embedding(r) for r in rules]
    embs = encode_texts(texts)
    index = faiss.IndexFlatIP(EMBED_DIM)
    index.add(embs)
    if save:
        INDEX_DIR.mkdir(parents=True, exist_ok=True)
        idx_path, meta_path = _index_paths(region)
        faiss.write_index(index, str(idx_path))
        # Save lightweight metadata for fast lookup (we don't store full rule
        # in FAISS — we keep it here ordered to match index rows).
        meta = [
            {
                "rule_id": r["id"],
                "title": r.get("title", ""),
                "summary": r.get("summary", ""),
                "source": r.get("source", ""),
                "severity": r.get("severity", "medium"),
                "subject": r.get("subject", "officer"),
                "triggers": r.get("triggers", []),
                "region": r.get("_region", region),
            }
            for r in rules
        ]
        with meta_path.open("w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)
    return index, rules


def load_index_for_region(region: str) -> tuple["faiss.IndexFlatIP", list[dict]]:
    """Load FAISS index + metadata; rebuild if missing."""
    import faiss
    idx_path, meta_path = _index_paths(region)
    if not idx_path.exists() or not meta_path.exists():
        return build_index_for_region(region, save=True)
    index = faiss.read_index(str(idx_path))
    with meta_path.open(encoding="utf-8") as f:
        meta = json.load(f)
    return index, meta


# ---------------------------------------------------------------------------
# RetrievalAgent
# ---------------------------------------------------------------------------

class RetrievalAgent:
    """Semantic retrieval over jurisdiction rule packs."""

    def __init__(self, trace=None):
        self.trace = trace
        self._cache: dict[str, tuple] = {}  # region -> (index, meta)

    def _get(self, region: str) -> tuple:
        region = region.lower()
        if region not in self._cache:
            t0 = time.perf_counter()
            self._cache[region] = load_index_for_region(region)
            if self.trace is not None:
                self.trace.emit(
                    "retrieval", "index_loaded",
                    data={"region": region, "rules": len(self._cache[region][1]),
                          "load_ms": round((time.perf_counter() - t0) * 1000, 1)},
                )
        return self._cache[region]

    def search(
        self,
        query: str,
        region: str = "us",
        top_k: int = 5,
        subject_filter: Optional[str] = None,  # 'officer' | 'citizen' | None
    ) -> list[RuleHit]:
        """Return top-K rules ranked by cosine similarity.

        If subject_filter is set, we over-retrieve (top_k * 3) then filter.
        """
        t0 = time.perf_counter()
        index, meta = self._get(region)
        q_emb = encode_texts([query])
        # Over-retrieve when filtering so we still return top_k after filter
        search_k = top_k * 3 if subject_filter else top_k
        search_k = min(search_k, len(meta))
        scores, idxs = index.search(q_emb, search_k)
        hits: list[RuleHit] = []
        for score, idx in zip(scores[0], idxs[0]):
            if idx < 0:
                continue
            m = meta[idx]
            if subject_filter and m.get("subject") != subject_filter:
                continue
            hits.append(RuleHit(
                rule_id=m["rule_id"],
                score=float(score),
                title=m["title"],
                summary=m["summary"],
                source=m["source"],
                severity=m["severity"],
                subject=m["subject"],
                region=m["region"],
                triggers=m.get("triggers", []),
            ))
            if len(hits) >= top_k:
                break

        elapsed_ms = (time.perf_counter() - t0) * 1000
        if self.trace is not None:
            self.trace.emit(
                "retrieval", "search",
                data={
                    "region": region,
                    "query": query[:120],
                    "top_k": top_k,
                    "returned": len(hits),
                    "subject_filter": subject_filter,
                    "latency_ms": round(elapsed_ms, 1),
                    "top_hit": hits[0].rule_id if hits else None,
                    "top_score": round(hits[0].score, 3) if hits else None,
                },
            )
        return hits


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli():
    import argparse
    parser = argparse.ArgumentParser(description="SENTINEL Retrieval — semantic rule search")
    parser.add_argument("--query", required=True, help="Search query (utterance or description)")
    parser.add_argument("--region", default="us", choices=["us", "eu", "it"])
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--subject", default=None, choices=["officer", "citizen"])
    parser.add_argument("--json", action="store_true", help="Emit JSON only")
    parser.add_argument("--rebuild", action="store_true", help="Force index rebuild")
    args = parser.parse_args()

    if args.rebuild:
        print(f"Rebuilding index for region={args.region}...", file=sys.stderr)
        t0 = time.perf_counter()
        build_index_for_region(args.region, save=True)
        print(f"Rebuilt in {time.perf_counter()-t0:.1f}s", file=sys.stderr)

    agent = RetrievalAgent()
    t0 = time.perf_counter()
    hits = agent.search(args.query, region=args.region, top_k=args.top_k, subject_filter=args.subject)
    total_ms = (time.perf_counter() - t0) * 1000

    if args.json:
        print(json.dumps([h.to_dict() for h in hits], indent=2, ensure_ascii=False))
        return

    print("=" * 78)
    print(f"RETRIEVAL  region={args.region}  top_k={args.top_k}  subject={args.subject or 'any'}")
    print(f"  Query: {args.query}")
    print(f"  Total latency: {total_ms:.1f} ms  (incl. model load if cold)")
    print("=" * 78)
    if not hits:
        print("  (no hits)")
        return
    for i, h in enumerate(hits, 1):
        bar = "█" * int(h.score * 30)
        print(f"\n  [{i}] {h.rule_id:24s} score={h.score:.3f}  {bar}")
        print(f"      [{h.severity:8s}|{h.subject:7s}|{h.region}] {h.title}")
        print(f"      {h.source[:100]}")
        print(f"      {h.summary[:180]}{'...' if len(h.summary) > 180 else ''}")
    print()


if __name__ == "__main__":
    _cli()
