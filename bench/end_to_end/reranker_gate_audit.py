#!/usr/bin/env python3
"""reranker_gate_audit.py — RerankerAlternative-1b: query-adaptive RRF gate audit.

READ-ONLY. No runtime change, no cloud, no full benchmark. Answers, on a LARGER
held-out qid set (not the curated 19 of 1a), whether the query-adaptive RRF
method (C) can be safely gated:

  Q1 which query types are safe for C?
  Q2 which must skip?
  Q3 can we reuse BioLocal-1b's do-no-harm gate (anchored = should_rerank)?
  Q4 is C's win a general mechanism, or 19-qid small-sample luck?

The gate under test (reusing BioLocal-1b's classification):
  C_gated = apply C only when query class == "anchored"
            (number/entity anchor, non-temporal/ordering/cjk); else dense-only.

Computes ONLY baseline (ONNX dense) + C + C_gated per qid (skips A/B/D — they are
PARKed) for speed. Baseline required; BLOCKS if no local embedder (never remote).

Run (py3.12 + [embedding]):
  /tmp/rm-rc-venv/bin/python bench/end_to_end/reranker_gate_audit.py --n 60
  ... --report bench/end_to_end/reranker-gate-1b-result.json
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from biolocal_probe import (  # noqa: E402
    DATASET, TARGET_QIDS, _ingest_qid, _gold_turn_ids, _candidate_pool,
)
from reranker_alt_probe import (  # noqa: E402
    _classify_query, _method_c, _baseline, _embed_matrix, _load_embedder,
)

REPO = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO / "bench/end_to_end/reranker-gate-1b-result.json"
# the 1a curated 19 (TARGET_QIDS + the controls _select_qids picked) — exclude
# from held-out so this is a genuinely fresh sample.
EXCLUDE = set(TARGET_QIDS) | {"e47becba", "118b2229", "51a45a95", "58bf7951", "1e043500"}


def _holdout_qids(data, n):
    out = []
    for r in data:
        if len(out) >= n:
            break
        if r["question_id"] not in EXCLUDE and r.get("haystack_sessions"):
            out.append(r["question_id"])
    return out


def audit_qid(mind, embedder, target, idx):
    import numpy as np
    qid = target["question_id"]; query = target["question"]
    _ingest_qid(mind, target, f"gate_{idx}")
    gold = _gold_turn_ids(target)
    pool = _candidate_pool(mind, f"gate_{idx}")
    if not pool or not gold:
        return None
    E = _embed_matrix(embedder, [c["content"] for c in pool])
    q = _embed_matrix(embedder, [query])[0]
    dense = E @ q
    base, base_order = _baseline(dense, pool, gold)
    c_metrics = _method_c(dense, pool, gold, query, mind._store)
    cls = _classify_query(query)
    gated_is_c = (cls == "anchored")
    return {
        "qid": qid, "question": query[:140],
        "question_type": target.get("question_type", "?"),
        "qclass": cls, "gold_total": len(gold),
        "base_best": base["best_rank"], "c_best": c_metrics["best_rank"],
        "gated_best": c_metrics["best_rank"] if gated_is_c else base["best_rank"],
        "base_r5": base["recall_at_5"], "c_r5": c_metrics["recall_at_5"],
        "gated_r5": c_metrics["recall_at_5"] if gated_is_c else base["recall_at_5"],
        "gated_applied_c": gated_is_c,
    }


def _verdict(rows):
    def br(v):
        return v if v is not None else 9999
    by = defaultdict(lambda: {"c_win": 0, "c_harm": 0, "g_win": 0, "g_harm": 0, "n": 0})
    tot = {"c_win": 0, "c_harm": 0, "g_win": 0, "g_harm": 0}
    for r in rows:
        b = br(r["base_best"]); c = br(r["c_best"]); g = br(r["gated_best"])
        k = by[r["qclass"]]; k["n"] += 1
        if c < b: k["c_win"] += 1; tot["c_win"] += 1
        elif c > b: k["c_harm"] += 1; tot["c_harm"] += 1
        if g < b: k["g_win"] += 1; tot["g_win"] += 1
        elif g > b: k["g_harm"] += 1; tot["g_harm"] += 1
    return {"per_class": dict(by), "totals": tot}


def _print(result):
    rows = result["results"]; v = result["verdict"]
    print(f"\nRerankerAlternative-1b gate audit — {len(rows)} held-out qids")
    print("=" * 80)
    print("per query-class (ungated C vs gated C, wins/harms vs dense baseline):")
    print(f"  {'class':22} {'n':>3}  {'C win/harm':>12}  {'C_gated win/harm':>16}")
    for cls, k in sorted(v["per_class"].items()):
        cwh = f"{k['c_win']}/{k['c_harm']}"
        gwh = f"{k['g_win']}/{k['g_harm']}"
        print(f"  {cls:22} {k['n']:>3}  {cwh:>12}  {gwh:>16}")
    t = v["totals"]
    print("-" * 80)
    print(f"  TOTAL ungated C : wins={t['c_win']} harms={t['c_harm']}")
    print(f"  TOTAL gated  C  : wins={t['g_win']} harms={t['g_harm']}")
    # anchored-class harm count = the key generality signal
    anc = v["per_class"].get("anchored", {})
    print(f"\n  anchored-class harms under C (the gated path): {anc.get('c_harm', 0)} "
          f"(0 = gate is safe & general)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--sandbox", default="/tmp/rm-gateaudit")
    ap.add_argument("--report", default="")
    args = ap.parse_args()

    if args.report:
        _print(json.loads(Path(args.report).read_text())); return 0
    if not DATASET.exists():
        print(f"dataset missing: {DATASET}", file=sys.stderr); return 2

    os.environ["RADIOMIND_HOME"] = args.sandbox
    os.environ["RADIOMIND_REMOTE_RETRIEVAL"] = "0"
    sb = Path(args.sandbox)
    if sb.exists():
        shutil.rmtree(sb)
    sb.mkdir(parents=True, exist_ok=True)

    embedder, msg = _load_embedder()
    if embedder is None:
        print(f"BLOCKED: ONNX embedding baseline unavailable ({msg}). "
              f"Install radiomind[embedding]; NOT falling back to remote.", file=sys.stderr)
        return 3

    data = json.loads(DATASET.read_text())
    by = {r["question_id"]: r for r in data}
    qids = _holdout_qids(data, args.n)

    from radiomind.core.mind import RadioMind
    mind = RadioMind(); mind.initialize()
    mind._embedder = None; mind._reranker = None  # keep mind.search = FTS for C

    rows = []
    t_all = time.time()
    for i, qid in enumerate(qids):
        t0 = time.time()
        try:
            r = audit_qid(mind, embedder, by[qid], i)
            if r:
                rows.append(r)
                print(f"[{i+1}/{len(qids)}] {qid:16} {r['qclass']:20} "
                      f"base={r['base_best']} C={r['c_best']} ({time.time()-t0:.1f}s)", flush=True)
        except Exception as e:
            print(f"[{i+1}/{len(qids)}] {qid} FAILED: {type(e).__name__}: {e}", flush=True)
    mind.shutdown()

    out = {"experiment": "RerankerAlternative-1b-gate-audit",
           "gate": "C applied only when qclass=='anchored' (== facet_rerank.should_rerank)",
           "held_out_n": len(rows), "excluded_1a_qids": sorted(EXCLUDE),
           "elapsed_s": round(time.time() - t_all, 1),
           "results": rows, "verdict": _verdict(rows)}
    Path(args.out).write_text(json.dumps(out, indent=2))
    print(f"\nwrote {args.out}")
    _print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
