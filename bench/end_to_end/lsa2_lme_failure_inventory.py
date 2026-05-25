"""LSA-2: LME-S n=100 failure inventory, 4-class label.

Inputs (read-only):
  - bench/end_to_end/lme-s-v822a-n100.judge-fixed.json (most-
    contemporary baseline available)
  - bench/end_to_end/lme-s-v82-1-n100.json (older comparator)
  - ~/Library/Caches/radiomind-data/longmemeval_s_cleaned.json
    (for full question + evidence_session_ids lookup)

For each fail qid (V8.2.2a baseline, MINUS the 4 fixed
target qids — they have shipped helpers now), produce a
JSON record with:

  question / gold / fail_in (which baselines failed) /
  v8x_answer_preview / v8x_verdict_tail /
  evidence_session_ids / qtype /
  preliminary 4-class label

Labels (Codex schema):
  - retrieve_missing
  - evidence_present_computation_missing
  - commit_variance
  - gold_or_input_limitation

Categorization is heuristic based on visible artifacts;
deeper retrieve probes can refine. This is the read-only
first cut.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

# Qids OUT of audit (Codex baseline freeze):
EXCLUDED = {
    # 4 fixed targets — already have shipped deterministic helpers
    "031748ae_abs",     # V8.2.2 role guard
    "9aaed6a3",         # V8.2.3a cashback
    "gpt4_d12ceb0e",    # V8.3.1 person_age average
    "d851d5ba",         # NAR charity sum
    # Dataset errata (runtime-filtered)
    "370a8ff4",
}

# Known-shape labels from V8.3 audit (avoid re-deciding):
V83_AUDIT_LABELS = {
    "d6233ab6":      ("gold_or_input_limitation",
                       "preference advice; not extractable as typed event"),
    "gpt4_ab202e7f": ("gold_or_input_limitation",
                       "kitchen count — entity normalization required, LLM-shaped"),
    "gpt4_d6585ce8": ("evidence_present_computation_missing",
                       "concert ordering — typed event family deferred to V8.3.2"),
    "9a707b82":      ("evidence_present_computation_missing",
                       "cooking-temporal — V8.2.1 retrieve has the answer, "
                       "LLM didn't soft-match 'couple of days ago'. Marginal "
                       "win versus current pipeline."),
}


def _load_per_query(path: Path) -> dict:
    if not path.exists():
        return {}
    return {p["question_id"]: p for p in json.loads(path.read_text())["per_query"]}


def _classify_heuristic(qa: dict, v822_rec: dict) -> tuple[str, str]:
    """Heuristic 4-class label from question text + answer + verdict."""
    ans = (v822_rec.get("answer") or "")
    verdict = (v822_rec.get("verdict_tail") or "")
    q = qa.get("question", "")
    gold = str(qa.get("answer", ""))
    qtype = qa.get("question_type", "?")

    q_low = q.lower()
    ans_low = ans.lower()
    v_low = verdict.lower()
    gold_low = gold.lower()

    # Single-session-preference qtype is ALWAYS preference-advice family
    # in LME-S; gold typically reads "The user would prefer ..." which
    # cannot be extracted as a typed event.
    if qtype == "single-session-preference":
        return ("gold_or_input_limitation",
                "single-session-preference qtype — preference / advice, "
                "not extractable as typed event")

    # Preference / advice / inference family (other qtypes)
    if any(kw in q_low for kw in (
        "would you", "do you think", "good idea", "should i",
        "feeling nostalgic",
    )):
        return ("gold_or_input_limitation",
                "preference / advice — not extractable as typed event")

    # Gold is itself an abstain-style answer ("not enough") — these are
    # "the LLM was expected to refuse to commit". If the LLM committed
    # to something specific, that's commit_variance over a calibration
    # problem, not retrieve_missing.
    if any(kw in gold_low for kw in (
        "information provided is not enough",
        "not enough information",
    )):
        return ("commit_variance",
                "gold itself is abstain; LLM committed a specific answer it "
                "shouldn't have — calibration / over-commit failure")

    # Refusal / abstain pattern in answer
    if any(kw in ans_low for kw in (
        "not enough", "information provided is not",
        "do not specify", "memories do not", "cannot determine",
        "i don't have", "no specific information",
    )):
        return ("retrieve_missing",
                "answer refuses; either retrieve missing or commit over-cautious")

    # Judge explicitly cited a number that doesn't match
    if ("count" in q_low or "how many" in q_low) and re.search(
        r"\b\d+\b", ans,
    ):
        return ("commit_variance",
                "count-shape question; LLM committed a number that judge "
                "rejected — may be over/under by 1 (gold-quality or "
                "entity-norm dependent)")

    # Aggregation / sum / total
    if any(kw in q_low for kw in ("total", "how much money", "sum of",
                                   "average")):
        return ("evidence_present_computation_missing",
                "aggregation-shape question; check if typed events would help")

    # Ordering / sequence / first / last
    if any(kw in q_low for kw in ("order", "first", "earliest", "latest",
                                   "before", "after")):
        return ("evidence_present_computation_missing",
                "temporal-ordering shape; check if event_date can drive a "
                "deterministic order")

    # Multi-session / inference shape, no clear pattern
    if qtype in ("multi-session", "temporal-reasoning"):
        return ("commit_variance",
                f"qtype={qtype}; check retrieve top-K before deciding")

    # Default
    return ("commit_variance",
            "uncategorized heuristic; needs manual audit")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--baseline", type=Path,
                   default=Path("bench/end_to_end/lme-s-v822a-n100.judge-fixed.json"))
    p.add_argument("--older", type=Path,
                   default=Path("bench/end_to_end/lme-s-v82-1-n100.json"))
    p.add_argument("--dataset", type=Path,
                   default=Path.home() / "Library/Caches/radiomind-data/longmemeval_s_cleaned.json")
    p.add_argument("--out", type=Path,
                   default=Path("bench/end_to_end/lsa2-failure-inventory.json"))
    args = p.parse_args()

    baseline = _load_per_query(args.baseline)
    older = _load_per_query(args.older)
    if not baseline:
        print(f"baseline missing: {args.baseline}")
        return 2

    fails_baseline = {q for q, r in baseline.items() if not r.get("correct")}
    fails_older = {q for q, r in older.items() if not r.get("correct")}

    in_scope = sorted(fails_baseline - EXCLUDED)
    print(f"baseline fails: {len(fails_baseline)}")
    print(f"older comparator fails: {len(fails_older)}")
    print(f"EXCLUDED (4 shipped targets + errata): {sorted(EXCLUDED)}")
    print(f"in-scope fails: {len(in_scope)}")
    print()

    # Load dataset for question / gold lookup
    ds_index: dict[str, dict] = {}
    if args.dataset.exists():
        data = json.loads(args.dataset.read_text())
        for qa in data:
            qid = qa.get("question_id") or qa.get("id")
            if qid:
                ds_index[qid] = qa

    records: list[dict] = []
    for qid in in_scope:
        ba = baseline.get(qid, {})
        ol = older.get(qid, {})
        qa = ds_index.get(qid, {})

        # Override label with V8.3 audit's prior decision if applicable
        if qid in V83_AUDIT_LABELS:
            label, reason = V83_AUDIT_LABELS[qid]
            label_source = "v8.3-audit"
        else:
            label, reason = _classify_heuristic(qa, ba)
            label_source = "heuristic"

        rec = {
            "qid": qid,
            "question_type": qa.get("question_type", "?"),
            "question": qa.get("question", "<unknown>"),
            "gold": str(qa.get("answer", "")),
            "evidence_session_ids": qa.get("answer_session_ids", []),
            "fail_in_baselines": [
                "v822a" if not ba.get("correct", True) else None,
                "v821" if not ol.get("correct", True) else None,
            ],
            "fail_in_baselines": list(filter(None, [
                "v822a" if qid in fails_baseline else None,
                "v821" if qid in fails_older else None,
            ])),
            "v822a_answer_preview": (ba.get("answer") or "")[:300],
            "v822a_verdict_tail": (ba.get("verdict_tail") or "")[:200],
            "label": label,
            "label_source": label_source,
            "reason": reason,
        }
        records.append(rec)

    # Aggregate
    from collections import Counter
    label_counts = Counter(r["label"] for r in records)

    summary = {
        "baseline_file": str(args.baseline),
        "baseline_overall_accuracy": json.loads(args.baseline.read_text()).get("overall_accuracy"),
        "n_in_scope": len(in_scope),
        "label_distribution": dict(label_counts),
        "EXCLUDED_targets": sorted(EXCLUDED),
        "in_scope_qids": in_scope,
    }
    out_payload = {"summary": summary, "records": records}

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out_payload, indent=2, ensure_ascii=False))

    # Console
    print("=" * 78)
    print("LSA-2 LME-S Failure Inventory (V8.2.2a baseline, in-scope)")
    print("=" * 78)
    for r in records:
        fail_in = "+".join(r["fail_in_baselines"])
        print(f"\n  {r['qid']:<22} [{r['question_type']:<25}] {fail_in}")
        print(f"    Q: {r['question'][:90]}")
        print(f"    gold: {r['gold'][:90]}")
        print(f"    label: {r['label']} ({r['label_source']})")
        print(f"    reason: {r['reason']}")
    print()
    print(f"=== Label distribution ===")
    for label, n in sorted(label_counts.items()):
        print(f"  {label:<40}: {n}")
    print(f"\nsaved → {args.out}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
