#!/usr/bin/env bash
# CQ-4: Nate candidate A/B/C e2e control.
#
# Single qid: c3_a9fddfe69b. Three variants × N runs each.
# Same sandbox is RE-USED across all 9 runs so retrieved
# memories stay identical (single ingest, multiple answer
# passes). Each variant only changes the candidate-block
# content via RADIOMIND_CQ4_VARIANT env-var.

set -e
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

N="${1:-3}"
SBX="/tmp/rm-cq4-nate-shared"
QIDS="c3_a9fddfe69b"

# Fresh shared sandbox for the first run only; reuse on subsequent runs.
# Mark fresh by removing data dir; the harness rebuilds it on next run.
SUMMARY_FILE="bench/end_to_end/cq4-nate-abc-summary.json"
echo "[]" > "$SUMMARY_FILE"

for variant in A B C; do
  for i in $(seq 1 "$N"); do
    OUT="bench/end_to_end/cq4-nate-${variant}-run${i}.json"
    rm -f "$OUT" "${OUT}.checkpoint.jsonl"
    # Only wipe sandbox on the very first run; subsequent runs reuse
    # the ingested store, so retrieved memories are deterministic.
    if [ "$variant" = "A" ] && [ "$i" = "1" ]; then
      rm -rf "$SBX"
    fi
    echo "=== CQ-4 variant=$variant run=$i/$N ==="
    START=$(date +%s)
    RADIOMIND_HOME="$SBX" RADIOMIND_CQ4_VARIANT="$variant" PYTHONPATH="$REPO_ROOT/src" \
      "$REPO_ROOT/.venv312/bin/python" bench/end_to_end/run_locomo_mem0.py \
        --qids "$QIDS" \
        --sandbox "$SBX" \
        --answer-model deepseek-v3.2 --answer-profile dashscope \
        --judge-model gpt-4o --judge-profile openrouter \
        --out "$OUT" 2>&1 | tail -8
    ELAPSED=$(( $(date +%s) - START ))
    echo "[$variant run $i] elapsed=${ELAPSED}s"

    # Append to summary
    PYTHONPATH="$REPO_ROOT/src" "$REPO_ROOT/.venv312/bin/python" - <<PY
import json
data = json.load(open("$OUT"))
summary = json.load(open("$SUMMARY_FILE"))
q = data["per_query"][0]
summary.append({
    "variant": "$variant",
    "run": $i,
    "elapsed_s": $ELAPSED,
    "correct": bool(q.get("correct")),
    "judge_failed": bool(q.get("judge_failed")),
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
summary = json.load(open("bench/end_to_end/cq4-nate-abc-summary.json"))
by_var = defaultdict(list)
for r in summary:
    by_var[r["variant"]].append(r)
print("=" * 60)
print("CQ-4 Nate A/B/C summary")
print("=" * 60)
print(f"{'variant':<10}{'pass':<10}{'total':<10}{'avg_elapsed_s':<15}")
for v in sorted(by_var):
    runs = by_var[v]
    p = sum(1 for r in runs if r["correct"])
    el = sum(r["elapsed_s"] for r in runs) / max(1, len(runs))
    print(f"{v:<10}{p}/{len(runs):<7}        {el:.0f}s")
PY
