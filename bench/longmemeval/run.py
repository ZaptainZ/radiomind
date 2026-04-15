"""LongMemEval benchmark runner — 500 questions, 6 question types.

LongMemEval (Wu et al., 2024) is a more recent long-form memory benchmark than
LoCoMo. Oracle variant: each question comes bundled with 1-3 evidence sessions
(no distractors); the task is pure retrieval quality of turns marked has_answer.

Usage:
    curl -sLo /tmp/longmemeval-data/oracle.json \\
      "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_oracle.json"

    python bench/longmemeval/run.py

Output: bench/longmemeval/oracle-result.json — R@5, R@10 overall + per type.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import sys
import time
from pathlib import Path


def run(dataset_path: Path, sandbox: Path, top_k: int = 5) -> dict:
    os.environ.setdefault("RADIOMIND_HOME", str(sandbox))
    if (sandbox / "data").exists():
        shutil.rmtree(sandbox / "data")
    sandbox.mkdir(parents=True, exist_ok=True)

    from radiomind.core.mind import RadioMind
    from radiomind.core.types import MemoryEntry, MemoryLevel

    data = json.loads(dataset_path.read_text())
    mind = RadioMind()
    mind.initialize()

    per_type_hits5: dict[str, list[float]] = {}
    per_type_hits10: dict[str, list[float]] = {}
    evaluated = 0
    skipped = 0

    t_total = time.time()
    for q_idx, q in enumerate(data):
        qtype = q.get("question_type", "?")
        question = q.get("question", "")
        if not question or not q.get("haystack_sessions"):
            skipped += 1
            continue

        # Per-question isolated domain (so sessions don't cross-pollute)
        domain = f"lme_{q_idx}"
        turn_ids_with_answer: list[str] = []

        # Ingest all haystack turns
        for s_idx, session in enumerate(q["haystack_sessions"]):
            sid = q["haystack_session_ids"][s_idx] if s_idx < len(q["haystack_session_ids"]) else f"sess_{s_idx}"
            sdate = q["haystack_dates"][s_idx] if s_idx < len(q["haystack_dates"]) else ""
            for t_idx, turn in enumerate(session):
                txt = turn.get("content", "")
                if not txt:
                    continue
                tid = f"{sid}_t{t_idx}"
                if turn.get("has_answer"):
                    turn_ids_with_answer.append(tid)
                entry = MemoryEntry(
                    content=f"[{turn.get('role','?')}] {txt}",
                    domain=domain,
                    level=MemoryLevel.FACT,
                    metadata={"turn_id": tid, "session": sid, "date": sdate},
                )
                if mind._embedder:
                    entry.embedding = mind._embedder.encode(txt)
                mind._store.add(entry, dedup=False)

        if not turn_ids_with_answer:
            skipped += 1
            continue

        results = mind.search(question, domain=domain)
        retrieved5 = {r.entry.metadata.get("turn_id", "") for r in results[:top_k]}
        retrieved10 = {r.entry.metadata.get("turn_id", "") for r in results[:10]}

        gold = set(turn_ids_with_answer)
        hit5 = 1.0 if gold & retrieved5 else 0.0
        hit10 = 1.0 if gold & retrieved10 else 0.0
        per_type_hits5.setdefault(qtype, []).append(hit5)
        per_type_hits10.setdefault(qtype, []).append(hit10)
        evaluated += 1

        if (q_idx + 1) % 50 == 0:
            print(f"  [{q_idx+1}/{len(data)}] {qtype}: R@5 so far = "
                  f"{sum(sum(v) for v in per_type_hits5.values()) / evaluated:.3f}",
                  flush=True)

    elapsed = time.time() - t_total

    overall_r5 = sum(sum(v) for v in per_type_hits5.values()) / max(1, evaluated)
    overall_r10 = sum(sum(v) for v in per_type_hits10.values()) / max(1, evaluated)

    report = {
        "benchmark": "LongMemEval oracle (Wu et al., 2024)",
        "dataset": str(dataset_path),
        "n_questions_total": len(data),
        "n_evaluated": evaluated,
        "n_skipped": skipped,
        "top_k": top_k,
        "embedder_available": mind._embedder is not None,
        "overall_r@5": round(overall_r5, 4),
        "overall_r@10": round(overall_r10, 4),
        "elapsed_s": round(elapsed, 1),
        "latency_ms_per_q": round(elapsed * 1000 / max(1, evaluated), 2),
        "by_type": {
            t: {
                "n": len(h),
                "r@5": round(sum(h) / len(h), 4),
                "r@10": round(sum(per_type_hits10[t]) / len(per_type_hits10[t]), 4),
            }
            for t, h in sorted(per_type_hits5.items())
        },
    }

    mind.shutdown()
    return report


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dataset", default="/tmp/longmemeval-data/oracle.json")
    p.add_argument("--sandbox", default="/tmp/rm-lme-sandbox")
    p.add_argument("--out", default="bench/longmemeval/oracle-result.json")
    p.add_argument("--top-k", type=int, default=5)
    args = p.parse_args()

    ds = Path(args.dataset)
    if not ds.exists():
        print(f"Dataset not found: {ds}", file=sys.stderr)
        return 2

    sandbox = Path(args.sandbox)
    report = run(ds, sandbox, top_k=args.top_k)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2))

    print(f"\n=== LongMemEval oracle ({report['n_evaluated']} evaluated, "
          f"{report['n_skipped']} skipped) ===")
    print(f"  Recall@5:  {report['overall_r@5']:.3f}")
    print(f"  Recall@10: {report['overall_r@10']:.3f}")
    print(f"  latency:   {report['latency_ms_per_q']:.1f} ms/q")
    print(f"\n  By question type:")
    for t, stats in report["by_type"].items():
        print(f"    {t:30s} (n={stats['n']:3d})  R@5={stats['r@5']:.3f}  R@10={stats['r@10']:.3f}")
    print(f"\n  Saved → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
