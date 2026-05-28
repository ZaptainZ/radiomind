"""Rejudge a single qid from an existing n=100 artifact when the
original judge attempt hit a transient infra error.

Reads the artifact, locates the target qid record, re-invokes the
LongMemEval judge prompt with the saved (gold, answer) pair, and
writes the updated correct/verdict back. Also recomputes the
overall accuracy + judge stats.

Used for `75f70248` whose original verdict was SSL EOF after 3
retries — the model answer is real, only the judge call failed.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from run_longmemeval_mem0 import _parse_judge_verdict, llm_call
from mem0_protocol.longmemeval_prompts import JUDGE_PROMPT


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--artifact", type=Path, required=True)
    p.add_argument("--qid", type=str, required=True)
    p.add_argument("--judge-model", default="gpt-4o")
    p.add_argument("--judge-profile", default="openrouter")
    args = p.parse_args()

    if not args.artifact.exists():
        print(f"artifact missing: {args.artifact}", flush=True)
        return 2
    d = json.loads(args.artifact.read_text())
    pq = d["per_query"]
    target = next((r for r in pq if r.get("question_id") == args.qid), None)
    if target is None:
        print(f"qid {args.qid} not in artifact", flush=True)
        return 2

    print(f"=== Rejudging {args.qid} ===")
    print(f"  qtype: {target.get('qtype')}")
    print(f"  gold:   {(target.get('gold') or '')[:200]}")
    print(f"  answer: {(target.get('answer') or '')[:200]}")
    print(f"  prior judge_failed: {target.get('judge_failed')}")
    print(f"  prior correct:      {target.get('correct')}")

    config_path = Path.home() / ".radiomind" / "config.toml"
    judge_prompt = JUDGE_PROMPT.format(
        question=target.get("q", ""),
        answer=target.get("gold", ""),
        response=target.get("answer", ""),
    )
    last_err = None
    new_correct = None
    new_verdict = None
    for attempt in range(3):
        try:
            verdict = llm_call(
                judge_prompt, config_path,
                model=args.judge_model, max_tokens=2000,
                profile=args.judge_profile,
            )
            new_correct = _parse_judge_verdict(verdict)
            new_verdict = verdict
            print(f"  rejudge attempt {attempt+1}: SUCCESS, "
                  f"correct={new_correct}", flush=True)
            break
        except Exception as e:
            last_err = e
            print(f"  rejudge attempt {attempt+1}: ERR {e}", flush=True)
            import time
            time.sleep(2 ** attempt)

    if new_verdict is None:
        print(f"  ALL 3 attempts failed; last err={last_err}",
              flush=True)
        return 3

    # JAB-1a veto re-application
    from jab1_abstain_veto import should_veto
    if new_correct and should_veto(target.get("gold", ""),
                                    target.get("answer", "")):
        new_correct = False
        new_verdict = (new_verdict or "") + (
            "\n[JAB-1a VETO: concrete gold + canonical "
            "abstain response → FAIL]"
        )
        print("  JAB-1a veto applied (concrete gold + abstain)",
              flush=True)

    # Update target record
    target["correct"] = bool(new_correct)
    target["verdict_tail"] = new_verdict[:1000]
    target["judge_failed"] = False
    target["rejudged_2026_05_28"] = True

    # Recompute aggregate
    total = len(pq)
    correct = sum(1 for r in pq if r.get("correct"))
    judge_failed = sum(1 for r in pq if r.get("judge_failed"))
    judge_n = total - judge_failed
    model_correct = correct
    d["overall_accuracy"] = round(correct / total, 4)
    d["judge_errors"] = judge_failed
    d["judge_n"] = judge_n
    d["model_correct"] = model_correct
    d["judged_n"] = judge_n
    d["judged_accuracy"] = (
        round(model_correct / judge_n, 4) if judge_n else None
    )
    # by_question_type stays the same logically (this rec was
    # already in there via count + correct delta, but accuracy
    # may shift); just recompute fresh.
    from collections import Counter
    per_type_n = Counter(r.get("qtype", "?") for r in pq)
    per_type_correct = Counter(
        r.get("qtype", "?") for r in pq if r.get("correct")
    )
    d["by_question_type"] = {
        k: {"n": per_type_n[k], "correct": per_type_correct[k]}
        for k in per_type_n
    }

    args.artifact.write_text(
        json.dumps(d, indent=2, ensure_ascii=False),
    )
    print(f"\n=== Updated artifact ===")
    print(f"  raw accuracy: {correct}/{total} = {correct/total:.4f}")
    print(f"  judge_failed: {judge_failed}")
    print(f"  judge_n: {judge_n}")
    print(f"  judged_accuracy: {model_correct}/{judge_n} = "
          f"{model_correct/judge_n:.4f}" if judge_n else "n/a")
    print(f"\nwritten → {args.artifact}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
