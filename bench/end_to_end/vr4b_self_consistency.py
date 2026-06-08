"""VR-4b — answer self-consistency offline analysis (bench-only experiment).

Reads a seed run (baseline single answer) + k answer-only runs over a FIXED
store, and evaluates whether aggregating k answers per qid (judge-majority or
exact-answer mode) improves the unstable qids without harming controls.

This is a MEASUREMENT, not a protocol. It does NOT change the eval protocol,
does NOT touch runtime, and its numbers are stability-adjusted — NEVER a
Mem0-compatible headline.

Aggregation methods (offline, no new LLM calls):
- baseline       : the seed run's single (answer, verdict) per qid.
- judge-majority : over the k answer-only runs, pass iff >= ceil(k/2) verdicts
                   are correct (i.e. per-qid pass-rate >= 0.5). This is the
                   "run it k times, take the majority verdict" estimator.
- exact-mode     : pick the most frequent normalized answer text across the k
                   runs; its verdict (majority among the runs that produced it)
                   is the result. Models "self-consistency on the answer string".

Usage:
  ~/.radiomind-bench-venv/bin/python bench/end_to_end/vr4b_self_consistency.py \
    --seed bench/end_to_end/vr4b-seed.json \
    --answer-only bench/end_to_end/vr4b-k*.json \
    --roles bench/end_to_end/vr4b-roles.json \
    --out bench/end_to_end/reports/vr4b-self-consistency.json
"""
from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from pathlib import Path


def _pq(d: dict) -> dict:
    return {r.get("question_id") or r.get("qid"): r
            for r in (d.get("per_query") or d.get("results") or [])
            if isinstance(r, dict)}


def _norm(ans: str) -> str:
    """Normalize an answer for exact-mode clustering: lowercase, strip thinking
    tags, collapse whitespace/punctuation tails."""
    if not ans:
        return ""
    ans = re.sub(r"<mem_thinking>[\s\S]*?</mem_thinking>", "", ans,
                 flags=re.IGNORECASE)
    ans = ans.lower().strip()
    ans = re.sub(r"\s+", " ", ans)
    return ans.rstrip(". ")


def analyze(seed: dict, ks: list, roles: dict) -> dict:
    seed_pq = _pq(seed)
    k_pqs = [_pq(d) for d in ks]
    k = len(k_pqs)
    qids = list(seed_pq.keys())

    rows = []
    for q in qids:
        base = seed_pq.get(q, {})
        base_correct = bool(base.get("correct"))
        # k verdicts + answers
        verds, answers = [], []
        for kp in k_pqs:
            r = kp.get(q)
            if r is None:
                continue
            verds.append(bool(r.get("correct")))
            answers.append(r.get("answer") or "")
        n = len(verds)
        n_pass = sum(verds)
        pass_rate = round(n_pass / n, 3) if n else None
        # judge-majority
        maj = (n_pass >= math.ceil(n / 2)) if n else None
        # exact-mode: most common normalized answer; verdict = majority among
        # the runs that produced that exact text
        norms = [_norm(a) for a in answers]
        mode_correct = None
        mode_share = None
        if norms:
            cnt = Counter(norms)
            top_norm, top_n = cnt.most_common(1)[0]
            mode_share = round(top_n / n, 3)
            idxs = [i for i, x in enumerate(norms) if x == top_norm]
            mp = sum(1 for i in idxs if verds[i])
            mode_correct = mp >= math.ceil(len(idxs) / 2)
        rows.append({
            "qid": q, "role": roles.get(q, "?"),
            "qtype": base.get("qtype"),
            "baseline_correct": base_correct,
            "k": n, "k_pass": n_pass, "pass_rate": pass_rate,
            "judge_majority_correct": maj,
            "exact_mode_correct": mode_correct,
            "exact_mode_share": mode_share,
            "distinct_answers": len(set(norms)) if norms else 0,
        })

    def _acc(key):
        vals = [r[key] for r in rows if r[key] is not None]
        return round(sum(1 for v in vals if v) / len(vals), 4) if vals else None

    def _role_delta(role, key):
        rs = [r for r in rows if r["role"] == role]
        b = sum(1 for r in rs if r["baseline_correct"])
        a = sum(1 for r in rs if r[key])
        return {"n": len(rs), "baseline_pass": b, "agg_pass": a, "delta": a - b}

    summary = {
        "k": k, "n_qids": len(rows),
        "acc_baseline": _acc("baseline_correct"),
        "acc_judge_majority": _acc("judge_majority_correct"),
        "acc_exact_mode": _acc("exact_mode_correct"),
        "by_role_judge_majority": {
            role: _role_delta(role, "judge_majority_correct")
            for role in ("unstable", "stable-pass", "stable-fail")},
        "by_role_exact_mode": {
            role: _role_delta(role, "exact_mode_correct")
            for role in ("unstable", "stable-pass", "stable-fail")},
    }
    # per-qid flips vs baseline (judge-majority)
    gains = [r["qid"] for r in rows
             if r["judge_majority_correct"] and not r["baseline_correct"]]
    losses = [r["qid"] for r in rows
              if r["baseline_correct"] and not r["judge_majority_correct"]]
    summary["judge_majority_gains"] = gains
    summary["judge_majority_losses"] = losses
    summary["judge_majority_net"] = len(gains) - len(losses)
    return {"summary": summary, "rows": rows}


def _print(report: dict) -> None:
    s = report["summary"]
    print(f"=== VR-4b self-consistency (k={s['k']}, {s['n_qids']} qids) ===")
    print(f"  acc baseline       : {s['acc_baseline']}")
    print(f"  acc judge-majority : {s['acc_judge_majority']}")
    print(f"  acc exact-mode     : {s['acc_exact_mode']}")
    print(f"  judge-majority net : +{len(s['judge_majority_gains'])} "
          f"-{len(s['judge_majority_losses'])} = {s['judge_majority_net']}")
    print(f"    gains : {s['judge_majority_gains']}")
    print(f"    losses: {s['judge_majority_losses']}")
    for role in ("unstable", "stable-pass", "stable-fail"):
        jm = s["by_role_judge_majority"][role]
        print(f"  [{role:<11}] judge-maj baseline {jm['baseline_pass']}/{jm['n']} "
              f"-> {jm['agg_pass']}/{jm['n']} (Δ{jm['delta']:+})")
    print()
    print(f"  {'qid':<15}{'role':<12}{'base':<5}{'pr':<6}{'maj':<5}{'mode':<5}{'#ans'}")
    for r in report["rows"]:
        print(f"  {r['qid']:<15}{r['role']:<12}"
              f"{'P' if r['baseline_correct'] else 'F':<5}"
              f"{str(r['pass_rate']):<6}"
              f"{'P' if r['judge_majority_correct'] else 'F':<5}"
              f"{'P' if r['exact_mode_correct'] else 'F':<5}"
              f"{r['distinct_answers']}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=Path, required=True)
    ap.add_argument("--answer-only", nargs="+", type=Path, required=True)
    ap.add_argument("--roles", type=Path, required=True,
                    help="JSON {qid: role} with roles unstable/stable-pass/stable-fail.")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    seed = json.loads(args.seed.read_text())
    ks = [json.loads(p.read_text()) for p in args.answer_only]
    roles = json.loads(args.roles.read_text())
    report = analyze(seed, ks, roles)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    _print(report)
    print(f"saved → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
