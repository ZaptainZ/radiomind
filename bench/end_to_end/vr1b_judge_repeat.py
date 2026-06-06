"""VR-1b — judge-only repeat experiment (read-only measurement).

Quantifies gpt-4o/OpenRouter judge non-determinism by re-judging a FIXED
(question, gold, answer) triple N times. NO ingest, NO answer generation, NO
n=100, NO runtime/scoring change — it only re-calls the judge on frozen inputs
pulled from existing artifacts and reuses the runner's own judge code.

Usage:
  ~/.radiomind-bench-venv/bin/python bench/end_to_end/vr1b_judge_repeat.py \
      --repeats 10 --out bench/end_to_end/vr1b-judge-repeat.json

Per qid it reports: the yes/no sequence, yes_rate, a stable/FLIP label,
shannon entropy, and judge_failed count. swing qids vs stable controls tell us
whether judge variance is a real lever (→ VR-1d N-judge) or negligible (→ the
0.910 wobble is answer/ingest-side instead).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from run_longmemeval_mem0 import llm_call, _parse_judge_verdict  # noqa: E402
from mem0_protocol.longmemeval_prompts import JUDGE_PROMPT  # noqa: E402

CONFIG = Path.home() / ".radiomind" / "config.toml"
BASELINE = Path("bench/end_to_end/lme-s-n100-2026-06-04-baseline.json")
REP1 = Path("bench/end_to_end/v611-rep1.json")

# qid -> role. answer is taken from BASELINE unless overridden below.
PLAN = {
    # swing (observed flips in full-run repeats)
    "9ee3ecd6":      "swing",
    "1c0ddc50":      "swing",
    "gpt4_194be4b3": "swing",
    "d3ab962e":      "swing",
    # stable PASS controls (correct in BOTH baseline and V6.1.1)
    "e9327a54":      "ctrl-pass",
    "caf9ead2":      "ctrl-pass",
    # stable FAIL controls (incorrect in BOTH)
    "b46e15ed":      "ctrl-fail",
    "778164c6":      "ctrl-fail",
}

# 9ee3ecd6: use the EXACT answer text that produced yes/yes/no across full-run
# repeats (byte-identical answer, different verdict) — the cleanest pure-judge
# noise probe. Pulled from v611-rep1.
ANSWER_OVERRIDE = {"9ee3ecd6": ("REP1", "answer")}


def _load_triples() -> dict:
    base = {r["question_id"]: r
            for r in json.loads(BASELINE.read_text())["per_query"]}
    rep1 = {r["question_id"]: r
            for r in json.loads(REP1.read_text())["per_query"]}
    triples = {}
    for qid in PLAN:
        src = base[qid]
        answer = src["answer"]
        note = "baseline answer"
        if qid in ANSWER_OVERRIDE:
            answer = rep1[qid]["answer"]
            note = "v611-rep1 flip-probe answer (byte-identical text that flipped)"
        triples[qid] = {
            "question": src["q"], "gold": src["gold"],
            "answer": answer, "answer_source": note,
            "role": PLAN[qid], "qtype": src.get("qtype"),
        }
    return triples


def _entropy(yes: int, n: int) -> float:
    if n == 0:
        return 0.0
    p = yes / n
    if p in (0.0, 1.0):
        return 0.0
    return -(p * math.log2(p) + (1 - p) * math.log2(1 - p))


def _judge_once(question: str, gold: str, answer: str,
                model: str, profile: str) -> tuple[bool, bool]:
    """Returns (is_correct, judge_failed). Mirrors the runner's judge call."""
    prompt = JUDGE_PROMPT.format(question=question, answer=gold, response=answer)
    try:
        verdict = llm_call(prompt, CONFIG, model=model, max_tokens=2000,
                           profile=profile)
        return _parse_judge_verdict(verdict), False
    except Exception:
        return False, True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repeats", type=int, default=10)
    ap.add_argument("--judge-model", default="gpt-4o")
    ap.add_argument("--judge-profile", default="openrouter")
    ap.add_argument("--only", default="",
                    help="Comma-separated qids to restrict to (e.g. extend 9ee3ecd6 to 20x).")
    ap.add_argument("--out", type=Path,
                    default=Path("bench/end_to_end/vr1b-judge-repeat.json"))
    args = ap.parse_args()

    triples = _load_triples()
    only = set(x for x in args.only.split(",") if x)
    if only:
        triples = {q: v for q, v in triples.items() if q in only}

    rows = []
    for qid, t in triples.items():
        seq, fails = [], 0
        for _ in range(args.repeats):
            ok, jf = _judge_once(t["question"], t["gold"], t["answer"],
                                 args.judge_model, args.judge_profile)
            if jf:
                fails += 1
            else:
                seq.append("Y" if ok else "N")
        n = len(seq)
        yes = seq.count("Y")
        yes_rate = round(yes / n, 3) if n else None
        flip = "STABLE" if (n and (yes == 0 or yes == n)) else "FLIP"
        row = {
            "qid": qid, "role": t["role"], "qtype": t["qtype"],
            "answer_source": t["answer_source"],
            "n_judged": n, "judge_failed": fails,
            "yes_seq": "".join(seq), "yes_rate": yes_rate,
            "label": flip, "entropy_bits": round(_entropy(yes, n), 3),
            "gold": str(t["gold"])[:80], "answer": t["answer"][:120],
        }
        rows.append(row)
        print(f"  {qid:<14} {t['role']:<10} [{row['yes_seq']:<{args.repeats}}] "
              f"yes_rate={yes_rate} {flip} ent={row['entropy_bits']} "
              f"jf={fails}")

    out = {"repeats": args.repeats, "judge_model": args.judge_model,
           "judge_profile": args.judge_profile, "rows": rows}
    args.out.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"saved → {args.out}")

    swing_flip = [r for r in rows if r["role"] == "swing" and r["label"] == "FLIP"]
    ctrl_flip = [r for r in rows if r["role"].startswith("ctrl") and r["label"] == "FLIP"]
    print(f"\nswing FLIP: {len(swing_flip)}/{sum(1 for r in rows if r['role']=='swing')}"
          f"  | control FLIP: {len(ctrl_flip)}/{sum(1 for r in rows if r['role'].startswith('ctrl'))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
