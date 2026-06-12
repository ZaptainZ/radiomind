#!/usr/bin/env python3
"""regression_pack.py — deterministic local smoke standard.

Runs a curated, dependency-light subset of the unit suite — the behaviours
the Phase-2 committer/suppressor closures, the arithmetic / person-age hints,
the SelfAnchor store-scans, the JAB abstain veto, and the diagnostic
closure_view depend on — grouped by category, in ONE command:

    ~/.radiomind-bench-venv/bin/python bench/end_to_end/regression_pack.py

Fast (no ingest, no LLM, no benchmark). Run it on every architecture change
as the local gate before committing. Exit 0 iff every category passes.

Coverage is by BEHAVIOUR (the existing faithful-data unit tests + the
closure_view test), not by re-ingesting 10-15 qids — see the regression-pack
log. To add a behaviour to the gate, add its test file under the right
category below.
"""
from __future__ import annotations

import subprocess
import sys
import argparse
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# category -> test files (relative to repo root)
PACK: dict[str, list[str]] = {
    "committer:cashback": [
        "tests/test_cashback_commit_closure.py",
        "tests/test_cashback_closure_field_9aaed6a3.py",
        "tests/test_proof_result_cashback_adapter.py",
    ],
    "committer:age": [
        "tests/test_age_interval_commit.py",
        "tests/test_proof_result_age_adapter.py",
    ],
    "committer:shared-gate": [
        "tests/test_commit_on_abstain.py",
    ],
    "suppressor:role": [
        "tests/test_role_mismatch_guard.py",
    ],
    "suppressor:temporal-endpoint": [
        "tests/test_temporal_endpoint_guard.py",
    ],
    "hint:savings": [
        "tests/test_savings_arithmetic_hint.py",
    ],
    "hint:person-age": [
        "tests/test_typed_event_hint.py",
    ],
    "hint:arithmetic-core": [
        "tests/test_arithmetic_hint.py",
    ],
    "self-anchor": [
        "tests/test_self_anchor.py",
    ],
    "jab:abstain-veto": [
        "tests/test_jab1_abstain_veto.py",
    ],
    "diagnostic:closure-view": [
        "tests/test_closure_view.py",
    ],
    "skill:event-date-parse": [
        "tests/test_event_date_parse.py",
    ],
    "skill:list-ordering": [
        "tests/test_list_ordering_routing.py",
    ],
    "harness:target-pack": [
        "tests/test_target_pack.py",
    ],
    "harness:answer-retry": [
        "tests/test_answer_retry.py",
    ],
    "harness:origin1b-hygiene": [
        "tests/test_origin1b_hygiene.py",
    ],
    "harness:origin3b-dream-flag": [
        "tests/test_origin3b_dream_flag.py",
    ],
    "refinement:dream-merge-role-prefix": [
        "tests/test_dream_merge_role_prefix.py",
    ],
    "harness:rejudge-errors": [
        "tests/test_rejudge_errors.py",
    ],
    "harness:internal-model-flag": [
        "tests/test_internal_model_flag.py",
    ],
    "training:lora-modelfile": [
        "tests/test_lora_modelfile.py",
    ],
    "training:lorafuel-prepare": [
        "tests/test_lorafuel_prepare.py",
    ],
    "harness:devtools": [
        "tests/test_devtools.py",
    ],
    "harness:vr2b-answer-only": [
        "tests/test_vr2b_answer_only.py",
    ],
    "diagnostic:path-summary": [
        "tests/test_path_summary.py",
    ],
    "diagnostic:report": [
        "tests/test_diagnosis_report.py",
    ],
    "diagnostic:stability-report": [
        "tests/test_stability_report.py",
    ],
}


def _run_category(name: str, files: list[str]) -> dict:
    missing = [f for f in files if not (REPO / f).exists()]
    if missing:
        return {"name": name, "ok": False,
                "summary": f"MISSING {missing}", "out": ""}
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *files],
        cwd=REPO, capture_output=True, text=True,
    )
    lines = [ln for ln in proc.stdout.strip().splitlines() if ln.strip()]
    summary = lines[-1] if lines else "(no output)"
    return {"name": name, "ok": proc.returncode == 0,
            "summary": summary, "out": proc.stdout}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run RadioMind's deterministic local regression pack.",
    )
    parser.add_argument(
        "--integration", action="store_true",
        help=("Reserved for future slow diagnose_qid integration checks. "
              "Currently prints a notice and still runs the fast pack."),
    )
    args = parser.parse_args()
    if args.integration:
        print("NOTE: --integration is reserved; no slow ingest/LLM checks "
              "are wired yet. Running the deterministic fast pack only.")
    results = [_run_category(n, f) for n, f in PACK.items()]
    width = max(len(r["name"]) for r in results)
    print("=== RadioMind regression pack ===")
    all_ok = True
    for r in results:
        all_ok = all_ok and r["ok"]
        print(f"  [{'PASS' if r['ok'] else 'FAIL'}] "
              f"{r['name']:<{width}}  {r['summary']}")
    print("=== " + ("ALL PASS" if all_ok else "FAILURES PRESENT") + " ===")
    if not all_ok:
        for r in results:
            if not r["ok"]:
                print(f"\n--- {r['name']} ---\n{r['out']}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
