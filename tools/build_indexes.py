"""Build FAISS indexes for all rule pack regions.

Run once after any change to case_law/police_*.json:
    python -m tools.build_indexes

Output: case_law/indexes/{us,eu,it}.faiss + .meta.json
"""
from __future__ import annotations
import sys
import time
from pathlib import Path

# Ensure repo root on path when invoked as 'python tools/build_indexes.py'
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agents.retrieval_agent import build_index_for_region, INDEX_DIR


def main():
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    regions = ["us", "eu", "it"]
    print(f"Building FAISS indexes → {INDEX_DIR}")
    print("=" * 60)
    overall_t0 = time.perf_counter()
    for region in regions:
        t0 = time.perf_counter()
        index, rules = build_index_for_region(region, save=True)
        elapsed = time.perf_counter() - t0
        print(f"  [{region:3s}] {len(rules):3d} rules  →  index built in {elapsed:.1f}s")
    print("=" * 60)
    print(f"Done in {time.perf_counter()-overall_t0:.1f}s")
    print()
    print("Files written:")
    for f in sorted(INDEX_DIR.iterdir()):
        size_kb = f.stat().st_size / 1024
        print(f"  {f.name:30s} {size_kb:8.1f} KB")


if __name__ == "__main__":
    main()
