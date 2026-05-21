"""Re-judge qids whose verdict was a judge-infra error.

When OpenRouter returns 403 / SSL EOF / Connection reset, the bench
default-counts the question as FAIL. This script rejudges only those
specific qids, leaving the model answer intact. Used to recover the
true model_accuracy from a polluted bench run.

Usage:
    python bench/end_to_end/rejudge_errors.py <bench_result.json>

Writes <bench_result.judge-fixed.json> with updated correct + verdict
fields for the previously errored qids.
"""
from __future__ import annotations

import json
import os
import sys
import time
import tomllib
import urllib.request
from pathlib import Path


_BYPASS_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


# Mem0 LME-S judge prompt (verbatim from bench)
JUDGE_PROMPT = (
    "Your job is to judge whether the LLM's response correctly answers the "
    "user's question, given a gold reference answer.\n\n"
    "Question: {question}\n"
    "Gold answer: {answer}\n"
    "LLM response: {response}\n\n"
    "Output ONLY 'yes' if the LLM response captures the gold answer's "
    "meaning, or 'no' otherwise. Brief reasoning then yes/no on the last line."
)


def llm_call(prompt: str, profile_cfg: dict, model: str,
             max_tokens: int = 600, timeout: int = 60) -> str:
    req = urllib.request.Request(
        f"{profile_cfg['base_url'].rstrip('/')}/chat/completions",
        data=json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens, "temperature": 0.0,
        }).encode(),
        headers={
            "Authorization": f"Bearer {profile_cfg['api_key']}",
            "Content-Type": "application/json",
        },
    )
    with _BYPASS_PROXY_OPENER.open(req, timeout=timeout) as r:
        body = json.loads(r.read())
    return body["choices"][0]["message"]["content"].strip()


def parse_verdict(verdict: str) -> bool:
    """Match bench's _parse_judge_verdict heuristics."""
    tail = verdict.lower()[-80:]
    if "yes" in tail and "no" not in tail.split("yes")[-1][:20]:
        return True
    if tail.rstrip().endswith("yes"):
        return True
    if tail.rstrip().endswith("no"):
        return False
    return "yes" in tail and tail.rfind("yes") > tail.rfind("no")


def main():
    if len(sys.argv) < 2:
        print("Usage: rejudge_errors.py <bench_result.json>")
        sys.exit(1)

    in_path = Path(sys.argv[1])
    data = json.loads(in_path.read_text())

    cfg_path = Path.home() / ".radiomind" / "config.toml"
    cfg = tomllib.loads(cfg_path.read_text())
    judge_profile_name = data.get("judge_profile", "openrouter")
    judge_model = data.get("judge_model", "gpt-4o")
    profile = cfg["llm"][judge_profile_name]

    n_rejudged = 0
    n_flipped_pass = 0
    n_flipped_fail = 0
    for r in data["per_query"]:
        verdict_tail = r.get("verdict_tail", "")
        if not ("[judge error" in verdict_tail or "403" in verdict_tail):
            continue
        n_rejudged += 1
        q = r["q"]
        gold = r["gold"]
        ans = r["answer"]
        prompt = JUDGE_PROMPT.format(question=q, answer=gold, response=ans)
        # Up to 3 attempts
        verdict = ""
        for attempt in range(3):
            try:
                verdict = llm_call(prompt, profile, judge_model, max_tokens=600)
                break
            except Exception as e:
                print(f"  {r['question_id']} attempt {attempt+1} failed: {e}")
                if attempt < 2:
                    time.sleep(2 ** attempt)
        if not verdict:
            print(f"  {r['question_id']} STILL UNJUDGED after retries")
            continue
        new_correct = parse_verdict(verdict)
        old_correct = r["correct"]
        r["correct"] = new_correct
        r["verdict_tail"] = "[REJUDGED] " + verdict[-100:]
        if "judge_failed" in r:
            r["judge_failed"] = False
        if new_correct and not old_correct:
            n_flipped_pass += 1
            mark = "FAIL→PASS"
        elif not new_correct and old_correct:
            n_flipped_fail += 1
            mark = "PASS→FAIL"
        else:
            mark = "no change"
        print(f"  {r['question_id']}: {mark}  gold={gold[:40]}  verdict={verdict[-60:]}")

    # Recompute aggregates
    n = len(data["per_query"])
    n_correct = sum(1 for r in data["per_query"] if r.get("correct"))
    data["overall_accuracy"] = round(n_correct / max(1, n), 4)
    data["raw_accuracy"] = data["overall_accuracy"]
    # If split fields exist, recompute too
    if "model_correct" in data:
        # Now all rejudged are model_correct or not. judge_errors should be 0 if all retried
        data["model_correct"] = n_correct  # all judged now
        data["judged_n"] = sum(1 for r in data["per_query"]
                                if not r.get("judge_failed"))
        data["judge_errors"] = sum(1 for r in data["per_query"]
                                    if r.get("judge_failed"))
        data["judged_accuracy"] = round(
            n_correct / max(1, data["judged_n"]), 4
        )
        data["judge_error_rate"] = round(
            data["judge_errors"] / max(1, n), 4
        )

    out_path = in_path.with_suffix(".judge-fixed.json")
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print()
    print(f"Rejudged {n_rejudged} qids: {n_flipped_pass} FAIL→PASS, "
          f"{n_flipped_fail} PASS→FAIL, {n_rejudged - n_flipped_pass - n_flipped_fail} no change")
    print(f"New overall_accuracy: {data['overall_accuracy']} = {n_correct}/{n}")
    print(f"Saved → {out_path}")


if __name__ == "__main__":
    main()
