"""Full LoCoMo10 benchmark — all 10 conversations, all ~1986 QA pairs.

Canonical long-form memory benchmark (Maharana et al., ACL 2024).
We evaluate retrieval-only: for each QA with evidence markers, check
if RadioMind's top-k returns any of the gold evidence turns.

Usage:
    # Needs the dataset downloaded
    curl -sLo /tmp/locomo10.json \
      https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json

    RADIOMIND_HOME=/tmp/rm-locomo-full \
        python bench/locomo_real/run_all.py

Output: bench/locomo_real/full-result.json

Each conversation gets its own sandbox domain so we don't pollute
across convs. A separate RadioMind instance per conversation would be
cleaner but ~10× slower on init; domain-scoped search + isolated
evidence IDs give us the same end result.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from collections import Counter
from pathlib import Path


def run(dataset_path: Path, sandbox: Path, top_k: int = 5) -> dict:
    os.environ.setdefault("RADIOMIND_HOME", str(sandbox))
    sandbox.mkdir(parents=True, exist_ok=True)

    from radiomind.core.mind import RadioMind
    from radiomind.core.types import MemoryEntry, MemoryLevel

    data = json.loads(dataset_path.read_text())
    mind = RadioMind()
    mind.initialize()

    # Ingest every turn of every conversation into its own domain
    t_ingest = time.time()
    total_turns = 0
    conv_domains: list[str] = []
    for conv_idx, conv in enumerate(data):
        domain = f"loco{conv_idx}"
        conv_domains.append(domain)
        session_keys = sorted(
            [k for k in conv["conversation"]
             if k.startswith("session_") and not k.endswith("date_time")],
            key=lambda s: int(s.split("_")[1]),
        )
        for sess_idx, skey in enumerate(session_keys, 1):
            date = conv["conversation"].get(f"session_{sess_idx}_date_time", "")
            for turn_idx, turn in enumerate(conv["conversation"][skey], 1):
                txt = turn.get("text", "")
                if not txt:
                    continue
                entry = MemoryEntry(
                    content=f"[{turn.get('speaker', '?')}] {txt}",
                    domain=domain,
                    level=MemoryLevel.FACT,
                    metadata={
                        "evidence_id": f"D{sess_idx}:{turn_idx}",
                        "date": date,
                        "conv": conv_idx,
                    },
                )
                if mind._embedder:
                    entry.embedding = mind._embedder.encode(txt)
                mind._store.add(entry, dedup=False)
                total_turns += 1
    ingest_time = time.time() - t_ingest
    print(f"Ingested {total_turns} turns across {len(data)} conversations in {ingest_time:.1f}s")

    # Evaluate every QA
    per_cat_hits: dict[int, list[float]] = {}
    per_cat_hits_k10: dict[int, list[float]] = {}
    per_conv_hits: dict[int, list[float]] = {}
    evaluated = 0
    skipped = 0

    t_eval = time.time()
    for conv_idx, conv in enumerate(data):
        domain = conv_domains[conv_idx]
        for qa in conv["qa"]:
            q = qa.get("question", "")
            evidence = qa.get("evidence", [])
            cat = qa.get("category", 0)
            if not q or not evidence:
                skipped += 1
                continue
            gold = set(evidence)
            results = mind.search(q, domain=domain)
            retrieved = [r.entry.metadata.get("evidence_id", "") for r in results[:top_k]]
            retrieved_10 = [r.entry.metadata.get("evidence_id", "") for r in results[:10]]

            hit5 = 1.0 if gold & set(retrieved) else 0.0
            hit10 = 1.0 if gold & set(retrieved_10) else 0.0
            per_cat_hits.setdefault(cat, []).append(hit5)
            per_cat_hits_k10.setdefault(cat, []).append(hit10)
            per_conv_hits.setdefault(conv_idx, []).append(hit5)
            evaluated += 1
    eval_time = time.time() - t_eval

    # Aggregate
    overall_r5 = sum(sum(v) for v in per_cat_hits.values()) / max(1, evaluated)
    overall_r10 = sum(sum(v) for v in per_cat_hits_k10.values()) / max(1, evaluated)

    report = {
        "benchmark": "LoCoMo10 (Snap Research / ACL 2024) — all 10 conversations",
        "n_conversations": len(data),
        "n_turns_ingested": total_turns,
        "n_queries_evaluated": evaluated,
        "n_queries_skipped_no_evidence": skipped,
        "ingest_time_s": round(ingest_time, 1),
        "eval_time_s": round(eval_time, 1),
        "eval_latency_ms_per_query": round(eval_time * 1000 / max(1, evaluated), 2),
        "embedder_available": mind._embedder is not None,
        "overall_r@5": round(overall_r5, 4),
        "overall_r@10": round(overall_r10, 4),
        "by_category_r@5": {
            f"cat{cat}": {"n": len(h), "r@5": round(sum(h) / len(h), 4),
                          "r@10": round(sum(per_cat_hits_k10[cat]) / len(per_cat_hits_k10[cat]), 4)}
            for cat, h in sorted(per_cat_hits.items())
        },
        "by_conversation_r@5": {
            f"conv{c}": {"n": len(h), "r@5": round(sum(h) / len(h), 4)}
            for c, h in sorted(per_conv_hits.items())
        },
    }

    mind.shutdown()
    return report


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dataset", default="/tmp/locomo10.json",
                   help="Path to locomo10.json (download from snap-research/locomo repo)")
    p.add_argument("--sandbox", default="/tmp/rm-locomo-full",
                   help="RadioMind sandbox dir (MUST NOT be ~/.radiomind)")
    p.add_argument("--out", default="bench/locomo_real/full-result.json")
    p.add_argument("--top-k", type=int, default=5)
    args = p.parse_args()

    ds = Path(args.dataset)
    if not ds.exists():
        print(f"Dataset not found at {ds}. Download with:\n  curl -sLo {ds} "
              f"https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json",
              file=sys.stderr)
        return 2

    sandbox = Path(args.sandbox)
    # Fresh DB per run, but preserve models/ so a pre-staged embedder survives
    import shutil
    if (sandbox / "data").exists():
        shutil.rmtree(sandbox / "data")
    sandbox.mkdir(parents=True, exist_ok=True)

    report = run(ds, sandbox, top_k=args.top_k)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2))

    print(f"\n=== LoCoMo10 — full ({report['n_queries_evaluated']} queries) ===")
    print(f"  Recall@5:  {report['overall_r@5']:.3f}")
    print(f"  Recall@10: {report['overall_r@10']:.3f}")
    print(f"  embedder:  {report['embedder_available']}")
    print(f"  eval time: {report['eval_time_s']:.1f}s  ({report['eval_latency_ms_per_query']} ms/query)")
    print(f"\n  By category:")
    for cat, stats in report["by_category_r@5"].items():
        print(f"    {cat} (n={stats['n']:3d}):  R@5={stats['r@5']:.3f}  R@10={stats['r@10']:.3f}")
    print(f"\n  Saved → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
