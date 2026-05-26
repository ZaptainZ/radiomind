"""JAB-1 offline scan: count concrete-gold + canonical-abstain
per-query records that were marked correct=true.

For each LME-S artifact:
  - load per_query
  - for each record:
      - is gold canonical abstain?  (skip — gold itself is abstain)
      - is answer canonical abstain? (yes/no)
      - if gold_concrete AND answer_abstain AND correct=true →
        FALSE-PASS candidate
  - report per-file count + qids

Definitions (deliberately conservative — only catches the most
unambiguous abstain phrasings):
  CANONICAL_ABSTAIN_GOLD = exact match (case-insensitive,
    whitespace-normalized) of common LME-S abstain golds
  CANONICAL_ABSTAIN_RESPONSE = response contains any of the
    canonical abstain phrases as a (near-)complete answer

The goal is high precision, not recall — to support the claim
"X% of correct=true are abstain false-passes" we need to be
sure each flagged record is unambiguously a false-pass.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

# Shared canonical-abstain detector with runner-side JAB-1a veto.
from jab1_abstain_veto import is_abstain_gold as _is_gold_abstain
from jab1_abstain_veto import is_abstain_response as _is_response_abstain


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path,
                   default=Path("bench/end_to_end"))
    p.add_argument("--out", type=Path,
                   default=Path("bench/end_to_end/jab1-false-pass-scan.json"))
    args = p.parse_args()

    files = sorted(args.root.glob("lme-s-*.json"))
    print(f"scanning {len(files)} artifacts")

    rows = []
    for f in files:
        try:
            d = json.loads(f.read_text())
        except Exception as e:
            print(f"  skip {f.name}: {e}")
            continue
        per_query = d.get("per_query")
        if not per_query:
            continue
        overall_acc = d.get("overall_accuracy") or d.get(
            "overall_accuracy") or None

        n_total = len(per_query)
        n_correct = sum(1 for r in per_query if r.get("correct"))
        false_passes: list[dict] = []
        for r in per_query:
            qid = r.get("question_id") or r.get("qid", "?")
            gold = r.get("gold") or r.get("answer_gold", "")
            ans = r.get("answer", "")
            correct = bool(r.get("correct"))
            if not correct:
                continue
            if _is_gold_abstain(gold):
                continue
            if not _is_response_abstain(ans):
                continue
            false_passes.append({
                "qid": qid,
                "gold": str(gold)[:120],
                "answer": str(ans)[:160],
                "qtype": r.get("qtype", "?"),
                "verdict_tail": (r.get("verdict_tail") or "")[:180],
            })
        rows.append({
            "file": f.name,
            "n_total": n_total,
            "n_correct": n_correct,
            "acc_reported": overall_acc,
            "n_false_pass_candidates": len(false_passes),
            "false_passes": false_passes,
        })

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(rows, indent=2, ensure_ascii=False))

    print(f"\n=== JAB-1 false-pass scan summary ===")
    print(f"{'file':<60} {'n':>4} {'acc':>6} {'#fp':>4}")
    total_fp = 0
    for row in rows:
        acc = f"{row['acc_reported']:.3f}" if row['acc_reported'] is not None else "n/a"
        print(f"  {row['file']:<60} {row['n_total']:>4} {acc:>6} "
              f"{row['n_false_pass_candidates']:>4}")
        total_fp += row['n_false_pass_candidates']
    print(f"\ntotal false-pass candidates across all files: {total_fp}")
    print(f"\n=== files with ≥1 false-pass ===")
    for row in rows:
        if row['n_false_pass_candidates'] == 0:
            continue
        print(f"\n{row['file']} (n={row['n_total']}, {row['n_false_pass_candidates']} false-pass):")
        for fp in row['false_passes'][:10]:
            print(f"  {fp['qid']:<22} gold={fp['gold'][:60]!r}")
            print(f"  {'':>22} ans ={fp['answer'][:80]!r}")
    print(f"\nsaved → {args.out}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
