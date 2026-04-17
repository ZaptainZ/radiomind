"""LoCoMo harness using Mem0's exact protocol.

Dataset: locomo10.json (10 conversations, ~1986 QA pairs across 5 categories).
Mem0 evaluates categories 1-4 (excluding adversarial/cat 5); their v3 number
on LoCoMo is 91.6.

Categories (from mem0ai/memory-benchmarks/benchmarks/locomo/prompts.py):
  1: multi-hop
  2: temporal
  3: open-domain
  4: single-hop
  5: adversarial (skipped by default — answer not in conversation)

Usage:
    python3 bench/end_to_end/run_locomo_mem0.py \\
        --n 200 \\
        --answer-model gpt-4o --answer-profile openai_direct \\
        --judge-model gpt-4o --judge-profile openai_direct \\
        --out bench/end_to_end/locomo-mem0proto.json
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
from datetime import datetime


DATASET = Path("/tmp/locomo-data/locomo10.json")
CATEGORY_NAMES = {1: "multi-hop", 2: "temporal", 3: "open-domain", 4: "single-hop", 5: "adversarial"}
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
            "model": model, "messages": messages,
            "max_tokens": max_tokens, "temperature": 0.0,
        }).encode(),
        headers={
            "Authorization": f"Bearer {oc['api_key']}",
            "Content-Type": "application/json",
        },
    )
    with _BYPASS_PROXY_OPENER.open(req, timeout=120) as r:
        body = json.loads(r.read())
    return body["choices"][0]["message"]["content"].strip()


def parse_locomo_date(s: str) -> str:
    """LoCoMo session_*_date_time comes in formats like '1:56 pm on 8 May, 2023'.
    Convert to ISO so our answer prompt can format it human-readable consistently.
    """
    if not s:
        return ""
    # Try common formats
    for fmt in (
        "%I:%M %p on %d %B, %Y", "%I:%M %p on %d %b, %Y",
        "%H:%M on %d %B, %Y", "%I:%M%p on %d %B, %Y",
    ):
        try:
            dt = datetime.strptime(s.strip(), fmt)
            return dt.strftime("%Y-%m-%dT%H:%M:%S")
        except ValueError:
            continue
    # Try "8 May, 2023" without time
    for fmt in ("%d %B, %Y", "%d %b, %Y"):
        try:
            dt = datetime.strptime(s.strip(), fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return s  # opaque fallback


def build_turns(conversation: dict) -> list[tuple[str, str, str, str]]:
    """Walk conversation sessions, return (session_num, dia_id, iso_date, content)."""
    speaker_a = conversation.get("speaker_a", "")
    speaker_b = conversation.get("speaker_b", "")
    turns: list[tuple[str, str, str, str]] = []
    session_dates: dict[str, str] = {}
    for key, val in conversation.items():
        if key.startswith("session_") and key.endswith("_date_time"):
            session_dates[key.replace("session_", "").replace("_date_time", "")] = parse_locomo_date(val)
    for key, val in conversation.items():
        if not (key.startswith("session_") and not key.endswith("_date_time")):
            continue
        if not isinstance(val, list):
            continue
        snum = key.replace("session_", "")
        sdate = session_dates.get(snum, "")
        for turn in val:
            speaker = turn.get("speaker", "")
            text = turn.get("text", "")
            blip = turn.get("blip_caption", "")
            query = turn.get("query", "")
            if query and blip:
                photo_tag = f"[Sharing image — query: {query}. The image shows: {blip}]"
            elif query:
                photo_tag = f"[Sharing image — query for: {query}]"
            elif blip:
                photo_tag = f"[Sharing image that shows: {blip}]"
            else:
                photo_tag = ""
            combined = f"{text} {photo_tag}".strip() if photo_tag else text
            if not combined:
                continue
            role = "user" if speaker == speaker_a else "assistant"
            dia_id = turn.get("dia_id", "")
            content = f"{speaker}: {combined}"
            turns.append((snum, dia_id, sdate, content))
    return turns


def run(
    sandbox: Path,
    n_questions: int,
    answer_model: str, judge_model: str,
    answer_profile: str, judge_profile: str,
    use_reranker: bool, use_temporal_math: bool, use_agentic: bool,
    categories: tuple[int, ...] = (1, 2, 3, 4),
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
    from mem0_protocol.locomo_prompts import (
        get_answer_generation_prompt, get_judge_prompt, preprocess_answer,
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

    # Flatten and stratify: (conv_idx, qa)
    flat: list[tuple[int, dict]] = []
    for conv_idx, conv in enumerate(data):
        for qa in conv.get("qa", []):
            if qa.get("category") in categories and qa.get("answer") is not None:
                flat.append((conv_idx, qa))

    if n_questions > 0 and n_questions < len(flat):
        import random
        from collections import defaultdict
        by_cat: dict[int, list] = defaultdict(list)
        for x in flat:
            by_cat[x[1].get("category")].append(x)
        rng = random.Random(20260417)
        per = max(1, n_questions // len(by_cat))
        sampled: list = []
        for c, xs in by_cat.items():
            rng.shuffle(xs)
            sampled.extend(xs[:per])
        remaining = n_questions - len(sampled)
        if remaining > 0:
            extra = []
            for c, xs in by_cat.items():
                extra.extend(xs[per:])
            rng.shuffle(extra)
            sampled.extend(extra[:remaining])
        rng.shuffle(sampled)
        flat = sampled[:n_questions]
        print(
            f"  stratified sample: {len(flat)} across {len(by_cat)} categories "
            f"{[(CATEGORY_NAMES.get(c,c), len(xs)) for c,xs in by_cat.items()]}",
            flush=True,
        )

    # Ingest each conversation ONCE, reused across its QAs
    ingested: set[int] = set()
    per_type: dict[str, dict] = {}
    overall = {"n": 0, "correct": 0, "total_ingested_turns": 0}
    per_query_log: list[dict] = []
    t_start = time.time()
    config_path = cfg_src

    for q_idx, (conv_idx, qa) in enumerate(flat):
        domain = f"locomo_{conv_idx}"
        if conv_idx not in ingested:
            conv = data[conv_idx]["conversation"]
            turns = build_turns(conv)
            for snum, dia_id, sdate, content in turns:
                entry = MemoryEntry(
                    content=content, domain=domain, level=MemoryLevel.FACT,
                    metadata={
                        "turn_id": dia_id or f"s{snum}_t0",
                        "session_date": sdate,
                        "session": snum,
                    },
                )
                if mind._embedder:
                    entry.embedding = mind._embedder.encode(content)
                mid = mind._store.add(entry, dedup=False)
                overall["total_ingested_turns"] += 1
                if mind._kg is not None and mid > 0:
                    for subj, rel, obj in mind._kg.extract_triples_from_text(content):
                        mind._kg.add_triple(subj, rel, obj, source_id=mid)
            ingested.add(conv_idx)

        category = qa.get("category")
        question = qa.get("question", "")
        raw_answer = qa.get("answer", "")
        answer_str = str(raw_answer)
        processed_answer = preprocess_answer(category, answer_str)

        # Reference date: use first session date of this conversation
        first_sdate = ""
        for snum, dia_id, sdate, _ in build_turns(data[conv_idx]["conversation"])[:1]:
            first_sdate = sdate
            break
        try:
            ref_dt = datetime.fromisoformat(first_sdate)
            ref_human = ref_dt.strftime("%B %d, %Y")
        except Exception:
            ref_human = "2023"

        # Mem0 uses top_k=200 by default. Match for fair comparison.
        TOP_K = 200
        if use_agentic:
            from radiomind.storage.agentic import agentic_search
            def _llm_fn(prompt: str) -> str:
                return llm_call(prompt, config_path, model=answer_model,
                                 max_tokens=150, profile=answer_profile)
            def _search_fn(q, domain=None, max_results=TOP_K):
                return mind.search(q, domain=domain, max_results=max_results)
            results = agentic_search(
                question, _search_fn, _llm_fn, domain=domain,
                per_subquery_k=50, final_k=TOP_K,
            )
        else:
            results = mind.search(question, domain=domain, max_results=TOP_K)

        mem_results = []
        for r in results[:TOP_K]:
            sdate = (r.entry.metadata or {}).get("session_date", "")
            mem_results.append({
                "memory": r.entry.content,
                "score": float(getattr(r, "score", 0.0)),
                "created_at": sdate,
            })

        ans_prompt = get_answer_generation_prompt(
            question=question, search_results=mem_results,
            reference_date=ref_human,
        )
        try:
            # 1500 tokens leaves room for all 7 reasoning steps + final answer.
            # 500 was too tight — saw truncation mid-Step-4 in smoke tests.
            answer = llm_call(
                ans_prompt, config_path,
                model=answer_model, max_tokens=1500, profile=answer_profile,
            )
        except Exception as e:
            answer = f"[answer error: {e}]"

        judge_prompt = get_judge_prompt(category, question, processed_answer, answer)
        is_correct = False
        verdict = ""
        try:
            # LoCoMo judge returns JSON with reasoning + label. 300 tokens was
            # enough for short reasoning but not for complex cases — bump to 600
            # to be safe.
            verdict = llm_call(
                judge_prompt, config_path,
                model=judge_model, max_tokens=600, profile=judge_profile,
                system="You are evaluating conversational AI memory recall. Return JSON only with the format requested.",
            )
            # Parse JSON {"reasoning":..., "label":"CORRECT"|"WRONG"}
            import re as _re
            m = _re.search(r'"label"\s*:\s*"?(CORRECT|WRONG)', verdict, _re.I)
            if m:
                is_correct = m.group(1).upper() == "CORRECT"
            else:
                # Fallback: if no JSON label found, check last meaningful word
                tail = verdict.lower()[-80:]
                is_correct = ("correct" in tail) and ("wrong" not in tail)
        except Exception as e:
            verdict = f"[judge error: {e}]"

        cat_name = CATEGORY_NAMES.get(category, str(category))
        overall["n"] += 1
        overall["correct"] += int(is_correct)
        per_type.setdefault(cat_name, {"n": 0, "correct": 0})
        per_type[cat_name]["n"] += 1
        per_type[cat_name]["correct"] += int(is_correct)

        per_query_log.append({
            "q": question, "gold": processed_answer, "answer": answer[:2000],
            "correct": is_correct, "category": cat_name,
            "verdict_tail": verdict[-200:],
            "n_retrieved": len(results),
        })

        if (q_idx + 1) % 10 == 0:
            acc = overall["correct"] / overall["n"]
            elapsed = time.time() - t_start
            print(f"  [{q_idx+1}/{len(flat)}] acc={acc:.3f}  t={elapsed:.0f}s", flush=True)

    elapsed = time.time() - t_start
    mind.shutdown()

    return {
        "benchmark": "LoCoMo — Mem0 protocol",
        "protocol": "mem0 prompts; cats 1-4; one ingest per conversation",
        "n_questions": overall["n"],
        "total_ingested_turns": overall["total_ingested_turns"],
        "reranker_enabled": use_reranker,
        "temporal_math": use_temporal_math,
        "agentic": use_agentic,
        "answer_model": answer_model, "judge_model": judge_model,
        "answer_profile": answer_profile, "judge_profile": judge_profile,
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
    p.add_argument("--n", type=int, default=200)
    p.add_argument("--sandbox", default="/tmp/rm-e2e-locomo-mem0")
    p.add_argument("--no-reranker", action="store_true")
    p.add_argument("--temporal-math", action="store_true")
    p.add_argument("--agentic", action="store_true")
    p.add_argument("--categories", default="1,2,3,4")
    p.add_argument("--answer-model", default="gpt-4o")
    p.add_argument("--judge-model", default="gpt-4o")
    p.add_argument("--answer-profile", default="openai_direct")
    p.add_argument("--judge-profile", default="openai_direct")
    p.add_argument("--out", default="bench/end_to_end/locomo-mem0proto.json")
    args = p.parse_args()

    if not DATASET.exists():
        print(f"Dataset missing at {DATASET}")
        return 2

    cats = tuple(int(c) for c in args.categories.split(",") if c)
    print(
        f"Running {args.n or 1540} questions on LoCoMo cats {cats}; "
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
        categories=cats,
    )
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2))

    print(f"\n=== LoCoMo (Mem0 protocol), {report['n_questions']} queries ===")
    print(f"  Overall accuracy: {report['overall_accuracy']:.3f}")
    print(f"  Reranker:         {report['reranker_enabled']}")
    print(f"  Time:             {report['elapsed_s']:.0f}s")
    print("\n  By category:")
    for t, stats in report["by_type"].items():
        print(f"    {t:20s} (n={stats['n']:3d})  acc={stats['accuracy']:.3f}")
    print(f"\n  Saved → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
