#!/usr/bin/env python3
"""target_pack.py — small REAL e2e pack (distinct from regression_pack.py).

Runs a curated set of representative LongMemEval qids through the FULL runner
(ingest + answer-LLM + judge) to confirm the helpers / closures / skills still
behave under real ingest + LLM trust/retrieval jitter — what the fast
deterministic regression pack cannot cover.

This is the HEAVY gate: ~50-session ingest + LLM + judge per qid → run it
MANUALLY after key-path changes, NOT on every commit, and NOT inside the
default regression pack.

  # run the full pack (real ingest+LLM+judge — slow, authorized use):
  ~/.radiomind-bench-venv/bin/python bench/end_to_end/target_pack.py
  # just re-summarize an existing result json (fast, no run):
  ~/.radiomind-bench-venv/bin/python bench/end_to_end/target_pack.py --report <out.json>

`mode` separates `required` (gates the exit code) from `observe_only`
(parked/deferred lines — reported but never turn the pack red).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# qid -> {line, mode}. mode: "required" gates exit code; "observe_only" is
# reported but never fails the pack (parked / deferred lines).
MANIFEST: dict[str, dict] = {
    # ---- required gates ----
    "031748ae_abs":      {"line": "role-suppressor",        "mode": "required"},
    "gpt4_93159ced_abs": {"line": "tesg-suppressor",        "mode": "required"},
    "gpt4_93159ced":     {"line": "tesg-negative-anchor",   "mode": "required"},
    "9aaed6a3":          {"line": "cashback-committer",     "mode": "required"},
    "bb7c3b45":          {"line": "savings-hint",           "mode": "required"},
    "gpt4_d12ceb0e":     {"line": "person-age-hint",        "mode": "required"},
    "c18a7dc8":          {"line": "age-interval-committer", "mode": "required"},
    "d851d5ba":          {"line": "nar-charity-sum",        "mode": "required"},
    # ---- observe-only (parked / deferred — never reds the pack) ----
    "gpt4_7abb270c":     {"line": "ordered-event-list",     "mode": "observe_only"},
    "b46e15ed":          {"line": "event-cluster-interval", "mode": "observe_only"},
}

_SANDBOX = "/tmp/rm-sandbox-target-pack"


def summarize(per_query: list, manifest: dict) -> dict:
    """Pure: classify each manifest qid's runner result. Returns a structured
    summary; `required_all_pass` ignores observe_only qids entirely."""
    by_qid = {}
    for rec in (per_query or []):
        if isinstance(rec, dict):
            qid = rec.get("question_id") or rec.get("qid")
            if qid is not None:
                by_qid[qid] = rec

    rows = []
    for qid, meta in manifest.items():
        present = qid in by_qid
        correct = bool(by_qid.get(qid, {}).get("correct")) if present else False
        rows.append({
            "qid": qid,
            "line": meta["line"],
            "mode": meta["mode"],
            "present": present,
            "correct": correct,
            # a missing required qid is a failure; a missing observe is just noted
            "ok": correct if present else False,
        })

    required = [r for r in rows if r["mode"] == "required"]
    observe = [r for r in rows if r["mode"] == "observe_only"]
    return {
        "rows": rows,
        "required": required,
        "observe": observe,
        "required_pass": sum(1 for r in required if r["ok"]),
        "required_total": len(required),
        "observe_pass": sum(1 for r in observe if r["ok"]),
        "observe_total": len(observe),
        "required_all_pass": all(r["ok"] for r in required),
    }


def _print(summary: dict) -> None:
    def line(r):
        mark = "PASS" if r["ok"] else ("MISSING" if not r["present"] else "FAIL")
        return f"  [{mark:>7}] {r['qid']:<18} {r['line']}"
    print("=== target-pack (REAL e2e) ===")
    print("-- required (gates exit code) --")
    for r in summary["required"]:
        print(line(r))
    print("-- observe-only (never reds the pack) --")
    for r in summary["observe"]:
        print(line(r))
    print(f"=== required {summary['required_pass']}/{summary['required_total']} "
          f"| observe {summary['observe_pass']}/{summary['observe_total']} "
          f"| GATE {'PASS' if summary['required_all_pass'] else 'FAIL'} ===")


def _load_per_query(path: Path) -> list:
    d = json.loads(Path(path).read_text())
    return d.get("per_query") or d.get("results") or []


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report", type=Path, default=None,
                    help="Summarize an existing runner result json; do not run.")
    ap.add_argument("--out", type=Path,
                    default=REPO / "bench/end_to_end/target-pack-result.json")
    ap.add_argument("--answer-model", default="deepseek-v3.2")
    ap.add_argument("--answer-profile", default="dashscope")
    ap.add_argument("--judge-model", default="gpt-4o")
    ap.add_argument("--judge-profile", default="openrouter")
    args = ap.parse_args()

    if args.report:
        _print(summarize(_load_per_query(args.report), MANIFEST))
        return 0  # report mode never gates

    qids = ",".join(MANIFEST)
    cmd = [
        sys.executable, "bench/end_to_end/run_longmemeval_mem0.py",
        "--qids", qids, "--sandbox", _SANDBOX,
        "--answer-model", args.answer_model, "--answer-profile", args.answer_profile,
        "--judge-model", args.judge_model, "--judge-profile", args.judge_profile,
        "--out", str(args.out),
    ]
    print("running:", " ".join(cmd), flush=True)
    env = {**__import__("os").environ, "RADIOMIND_HOME": _SANDBOX}
    rc = subprocess.run(cmd, cwd=REPO, env=env).returncode
    if rc != 0:
        print(f"runner exited {rc}")
        return 2
    summary = summarize(_load_per_query(args.out), MANIFEST)
    _print(summary)
    return 0 if summary["required_all_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
