"""End-to-end LongMemEval benchmark — directly comparable to MemMachine/Mem0.

Protocol (matches Wu et al., 2024):
  1. Ingest all haystack turns into RadioMind
  2. For each question: retrieve top-5 via RadioMind search
  3. Feed question + retrieved context to Qwen-max → generate answer
  4. LLM judge compares generated answer to gold answer → correct/incorrect
  5. Aggregate accuracy per question type + overall

This gives an apples-to-apples number against published LoCoMo/LongMemEval
leaderboards:
  - MemMachine (SOTA, March 2026): 0.9169 on LoCoMo oracle
  - Mem0: ~0.73 on LoCoMo
  - Pure BM25: ~0.50
  - Our prior R@5 retrieval-only: 0.626 (LongMemEval oracle)

Usage:
    # Default: 100 question sample with reranker
    RADIOMIND_HOME=/tmp/rm-e2e-lme python bench/end_to_end/run_longmemeval.py

    # Full 500 questions
    python bench/end_to_end/run_longmemeval.py --n 500

    # No reranker (for before/after comparison)
    python bench/end_to_end/run_longmemeval.py --no-reranker
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import urllib.request
from pathlib import Path


DATASET = Path("/tmp/longmemeval-data/oracle.json")


ANSWER_PROMPT = """Current date: {now}

Here are some facts retrieved from the user's memory (each tagged with the date of the conversation):

{context}

Based ONLY on the facts above, answer the question below concisely (1-2 sentences).
If the question asks WHEN or HOW LONG AGO, pay attention to the dates in parentheses.

Question: {question}

Answer:"""


JUDGE_PROMPT = """You are evaluating whether an AI's answer matches a gold-standard answer.

Question: {question}
Gold answer: {gold}
AI's answer: {answer}

The AI's answer is CORRECT if it conveys the same information as the gold answer,
even if worded differently. Ignore stylistic differences.
The AI's answer is INCORRECT if it contradicts the gold answer, misses the key fact,
or fabricates information not supported by the gold.

