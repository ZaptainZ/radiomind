"""LoCoMo-lite benchmark runner.

Measures RadioMind retrieval quality on a 60-statement / 50-query synthetic
long-form memory dataset. Outputs Recall@5 and Recall@10 as a regression
baseline for the v0.x line.

Usage:
    # Always run against a sandbox — never touch real ~/.radiomind
    RADIOMIND_HOME=/tmp/rm-bench python bench/locomo_lite/run.py

    # JSON output for CI
    RADIOMIND_HOME=/tmp/rm-bench python bench/locomo_lite/run.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path


DATASET = Path(__file__).parent / "dataset.json"


def recall_at_k(retrieved: list[str], gold: list[str], k: int) -> float:
    top = set(retrieved[:k])
    hit = sum(1 for g in gold if g in top)
    return hit / len(gold) if gold else 0.0


def run(sandbox: Path, verbose: bool = False) -> dict:
    os.environ["RADIOMIND_HOME"] = str(sandbox)
    sandbox.mkdir(parents=True, exist_ok=True)

    # Import AFTER env is set
    from radiomind.core.config import Config
    from radiomind.core.mind import RadioMind
    from radiomind.core.types import MemoryEntry, MemoryLevel

    cfg = Config.load()
    assert cfg.home == sandbox, f"sandbox leak: {cfg.home}"

    data = json.loads(DATASET.read_text())
    statements = data["statements"]
    queries = data["queries"]

    mind = RadioMind()
    mind.initialize()

    # Directly add as L2 facts — bypass the gate so every statement lands
    # in memory. The gate's job is attention filtering on conversation;
    # here we're benchmarking retrieval on known-indexed content.
    id_map: dict[int, str] = {}  # db_id → statement id
    for s in statements:
        entry = MemoryEntry(
            content=s["text"],
            domain="bench",
            level=MemoryLevel.FACT,
            metadata={"sid": s["id"]},
        )
        if mind._embedder:
            entry.embedding = mind._embedder.encode(s["text"])
        mid = mind._store.add(entry, dedup=False)
        id_map[mid] = s["id"]

    # Run queries
    r5_scores: list[float] = []
    r10_scores: list[float] = []
    per_query: list[dict] = []
    method_counter: dict[str, int] = {}

    t0 = time.time()
    for q in queries:
        results = mind.search(q["q"])
        retrieved_sids: list[str] = []
        for r in results:
            sid = r.entry.metadata.get("sid", "")
            if sid:
                retrieved_sids.append(sid)
            method_counter[r.method] = method_counter.get(r.method, 0) + 1

        r5 = recall_at_k(retrieved_sids, q["gold"], 5)
        r10 = recall_at_k(retrieved_sids, q["gold"], 10)
        r5_scores.append(r5)
        r10_scores.append(r10)
        per_query.append({
            "q": q["q"],
            "gold": q["gold"],
            "retrieved_top5": retrieved_sids[:5],
            "r@5": round(r5, 3),
            "r@10": round(r10, 3),
        })
        if verbose:
            status = "OK" if r5 == 1.0 else ("PART" if r5 > 0 else "MISS")
            print(f"  [{status}] {q['q']:<30s} R@5={r5:.2f} top5={retrieved_sids[:5]} gold={q['gold']}")

    elapsed = time.time() - t0

    report = {
        "dataset": str(DATASET),
        "sandbox": str(sandbox),
        "n_statements": len(statements),
        "n_queries": len(queries),
        "embedder_available": mind._embedder is not None,
        "retrieval_methods_used": method_counter,
        "recall@5": {
            "mean": round(statistics.mean(r5_scores), 4),
            "median": round(statistics.median(r5_scores), 4),
            "perfect_count": sum(1 for s in r5_scores if s == 1.0),
            "zero_count": sum(1 for s in r5_scores if s == 0.0),
        },
        "recall@10": {
            "mean": round(statistics.mean(r10_scores), 4),
            "median": round(statistics.median(r10_scores), 4),
            "perfect_count": sum(1 for s in r10_scores if s == 1.0),
            "zero_count": sum(1 for s in r10_scores if s == 0.0),
        },
        "latency_total_s": round(elapsed, 2),
        "latency_per_query_ms": round(elapsed * 1000 / len(queries), 1),
        "per_query": per_query,
    }

    mind.shutdown()
    return report


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--json", action="store_true", help="Output full JSON report.")
    p.add_argument("--verbose", "-v", action="store_true", help="Print per-query results.")
    p.add_argument("--sandbox", default="/tmp/rm-bench-locomo", help="Sandbox home dir.")
    p.add_argument("--save", default="", help="Save JSON report to this path.")
    args = p.parse_args()

    sandbox = Path(args.sandbox)
    # Fresh sandbox each run so indexing state is reproducible
    if sandbox.exists():
        import shutil
        shutil.rmtree(sandbox)

    report = run(sandbox, verbose=args.verbose)

    if args.save:
        Path(args.save).write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(f"Saved report → {args.save}")

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("LoCoMo-lite baseline")
        print(f"  sandbox:             {report['sandbox']}")
        print(f"  statements / queries: {report['n_statements']} / {report['n_queries']}")
        print(f"  embedder available:  {report['embedder_available']}")
        print(f"  methods used:        {report['retrieval_methods_used']}")
        print(f"  Recall@5:            {report['recall@5']['mean']:.3f}  "
              f"(perfect={report['recall@5']['perfect_count']}, zero={report['recall@5']['zero_count']})")
        print(f"  Recall@10:           {report['recall@10']['mean']:.3f}  "
              f"(perfect={report['recall@10']['perfect_count']}, zero={report['recall@10']['zero_count']})")
        print(f"  Latency/query:       {report['latency_per_query_ms']:.1f} ms")

    # Nonzero exit if recall@5 collapses — acts as a CI regression gate
    if report["recall@5"]["mean"] < 0.3:
        print(f"\nWARN: Recall@5 below 0.3 — regression likely.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
