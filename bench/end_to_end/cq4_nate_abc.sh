#!/usr/bin/env bash
# CQ-4 v2: Nate candidate A/B/C e2e control with HONEST ingest fix.
#
# Single qid: c3_a9fddfe69b. Three variants × N runs each.
# Run 1 of variant A does a FRESH ingest into the shared sandbox;
# every subsequent run uses --reuse-sandbox to skip re-ingest and
# preserve the same retrieved memories. Each variant only changes
# the candidate-block content via RADIOMIND_CQ4_VARIANT env-var.
# evidence_section is recorded in per_query JSON for audit.

set -e
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

N="${1:-3}"
SBX="/tmp/rm-cq4v2-nate-shared"
QIDS="c3_a9fddfe69b"

SUMMARY_FILE="bench/end_to_end/cq4v2-nate-abc-summary.json"
echo "[]" > "$SUMMARY_FILE"

# Fresh sandbox once
rm -rf "$SBX"

for variant in A B C; do
  for i in $(seq 1 "$N"); do
    OUT="bench/end_to_end/cq4v2-nate-${variant}-run${i}.json"
    rm -f "$OUT" "${OUT}.checkpoint.jsonl"
    # First run (A run 1) does the ingest; everything after reuses it.
    REUSE_FLAG=""
    if [ "$variant" != "A" ] || [ "$i" != "1" ]; then
      REUSE_FLAG="--reuse-sandbox"
    fi
    echo "=== CQ-4 v2 variant=$variant run=$i/$N (reuse=$REUSE_FLAG) ==="
    START=$(date +%s)
    RADIOMIND_HOME="$SBX" RADIOMIND_CQ4_VARIANT="$variant" PYTHONPATH="$REPO_ROOT/src" \
      "$REPO_ROOT/.venv312/bin/python" bench/end_to_end/run_locomo_mem0.py \
        --qids "$QIDS" \
        --sandbox "$SBX" \
        $REUSE_FLAG \
        --answer-model deepseek-v3.2 --answer-profile dashscope \
        --judge-model gpt-4o --judge-profile openrouter \
        --out "$OUT" 2>&1 | tail -8
    ELAPSED=$(( $(date +%s) - START ))
    echo "[$variant run $i] elapsed=${ELAPSED}s"

    # Append to summary (now includes evidence_section snippet + dragon flag)
    PYTHONPATH="$REPO_ROOT/src" "$REPO_ROOT/.venv312/bin/python" - <<PY
import json
data = json.load(open("$OUT"))
summary = json.load(open("$SUMMARY_FILE"))
q = data["per_query"][0]
ev = q.get("evidence_section", "") or ""
summary.append({
    "variant": "$variant",
    "run": $i,
    "elapsed_s": $ELAPSED,
    "correct": bool(q.get("correct")),
    "judge_failed": bool(q.get("judge_failed")),
    "evidence_section_len": len(ev),
    "dragon_in_evidence": "dragon" in ev.lower(),
    "answer_preview": (q.get("answer","") or "")[:300],
})
json.dump(summary, open("$SUMMARY_FILE", "w"), indent=2)
PY
    echo
  done
done

# Final table
PYTHONPATH="$REPO_ROOT/src" "$REPO_ROOT/.venv312/bin/python" - <<'PY'
import json
from collections import defaultdict
summary = json.load(open("bench/end_to_end/cq4v2-nate-abc-summary.json"))
by_var = defaultdict(list)
for r in summary:
    by_var[r["variant"]].append(r)
print("=" * 60)
print("CQ-4 v2 Nate A/B/C summary")
print("=" * 60)
print(f"{'variant':<10}{'pass':<10}{'dragon_in_ev':<14}{'avg_elapsed':<14}")
for v in sorted(by_var):
    runs = by_var[v]
    p = sum(1 for r in runs if r["correct"])
    d = sum(1 for r in runs if r["dragon_in_evidence"])
    el = sum(r["elapsed_s"] for r in runs) / max(1, len(runs))
    print(f"{v:<10}{p}/{len(runs):<7}  {d}/{len(runs):<11}  {el:.0f}s")
PY