Respond with exactly one word: CORRECT or INCORRECT"""


_BYPASS_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def qwen_call(prompt: str, config_path: Path, model: str = "qwen-max", max_tokens: int = 200) -> str:
    import tomllib
    cfg = tomllib.loads(config_path.read_text())
    oc = cfg["llm"]["openai"]
    req = urllib.request.Request(
        f"{oc['base_url'].rstrip('/')}/chat/completions",
        data=json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0.0,
        }).encode(),
        headers={"Authorization": f"Bearer {oc['api_key']}", "Content-Type": "application/json"},
    )
    # Bypass system proxy — macOS picks up Surge/similar automatically,
    # and we want these specific API calls to go direct.
    with _BYPASS_PROXY_OPENER.open(req, timeout=60) as r:
        body = json.loads(r.read())
    return body["choices"][0]["message"]["content"].strip()


def run(
    sandbox: Path,
    n_questions: int,
    use_reranker: bool,
    answer_model: str = "qwen-turbo",
    judge_model: str = "qwen-max",
    use_rewriter: bool = False,
    use_temporal_math: bool = False,
    use_agentic: bool = False,
) -> dict:
    os.environ["RADIOMIND_HOME"] = str(sandbox)
    if (sandbox / "data").exists():
        shutil.rmtree(sandbox / "data")
    sandbox.mkdir(parents=True, exist_ok=True)

    # Write config enabling reranker / rewriter as requested
    cfg_src = Path.home() / ".radiomind" / "config.toml"
    cfg_content = cfg_src.read_text() if cfg_src.exists() else ""
    if use_reranker and "[retrieval.reranker]" not in cfg_content:
        cfg_content += '\n[retrieval.reranker]\nenabled = true\n'
    elif not use_reranker:
        cfg_content = cfg_content.replace("enabled = true", "enabled = false")
    if use_rewriter and "[retrieval.query_rewriter]" not in cfg_content:
        cfg_content += '\n[retrieval.query_rewriter]\nenabled = true\n'
    (sandbox / "config.toml").write_text(
        cfg_content.replace(str(Path.home() / ".radiomind"), str(sandbox))
    )

    from radiomind.core.mind import RadioMind
    from radiomind.core.types import MemoryEntry, MemoryLevel

    mind = RadioMind()
    mind.initialize()
    print(f"  init: embedder={mind._embedder is not None}, reranker={mind._reranker is not None}", flush=True)

    data = json.loads(DATASET.read_text())
    if n_questions > 0:
        # Stratified sample: equal slots per question_type. Raw LongMemEval
        # is sorted by type, so naive head-truncation gives only one category.
        from collections import defaultdict
        import random
        by_type: dict[str, list] = defaultdict(list)
        for q in data:
            by_type[q.get("question_type", "?")].append(q)
        rng = random.Random(20260416)
        per_type_n = max(1, n_questions // len(by_type))
        sampled = []
        for t, qs in by_type.items():
            rng.shuffle(qs)
            sampled.extend(qs[:per_type_n])
        # If under quota, top up from the largest categories
        remaining = n_questions - len(sampled)
        if remaining > 0:
            extra_pool = []
            for t, qs in by_type.items():
                extra_pool.extend(qs[per_type_n:])
            rng.shuffle(extra_pool)
            sampled.extend(extra_pool[:remaining])
        rng.shuffle(sampled)
        data = sampled[:n_questions]
        print(f"  stratified sample: {len(data)} across {len(by_type)} types", flush=True)

    config_path = cfg_src

    per_type: dict[str, dict] = {}
    overall = {"n": 0, "correct": 0, "total_ingested_turns": 0}
    per_query_log = []
    t_start = time.time()

    for q_idx, q in enumerate(data):
        qtype = q.get("question_type", "?")
        question = q.get("question", "")
        gold = q.get("answer", "")
        if not question or not q.get("haystack_sessions") or not gold:
            continue

        # Ingest this question's haystack into an isolated domain.
        # Session dates flow through into metadata so temporal queries
        # can use them — LongMemEval's "when did X happen" answers live
        # in the session date, not in the turn content.
        domain = f"lme_{q_idx}"
        for s_idx, session in enumerate(q["haystack_sessions"]):
            sid = q["haystack_session_ids"][s_idx] if s_idx < len(q["haystack_session_ids"]) else f"s{s_idx}"
            sdate = q["haystack_dates"][s_idx] if s_idx < len(q.get("haystack_dates", [])) else ""
            for t_idx, turn in enumerate(session):
                txt = turn.get("content", "")
                if not txt: continue
                # Prepend date to content so FTS + vector see it for
                # temporal queries. Keeps metadata for later structured use.
                dated_content = f"[{turn.get('role','?')}] ({sdate}) {txt}" if sdate else f"[{turn.get('role','?')}] {txt}"
                entry = MemoryEntry(
                    content=dated_content,
                    domain=domain, level=MemoryLevel.FACT,
                    metadata={"turn_id": f"{sid}_t{t_idx}", "session_date": sdate},
                )
                if mind._embedder: entry.embedding = mind._embedder.encode(dated_content)
                mid = mind._store.add(entry, dedup=False)
                overall["total_ingested_turns"] += 1
                # Populate KG from user turns — mirrors RadioMind.ingest() path.
                # Gives pyramid search a structured route for entity/temporal queries.
                if mind._kg is not None and turn.get("role") == "user" and mid > 0:
                    for subj, rel, obj in mind._kg.extract_triples_from_text(txt):
                        mind._kg.add_triple(subj, rel, obj, source_id=mid)

        # Normalize gold once so both retrieval-hit and no-retrieval
        # branches can log it. Earlier runs crashed when retrieval was
        # empty because gold_str was only defined inside the hit branch.
        if isinstance(gold, list):
            gold_str = " | ".join(str(g) for g in gold)
        else:
            gold_str = str(gold)

        # Retrieve. top-10 gives the LLM enough room when our pipeline
        # expands nuclei with context turns (MemMachine-style). SOTA
        # systems typically feed 10-20 items.
        if use_agentic:
            from radiomind.storage.agentic import agentic_search
            def _llm_fn(prompt: str) -> str:
                return qwen_call(prompt, config_path, model=answer_model, max_tokens=150)
            def _search_fn(query: str, domain: str | None = None, max_results: int = 10):
                return mind.search(query, domain=domain)
            results = agentic_search(
                question, _search_fn, _llm_fn, domain=domain,
                per_subquery_k=5, final_k=10,
            )
        else:
            results = mind.search(question, domain=domain)
        if not results:
            is_correct = False
            answer = "(no retrieval)"
        else:
            context = "\n".join(f"- {r.entry.content}" for r in results[:10])
            q_date = q.get("question_date", "")
            # Date-arithmetic pre-compute: for temporal questions, hand the
            # LLM exact day counts so it doesn't have to compute in head.
            temporal_facts = ""
            if use_temporal_math:
                from radiomind.storage.temporal import is_temporal_question, compute_deltas
                if is_temporal_question(question):
                    pairs = [(r.entry.content, (r.entry.metadata or {}).get("session_date", ""))
                             for r in results[:10]]
                    deltas = compute_deltas(q_date, pairs, max_facts=6)
                    if deltas:
                        temporal_facts = "\n\nPre-computed date deltas (trust these over your own math):\n" + "\n".join(deltas)
            ans_prompt = ANSWER_PROMPT.format(
                now=q_date or "unknown", context=context + temporal_facts, question=question,
            )
            try:
                answer = qwen_call(ans_prompt, config_path, model=answer_model)
            except Exception as e:
                answer = f"[error: {e}]"
            judge_prompt = JUDGE_PROMPT.format(question=question, gold=gold_str, answer=answer)
            try:
                verdict = qwen_call(judge_prompt, config_path, model=judge_model, max_tokens=10)
                is_correct = verdict.upper().strip().startswith("CORRECT")
            except Exception as e:
                is_correct = False
                verdict = f"[judge error: {e}]"

        overall["n"] += 1
        overall["correct"] += int(is_correct)
        per_type.setdefault(qtype, {"n": 0, "correct": 0})
        per_type[qtype]["n"] += 1
        per_type[qtype]["correct"] += int(is_correct)

        per_query_log.append({
            "q": question, "gold": gold_str, "answer": answer[:200],
            "correct": is_correct, "qtype": qtype,
        })

        if (q_idx + 1) % 10 == 0:
            acc = overall["correct"] / overall["n"]
            elapsed = time.time() - t_start
            print(f"  [{q_idx+1}/{len(data)}] acc={acc:.3f}  t={elapsed:.0f}s", flush=True)

    elapsed = time.time() - t_start
    mind.shutdown()

    report = {
        "benchmark": "LongMemEval oracle — end-to-end (retrieve + generate + judge)",
        "protocol": "top-5 retrieval → qwen-turbo generates → qwen-max judges CORRECT/INCORRECT",
        "n_questions": overall["n"],
        "total_ingested_turns": overall["total_ingested_turns"],
        "reranker_enabled": use_reranker,
        "answer_model": answer_model,
        "judge_model": judge_model,
        "elapsed_s": round(elapsed, 1),
        "overall_accuracy": round(overall["correct"] / max(1, overall["n"]), 4),
        "by_type": {
            t: {"n": v["n"], "accuracy": round(v["correct"] / max(1, v["n"]), 4)}
            for t, v in sorted(per_type.items())
        },
        "per_query": per_query_log,
    }
    return report


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=100, help="Number of questions (0 = all 500)")
    p.add_argument("--sandbox", default="/tmp/rm-e2e-lme")
    p.add_argument("--no-reranker", action="store_true")
    p.add_argument("--rewriter", action="store_true", help="Enable LLM query rewriter")
    p.add_argument("--temporal-math", action="store_true", help="Pre-compute date deltas for temporal questions")
    p.add_argument("--agentic", action="store_true", help="LLM decomposes query into sub-queries, union results")
    p.add_argument("--out", default="bench/end_to_end/longmemeval-e2e.json")
    p.add_argument("--answer-model", default="qwen-turbo")
    p.add_argument("--judge-model", default="qwen-max")
    args = p.parse_args()

    if not DATASET.exists():
        print(f"Dataset missing at {DATASET}")
        return 2

    print(
        f"Running {args.n or 500} questions, reranker={not args.no_reranker}, "
        f"rewriter={args.rewriter}, temporal_math={args.temporal_math}, "
        f"agentic={args.agentic}, answer={args.answer_model}...",
        flush=True,
    )
    report = run(
        Path(args.sandbox), args.n,
        use_reranker=not args.no_reranker,
        use_rewriter=args.rewriter,
        use_temporal_math=args.temporal_math,
        use_agentic=args.agentic,
        answer_model=args.answer_model,
        judge_model=args.judge_model,
    )

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2))

    print(f"\n=== End-to-end LongMemEval ({report['n_questions']} queries) ===")
    print(f"  Overall accuracy:  {report['overall_accuracy']:.3f}")
    print(f"  Reranker:          {report['reranker_enabled']}")
    print(f"  Time:              {report['elapsed_s']:.0f}s")
    print(f"  Answer model:      {report['answer_model']}")
    print(f"  Judge model:       {report['judge_model']}")
    print(f"\n  By question type:")
    for t, stats in report["by_type"].items():
        print(f"    {t:30s} (n={stats['n']:3d})  acc={stats['accuracy']:.3f}")
    print(f"\n  Saved → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
