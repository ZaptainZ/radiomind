#!/usr/bin/env bash
# LCR-1: LoCoMo flip10 run 2 + run 3 to disambiguate the SC-3 single-run 4/10.
#
# Usage: ./lcr1_locomo_flip10_repeat.sh [START_IDX=2] [END_IDX=3]
#
# Each run ~2.5-2.7h sequential. Per-run sandbox + JSON.

set -e
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

START="${1:-2}"
END="${2:-3}"
QIDS="c1_69a7c9bffe,c2_29183ecb5e,c2_b4b43181aa,c3_2656e2c771,c3_94f06e1a00,c3_a9fddfe69b,c4_5cfba98ae8,c5_dac00a436e,c6_9da9f73c2a,c9_5ab522b5c7"

for i in $(seq "$START" "$END"); do
  echo "=== LCR-1 LoCoMo run $i ==="
  SBX="/tmp/rm-sc3-locomo-flip10-run$i"
  OUT="bench/end_to_end/sc3-locomo-flip10-run$i.json"
  rm -rf "$SBX" "$OUT" "${OUT}.checkpoint.jsonl"
  mkdir -p "$SBX"
  START_T=$(date +%s)
  RADIOMIND_HOME="$SBX" PYTHONPATH="$REPO_ROOT/src" \
    "$REPO_ROOT/.venv312/bin/python" bench/end_to_end/run_locomo_mem0.py \
      --qids "$QIDS" \
      --sandbox "$SBX" \
      --answer-model deepseek-v3.2 --answer-profile dashscope \
      --judge-model gpt-4o --judge-profile openrouter \
      --out "$OUT" 2>&1 | tail -15
  ELAPSED=$(( $(date +%s) - START_T ))
  echo "[run $i] elapsed=${ELAPSED}s"

  # Also run strict_judge for parity with SC-3 run 1
  PYTHONPATH="$REPO_ROOT/src" "$REPO_ROOT/.venv312/bin/python" \
    bench/end_to_end/strict_judge.py "$OUT" 2>&1 | tail -15
  echo
done

# 3-run aggregate
echo "=== LCR-1 3-RUN AGGREGATE ==="
PYTHONPATH="$REPO_ROOT/src" "$REPO_ROOT/.venv312/bin/python" - <<'PY'
import json
from pathlib import Path
rows = []
for i in (1, 2, 3):
    p = Path(f"bench/end_to_end/sc3-locomo-flip10-run{i}.json")
    if p.exists():
        d = json.loads(p.read_text())
        ok = sum(1 for q in d["per_query"] if q.get("correct"))
        rows.append((i, ok, len(d["per_query"])))
print(f"{'run':<6}{'pass':<8}{'total':<8}")
for r in rows:
    print(f"{r[0]:<6}{r[1]:<8}{r[2]:<8}")
if rows:
    mean = sum(r[1] for r in rows) / len(rows)
    print(f"\nmean: {mean:.2f}/10  (V8.2.1 historical mean = 5.80/10, range 5-7)")
PY
