"""LCO read-only audit: structured diagnostic JSON for a LoCoMo qid.

For each qid produces a machine-readable record of:
  - question + gold answer + gold evidence ids
  - default search top-K hits (rank, turn_id, score, preview)
  - gold evidence rank in default search
  - (optional --agentic) sub-queries generated + agentic top-K hits + gold ranks

Read-only: never invokes the answer LLM or mutates the sandbox.

Usage:
    python bench/end_to_end/lco_audit.py \
        --qid c3_2656e2c771 \
        --sandbox /tmp/rm-sc3-locomo-flip10 \
        --top-k 30 \
        --out bench/end_to_end/lco-audit-c3-count.json

  --agentic enables sub-query decomposition (requires dashscope LLM).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path


def _locate_qid(dataset: Path, qid: str) -> tuple[int, dict] | None:
    data = json.loads(dataset.read_text())
    for conv_idx, conv in enumerate(data):
        for qa in conv.get("qa", []):
            q = qa.get("question", "")
            h = hashlib.md5(q.encode()).hexdigest()[:10]
            if f"c{conv_idx}_{h}" == qid:
                return conv_idx, qa
            # Also try c{conv_idx-1} for legacy 1-indexed conv labels
            if f"c{conv_idx - 1}_{h}" == qid:
                return conv_idx, qa
    return None


def _entry_record(rank: int, r) -> dict:
    entry = getattr(r, "entry", r)
    content = getattr(entry, "content", "") or ""
    meta = getattr(entry, "metadata", {}) or {}
    if not isinstance(meta, dict):
        meta = {}
    return {
        "rank": rank,
        "turn_id": meta.get("turn_id", ""),
        "session_date": meta.get("session_date", ""),
        "score": getattr(r, "score", None),
        "method": getattr(r, "method", None),
        "content_preview": content[:160],
    }


def _gold_ranks(hits: list[dict], gold_ids: list[str]) -> dict[str, int | None]:
    out = {gid: None for gid in gold_ids}
    for h in hits:
        tid = h["turn_id"]
        if tid in out and out[tid] is None:
            out[tid] = h["rank"]
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--qid", required=True)
    p.add_argument("--sandbox", type=Path, required=True)
    p.add_argument("--dataset", type=Path,
                   default=Path.home() / "Library/Caches/radiomind-data/locomo10.json")
    p.add_argument("--top-k", type=int, default=30)
    p.add_argument("--agentic", action="store_true",
                   help="Also run agentic_search (requires dashscope LLM).")
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()

    if not args.dataset.exists():
        print(f"dataset missing: {args.dataset}", file=sys.stderr)
        return 2
    if not (args.sandbox / "data").exists():
        print(f"sandbox missing or empty: {args.sandbox}", file=sys.stderr)
        return 2

    located = _locate_qid(args.dataset, args.qid)
    if located is None:
        print(f"qid not found: {args.qid}", file=sys.stderr)
        return 2
    conv_idx, qa = located
    question = qa["question"]
    gold = qa.get("answer", "")
    gold_ids = list(qa.get("evidence") or [])
    category = qa.get("category")

    domain = f"locomo_{conv_idx}"
    print(f"=== {args.qid} | domain={domain} ===", flush=True)
    print(f"  Q: {question}", flush=True)
    print(f"  gold: {gold}", flush=True)
    print(f"  evidence: {gold_ids}", flush=True)

    # Set sandbox + import mind
    os.environ["RADIOMIND_HOME"] = str(args.sandbox)
    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
    from radiomind.core.mind import RadioMind  # noqa: WPS433
    mind = RadioMind(llm=lambda p, s="": "")
    mind.initialize()

    # Default search
    default_results = mind.search(question, domain=domain, max_results=args.top_k)
    default_hits = [_entry_record(i + 1, r) for i, r in enumerate(default_results)]
    default_gold_ranks = _gold_ranks(default_hits, gold_ids)

    record: dict = {
        "qid": args.qid,
        "question": question,
        "gold_answer": gold,
        "gold_evidence_ids": gold_ids,
        "category": category,
        "domain": domain,
        "default_search": {
            "top_k": args.top_k,
            "hits": default_hits,
            "gold_ranks": default_gold_ranks,
            "gold_in_top_k_count": sum(
                1 for v in default_gold_ranks.values() if v is not None
            ),
            "gold_in_top_k_total": len(gold_ids),
        },
    }

    if args.agentic:
        # Wire dashscope llm via runner's llm_call
        from run_locomo_mem0 import llm_call  # noqa: WPS433
        config_path = args.sandbox / "config.toml"

        def _llm(prompt: str, system: str = "") -> str:
            return llm_call(
                prompt, config_path, model="deepseek-v3.2",
                profile="dashscope", max_tokens=400,
                system=(system or None),
            )

        from radiomind.storage.agentic import (  # noqa: WPS433
            agentic_search, decompose_question,
        )
        sub_queries = decompose_question(question, _llm)

        def _search(q, domain=None, max_results=10):
            return mind.search(q, domain=domain, max_results=max_results)

        agentic_results = agentic_search(
            question, _search, _llm, domain=domain,
            per_subquery_k=10, final_k=args.top_k,
        )
        agentic_hits = [_entry_record(i + 1, r) for i, r in enumerate(agentic_results)]
        agentic_gold_ranks = _gold_ranks(agentic_hits, gold_ids)
        record["agentic_search"] = {
            "sub_queries": sub_queries,
            "per_subquery_k": 10,
            "final_k": args.top_k,
            "hits": agentic_hits,
            "gold_ranks": agentic_gold_ranks,
            "gold_in_top_k_count": sum(
                1 for v in agentic_gold_ranks.values() if v is not None
            ),
            "gold_in_top_k_total": len(gold_ids),
        }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(record, indent=2, ensure_ascii=False))

    # Print summary
    print(f"\n=== default search summary ===", flush=True)
    print(f"  gold in top-{args.top_k}: "
          f"{record['default_search']['gold_in_top_k_count']}/{len(gold_ids)}", flush=True)
    for gid, rank in default_gold_ranks.items():
        print(f"    {gid}: rank={rank}", flush=True)
    if args.agentic:
        print(f"\n=== agentic search summary ===", flush=True)
        print(f"  sub-queries ({len(record['agentic_search']['sub_queries'])}):", flush=True)
        for sq in record["agentic_search"]["sub_queries"]:
            print(f"    - {sq!r}", flush=True)
        print(f"  gold in top-{args.top_k}: "
              f"{record['agentic_search']['gold_in_top_k_count']}/{len(gold_ids)}", flush=True)
        for gid, rank in agentic_gold_ranks.items():
            print(f"    {gid}: rank={rank}", flush=True)
    print(f"\nsaved → {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
