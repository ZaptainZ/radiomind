"""LongMemEval-S harness using Mem0's exact protocol.

Why this file exists separately from run_longmemeval.py:
- Dataset: longmemeval_s_cleaned.json (~47.7 sessions/q, ~493 turns/q) — the
  true haystack benchmark Mem0 reports 93.4 on. Our earlier run_longmemeval.py
  used oracle.json (~1.9 sessions/q) which is a much easier setting.
- Prompts: answer+judge are ported verbatim from mem0ai/memory-benchmarks so
  any score difference vs their 93.4 is attributable to the memory system,
  not prompt wording. Our earlier one-line judge under-reports by ~10 pt.
- Answer format: LLM is instructed to use <mem_thinking> tags; we strip
  those before showing the answer to the judge.

Usage:
    python3 bench/end_to_end/run_longmemeval_mem0.py \\
        --n 30 \\
        --answer-profile openai_direct --answer-model gpt-4o \\
        --judge-profile openai_direct  --judge-model gpt-4o \\
        --out bench/end_to_end/lme-s-mem0proto-n30.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
import urllib.request
from pathlib import Path


DATASET = Path("/tmp/longmemeval-data/longmemeval_s_cleaned.json")

_BYPASS_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def llm_call(
    prompt: str, config_path: Path,
    model: str = "gpt-4o", max_tokens: int = 800,
    profile: str = "openai", system: str | None = None,
) -> str:
    import tomllib
    cfg = tomllib.loads(config_path.read_text())
    oc = cfg["llm"][profile]
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    req = urllib.request.Request(
        f"{oc['base_url'].rstrip('/')}/chat/completions",
        data=json.dumps({
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.0,
        }).encode(),
        headers={
            "Authorization": f"Bearer {oc['api_key']}",
            "Content-Type": "application/json",
        },
    )
    with _BYPASS_PROXY_OPENER.open(req, timeout=120) as r:
        body = json.loads(r.read())
    return body["choices"][0]["message"]["content"].strip()


_THINK_PATTERN = re.compile(r"<mem_thinking>[\s\S]*?</mem_thinking>", re.IGNORECASE)
_FINAL_VERDICT_RE = re.compile(
    r"(?:final\s+verdict|verdict|answer)\s*[:：]\s*[\"'`]?(yes|no)\b",
    re.IGNORECASE,
)


def _parse_judge_verdict(verdict: str) -> bool:
    """Parse 'yes' / 'no' from a Mem0 LongMemEval judge response.

    Mem0's judge template asks for step-by-step in <judge_thinking> tags
    then final verdict "yes"/"no" on a new line after the closing tag.
    Observed qwen deviations (seen on n=30 run):
      1. Closes </judge_thinking> with no verdict line after (put verdict
         inside the thinking block as "Final verdict: yes").
      2. Forgets the tags entirely and writes "Verdict: yes" inline.
      3. Correct format (expected).

    We try them in order; first definitive match wins. Conservative default
    is False so an ambiguous judge doesn't inflate accuracy.
    """
    if not verdict:
        return False
    low = verdict.lower()

    # 1. Line immediately after </judge_thinking>
    if "</judge_thinking>" in low:
        tail = low.split("</judge_thinking>", 1)[1].strip()
        first_tok = tail.split()[0] if tail.split() else ""
        if first_tok.startswith("yes"):
            return True
        if first_tok.startswith("no"):
            return False

    # 2. "Final verdict: yes" / "Verdict: yes" / "Answer: yes" anywhere
    m = _FINAL_VERDICT_RE.search(verdict)
    if m:
        return m.group(1).lower() == "yes"

    # 3. Last non-empty line that's a clean "yes"/"no"
    lines = [ln.strip() for ln in verdict.strip().splitlines() if ln.strip()]
    for ln in reversed(lines):
        ll = ln.lower()
        if ll in ("yes", "no"):
            return ll == "yes"

    # 4. Conservative default
    return False


def strip_thinking(text: str) -> str:
    """Remove <mem_thinking>...</mem_thinking> blocks from the answer.

    Mem0's answer prompt instructs the LLM to reason inside <mem_thinking>
    tags and produce a final answer outside. The judge should only see
    the final answer. If the LLM forgets to close the tag we keep content
    after the last </mem_thinking>, or fall back to the whole text.
    """
    without_blocks = _THINK_PATTERN.sub("", text).strip()
    if without_blocks:
        return without_blocks
    # Fallback: take everything after last </mem_thinking>
    idx = text.rfind("</mem_thinking>")
    if idx >= 0:
        return text[idx + len("</mem_thinking>"):].strip()
    # Or: strip open-only tag
    idx = text.rfind("<mem_thinking>")
    if idx >= 0:
        return text[:idx].strip() or text.strip()
    return text.strip()


def run(
    sandbox: Path,
    n_questions: int,
    answer_model: str,
    judge_model: str,
    answer_profile: str,
    judge_profile: str,
    use_reranker: bool,
    use_temporal_math: bool,
    use_agentic: bool,
    use_refinement: bool = True,
) -> dict:
    os.environ["RADIOMIND_HOME"] = str(sandbox)
    if (sandbox / "data").exists():
        shutil.rmtree(sandbox / "data")
    sandbox.mkdir(parents=True, exist_ok=True)

    cfg_src = Path.home() / ".radiomind" / "config.toml"
    cfg_content = cfg_src.read_text()
    if use_reranker and "[retrieval.reranker]" not in cfg_content:
        cfg_content += "\n[retrieval.reranker]\nenabled = true\n"
    elif not use_reranker:
        cfg_content = cfg_content.replace("enabled = true", "enabled = false")
    (sandbox / "config.toml").write_text(
        cfg_content.replace(str(Path.home() / ".radiomind"), str(sandbox))
    )

    sys.path.insert(0, str(Path(__file__).parent))
    from mem0_protocol.longmemeval_prompts import (
        get_answer_generation_prompt, JUDGE_PROMPT,
    )

    from radiomind.core.mind import RadioMind
    from radiomind.core.types import MemoryEntry, MemoryLevel

    mind = RadioMind()
    mind.initialize()
    print(
        f"  init: embedder={mind._embedder is not None}, "
        f"reranker={mind._reranker is not None}",
        flush=True,
    )

    data = json.loads(DATASET.read_text())
    if n_questions > 0:
        from collections import defaultdict
        import random
        by_type: dict[str, list] = defaultdict(list)
        for q in data:
            by_type[q.get("question_type", "?")].append(q)
        rng = random.Random(20260416)
        per_type_n = max(1, n_questions // len(by_type))
        sampled: list = []
        for t, qs in by_type.items():
            rng.shuffle(qs)
            sampled.extend(qs[:per_type_n])
        remaining = n_questions - len(sampled)
        if remaining > 0:
            extra = []
            for t, qs in by_type.items():
                extra.extend(qs[per_type_n:])
            rng.shuffle(extra)
            sampled.extend(extra[:remaining])
        rng.shuffle(sampled)
        data = sampled[:n_questions]
        print(
            f"  stratified sample: {len(data)} across {len(by_type)} types",
            flush=True,
        )

    config_path = cfg_src

    per_type: dict[str, dict] = {}
    overall = {"n": 0, "correct": 0, "total_ingested_turns": 0}
    per_query_log: list[dict] = []
    t_start = time.time()

    for q_idx, q in enumerate(data):
        qtype = q.get("question_type", "?")
        question = q.get("question", "")
        gold = q.get("answer", "")
        if not question or not q.get("haystack_sessions"):
            continue

        domain = f"lme_{q_idx}"
        # Flatten question's haystack into a list of turn dicts for
        # ingest_turns_raw, which runs the full pipeline: store + KG +
        # Meta + aggregation + optional three-body refinement. Previous
        # version bypassed this by calling mind._store.add directly,
        # which meant patterns/principles/habits never got built — the
        # benchmark was measuring only L2 raw-turn retrieval.
        turns: list[dict] = []
        for s_idx, session in enumerate(q["haystack_sessions"]):
            sid = (q["haystack_session_ids"][s_idx]
                   if s_idx < len(q.get("haystack_session_ids", []))
                   else f"s{s_idx}")
            sdate = (q["haystack_dates"][s_idx]
                     if s_idx < len(q.get("haystack_dates", []))
                     else "")
            for t_idx, turn in enumerate(session):
                txt = turn.get("content", "")
                if not txt:
                    continue
                turns.append({
                    "role": turn.get("role", "?"),
                    "content": f"[{turn.get('role','?')}] {txt}",
                    "metadata": {
                        "turn_id": f"{sid}_t{t_idx}",
                        "session_date": sdate,
                        "role": turn.get("role", "?"),
                    },
                })
        stats = mind.ingest_turns_raw(
            turns, domain=domain,
            run_aggregation=True,
            # Three-body debate fires once per question's domain. Each
            # adds ~1 LLM round-trip total (all 3 speakers run in parallel
            # inside chat.refine). Worth it: upgrades raw facts into
            # PRINCIPLE-level summaries that pyramid.search surfaces first.
            run_refinement=use_refinement,
        )
        overall["total_ingested_turns"] += stats["ingested"]

        if isinstance(gold, list):
            gold_str = " | ".join(str(g) for g in gold)
        else:
            gold_str = str(gold)

        # Mem0 retrieves top_k=200 (their default), because on haystack data
        # the answer-bearing memory is often beyond top-10. Match their depth
        # for a fair comparison. Answer prompt will still slice to top 200.
        TOP_K = 200
        if use_agentic:
            from radiomind.storage.agentic import agentic_search
            def _llm_fn(prompt: str) -> str:
                return llm_call(prompt, config_path, model=answer_model,
                                 max_tokens=150, profile=answer_profile)
            def _search_fn(query: str, domain=None, max_results=TOP_K):
                return mind.search(query, domain=domain, max_results=max_results)
            results = agentic_search(
                question, _search_fn, _llm_fn, domain=domain,
                per_subquery_k=50, final_k=TOP_K,
            )
        else:
            results = mind.search(question, domain=domain, max_results=TOP_K)

        # Build Mem0-format search_results: memory / score / created_at
        mem_results = []
        for r in results[:TOP_K]:
            sdate = (r.entry.metadata or {}).get("session_date", "")
            mem_results.append({
                "memory": r.entry.content,
                "score": float(getattr(r, "score", 0.0)),
                "created_at": sdate,
            })

        q_date = q.get("question_date", "")
        ans_prompt = get_answer_generation_prompt(
            question=question, search_results=mem_results, question_date=q_date or "",
        )
        try:
            raw_answer = llm_call(
                ans_prompt, config_path,
                model=answer_model, max_tokens=800, profile=answer_profile,
            )
            answer = strip_thinking(raw_answer)
        except Exception as e:
            answer = f"[answer error: {e}]"

        judge_prompt = JUDGE_PROMPT.format(
            question=question, answer=gold_str, response=answer,
        )
        is_correct = False
        verdict = ""
        try:
            # 1200 tokens: Mem0's judge asks for step-by-step in <judge_thinking>
            # followed by "yes"/"no" on a new line. 300 tokens truncated the
            # reasoning before the verdict (seen as 0% on n=30 smoke run).
            verdict = llm_call(
                judge_prompt, config_path,
                model=judge_model, max_tokens=1200, profile=judge_profile,
            )
            is_correct = _parse_judge_verdict(verdict)
        except Exception as e:
            verdict = f"[judge error: {e}]"

        overall["n"] += 1
        overall["correct"] += int(is_correct)
        per_type.setdefault(qtype, {"n": 0, "correct": 0})
        per_type[qtype]["n"] += 1
        per_type[qtype]["correct"] += int(is_correct)

        per_query_log.append({
            "q": question, "gold": gold_str, "answer": answer[:400],
            "correct": is_correct, "qtype": qtype, "verdict_tail": verdict[-120:],
        })

        if (q_idx + 1) % 10 == 0:
            acc = overall["correct"] / overall["n"]
            elapsed = time.time() - t_start
            print(
                f"  [{q_idx+1}/{len(data)}] acc={acc:.3f}  t={elapsed:.0f}s",
                flush=True,
            )

    elapsed = time.time() - t_start
    mind.shutdown()

    return {
        "benchmark": "LongMemEval-S (cleaned) — Mem0 protocol",
        "protocol": "mem0 prompts; haystack = ~47.7 sessions/q",
        "n_questions": overall["n"],
        "total_ingested_turns": overall["total_ingested_turns"],
        "reranker_enabled": use_reranker,
        "temporal_math": use_temporal_math,
        "agentic": use_agentic,
        "answer_model": answer_model,
        "judge_model": judge_model,
        "answer_profile": answer_profile,
        "judge_profile": judge_profile,
        "elapsed_s": round(elapsed, 1),
        "overall_accuracy": round(overall["correct"] / max(1, overall["n"]), 4),
        "by_type": {
            t: {"n": v["n"], "accuracy": round(v["correct"] / max(1, v["n"]), 4)}
            for t, v in sorted(per_type.items())
        },
        "per_query": per_query_log,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=30)
    p.add_argument("--sandbox", default="/tmp/rm-e2e-lme-s-mem0")
    p.add_argument("--no-reranker", action="store_true")
    p.add_argument("--temporal-math", action="store_true",
                   help="Our date-arithmetic module (off by default — Mem0 doesn't use it)")
    p.add_argument("--agentic", action="store_true",
                   help="Our agentic decomposition (off by default — Mem0 doesn't use it)")
    p.add_argument("--no-refinement", action="store_true",
                   help="Skip three-body chat refinement at ingest (default on — builds L3 principles)")
    p.add_argument("--answer-model", default="gpt-4o")
    p.add_argument("--judge-model", default="gpt-4o")
    p.add_argument("--answer-profile", default="openai_direct")
    p.add_argument("--judge-profile", default="openai_direct")
    p.add_argument("--out", default="bench/end_to_end/lme-s-mem0proto.json")
    args = p.parse_args()

    if not DATASET.exists():
        print(f"Dataset missing at {DATASET}")
        return 2

    print(
        f"Running {args.n or 500} questions on LongMemEval-S cleaned; "
        f"answer={args.answer_model}/{args.answer_profile}, "
        f"judge={args.judge_model}/{args.judge_profile}; "
        f"reranker={not args.no_reranker}, temporal_math={args.temporal_math}, "
        f"agentic={args.agentic}",
        flush=True,
    )

    report = run(
        Path(args.sandbox), args.n,
        answer_model=args.answer_model, judge_model=args.judge_model,
        answer_profile=args.answer_profile, judge_profile=args.judge_profile,
        use_reranker=not args.no_reranker,
        use_temporal_math=args.temporal_math,
        use_agentic=args.agentic,
        use_refinement=not args.no_refinement,
    )

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2))

    print(f"\n=== LongMemEval-S (Mem0 protocol), {report['n_questions']} questions ===")
    print(f"  Overall accuracy: {report['overall_accuracy']:.3f}")
    print(f"  Reranker:         {report['reranker_enabled']}")
    print(f"  Time:             {report['elapsed_s']:.0f}s")
    print(f"  Answer model:     {report['answer_model']} ({report['answer_profile']})")
    print(f"  Judge model:      {report['judge_model']} ({report['judge_profile']})")
    print("\n  By question type:")
    for t, stats in report["by_type"].items():
        print(f"    {t:30s} (n={stats['n']:3d})  acc={stats['accuracy']:.3f}")
    print(f"\n  Saved → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
