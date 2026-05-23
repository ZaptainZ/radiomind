#!/usr/bin/env bash
# SC-2: target pack repeat (4 LME-S qids x N runs, default 3).
#
# Usage: ./sc2_target_pack_repeat.sh [N=3]
#
# Each batch ~50-60 min. Default 3 runs ~ 2.5-3 hours.
# Per-run sandbox: /tmp/rm-sc2-target-pack/runK
# Per-run output: bench/end_to_end/sc2-target-pack-runK.json
# Summary       : bench/end_to_end/sc2-target-pack-matrix.json

set -e
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

N="${1:-3}"
QIDS="031748ae_abs,9aaed6a3,gpt4_d12ceb0e,d851d5ba"
SUMMARY="bench/end_to_end/sc2-target-pack-matrix.json"
echo "[]" > "$SUMMARY"

for i in $(seq 1 "$N"); do
  echo "=== SC-2 run $i/$N ==="
  SBX="/tmp/rm-sc2-target-pack/run$i"
  OUT="bench/end_to_end/sc2-target-pack-run$i.json"
  rm -rf "$SBX" "$OUT" "${OUT}.checkpoint.jsonl"
  mkdir -p "$SBX"
  START=$(date +%s)
  RADIOMIND_HOME="$SBX" PYTHONPATH="$REPO_ROOT/src" \
    "$REPO_ROOT/.venv312/bin/python" bench/end_to_end/run_longmemeval_mem0.py \
      --qids "$QIDS" \
      --sandbox "$SBX" \
      --answer-model deepseek-v3.2 --answer-profile dashscope \
      --judge-model gpt-4o --judge-profile openrouter \
      --out "$OUT" 2>&1 | tail -8
  ELAPSED=$(( $(date +%s) - START ))
  echo "[run $i] elapsed=${ELAPSED}s"

  # Append per_query results to summary JSON
  PYTHONPATH="$REPO_ROOT/src" "$REPO_ROOT/.venv312/bin/python" - <<PY
import json
data = json.load(open("$OUT"))
summary = json.load(open("$SUMMARY"))
summary.append({
    "run": $i,
    "elapsed_s": $ELAPSED,
    "per_qid": {p["question_id"]: {"correct": bool(p.get("correct")),
                                    "judge_failed": bool(p.get("judge_failed"))}
                for p in data.get("per_query", [])},
})
json.dump(summary, open("$SUMMARY", "w"), indent=2)
PY
  echo
done

# Final aggregate
PYTHONPATH="$REPO_ROOT/src" "$REPO_ROOT/.venv312/bin/python" - <<'PY'
import json
summary = json.load(open("bench/end_to_end/sc2-target-pack-matrix.json"))
qids = ["031748ae_abs", "9aaed6a3", "gpt4_d12ceb0e", "d851d5ba"]
print("=" * 60)
print("SC-2 SUMMARY")
print("=" * 60)
print(f"{'qid':<22} " + " ".join(f"run{r['run']:<4}" for r in summary)
      + " | pass-rate")
for qid in qids:
    cells = []
    n_pass = 0
    for r in summary:
        info = r["per_qid"].get(qid)
        if info is None:
            cells.append("---")
        else:
            mark = "PASS" if info["correct"] else "FAIL"
            cells.append(mark)
            n_pass += int(info["correct"])
    print(f"{qid:<22} " + " ".join(f"{c:<5}" for c in cells)
          + f"| {n_pass}/{len(summary)}")
total_pass = sum(int(r["per_qid"].get(qid, {}).get("correct", False))
                 for r in summary for qid in qids)
total = len(summary) * len(qids)
print()
print(f"OVERALL: {total_pass}/{total} ({100*total_pass/total:.1f}%)")
PY
