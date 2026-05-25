"""LSA-3: Existing-Path Regression Audit.

For each of 3 target qids (LSA-2 marked needs_retrieve_probe
or commit_variance), check on current main:

  - Whether gold-bearing memory enters retrieve top-K (with
    runner's TOP_K=200).
  - Whether existing typed-event / numeric / temporal skills
    fire on the query.
  - Whether existing role-mismatch / abstain guard would
    cover the presupposition case.

This is read-only audit — no new helper, no new skill. The
output decides whether each qid is:

  - A genuine regression of an existing path (FIX RECOMMENDED
    in a separate workstream).
  - A retrieval-recall-bridging case (out of LSA scope).
  - A commit-side / calibration issue (separate workstream).

Single fresh sandbox; ingest each qid's haystack once.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


DATASET = Path.home() / "Library/Caches/radiomind-data/longmemeval_s_cleaned.json"

TARGETS = [
    ("c18a7dc8", "needs_retrieve_probe / age_delta — historical PASS via age_interval/anchor"),
    ("b46e15ed", "needs_retrieve_probe / months-since-charity — historical PASS via infra fix"),
    ("gpt4_93159ced_abs", "commit_variance / Google presupposition — gold=abstain, LLM committed"),
]


def _ingest_qid(mind, target: dict, domain: str) -> int:
    turns: list[dict] = []
    for s_idx, session in enumerate(target["haystack_sessions"]):
        sid = (target["haystack_session_ids"][s_idx]
               if s_idx < len(target.get("haystack_session_ids", []))
               else f"s{s_idx}")
        sdate = (target["haystack_dates"][s_idx]
                 if s_idx < len(target.get("haystack_dates", []))
                 else "")
        for t_idx, turn in enumerate(session):
            content = turn.get("content", "")
            if not content:
                continue
            turns.append({
                "role": turn.get("role", "?"),
                "content": f"[{turn.get('role','?')}] {content}",
                "metadata": {
                    "turn_id": f"{sid}_t{t_idx}",
                    "session_date": sdate,
                    "role": turn.get("role", "?"),
                },
            })
    stats = mind.ingest_turns_raw(
        turns, domain=domain, run_aggregation=True, run_refinement=False,
    )
    return stats["ingested"]


def _probe_retrieve(mind, question: str, domain: str, gold_session_ids: list[str],
                    top_k: int = 200) -> dict:
    results = mind.search(question, domain=domain, max_results=top_k)
    hits = []
    gold_hits = 0
    gold_ranks: list[int] = []
    for i, r in enumerate(results, 1):
        entry = getattr(r, "entry", r)
        content = getattr(entry, "content", "") or ""
        meta = getattr(entry, "metadata", {}) or {}
        if not isinstance(meta, dict):
            meta = {}
        tid = meta.get("turn_id", "")
        # turn_id is "<session_id>_t<n>"
        session_id = tid.rsplit("_t", 1)[0] if "_t" in tid else ""
        is_gold = session_id in gold_session_ids
        if is_gold:
            gold_hits += 1
            gold_ranks.append(i)
        hits.append({
            "rank": i,
            "turn_id": tid,
            "is_gold_session": is_gold,
            "score": getattr(r, "score", None),
            "content_preview": content[:140],
        })
    return {
        "top_k": top_k,
        "total_returned": len(results),
        "gold_session_ids": gold_session_ids,
        "gold_hits_in_top_k": gold_hits,
        "gold_ranks_first_5": gold_ranks[:5],
        "top_10_hits": hits[:10],
        # full hits omitted to keep JSON compact; sample first 30
        "sample_hits_11_to_30": hits[10:30],
    }


def _probe_skills(mind, question: str, retrieved_memories: list,
                  qid: str) -> dict:
    """Check which existing helpers / skills would fire on this query."""
    out: dict = {}

    # role_mismatch_guard
    try:
        from radiomind.core.role_mismatch_guard import role_mismatch_guard
        r = role_mismatch_guard(question, retrieved_memories)
        out["role_mismatch_guard"] = bool(r)
        out["role_mismatch_guard_block"] = (r[:200] if r else "")
    except Exception as e:
        out["role_mismatch_guard_err"] = str(e)

    # cashback_arithmetic_hint
    try:
        from radiomind.core.arithmetic_hint import cashback_arithmetic_hint
        out["cashback_hint"] = bool(cashback_arithmetic_hint(question, retrieved_memories))
    except Exception as e:
        out["cashback_hint_err"] = str(e)

    # person_age_average_hint
    try:
        from radiomind.core.typed_event_hint import person_age_average_hint
        out["person_age_hint"] = bool(person_age_average_hint(question, retrieved_memories))
    except Exception as e:
        out["person_age_hint_err"] = str(e)

    # numeric cardinal view
    try:
        cv = mind.get_numeric_cardinal(query=question, domain="")
        out["numeric_cardinal_fires"] = bool(cv)
        out["numeric_cardinal_preview"] = (cv[:300] if cv else "")
    except Exception as e:
        out["numeric_cardinal_err"] = str(e)

    # evidence_candidates
    try:
        ec = mind.run_evidence_candidates(query=question,
                                           retrieved_memories=retrieved_memories)
        out["evidence_candidates_fires"] = bool(ec)
        out["evidence_candidates_preview"] = (ec[:400] if ec else "")
    except Exception as e:
        out["evidence_candidates_err"] = str(e)

    # temporal precision / open-domain
    for method in ("run_temporal_precision", "run_open_domain_specific"):
        if hasattr(mind, method):
            try:
                r = getattr(mind, method)(query=question,
                                           retrieved_memories=retrieved_memories,
                                           reference_date="2025-01-01",
                                           domain="")
                out[f"{method}_fires"] = bool(r)
                out[f"{method}_preview"] = (str(r)[:200] if r else "")
            except Exception as e:
                out[f"{method}_err"] = str(e)
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--sandbox", type=Path,
                   default=Path("/tmp/rm-lsa3-existing-path"))
    p.add_argument("--out", type=Path,
                   default=Path("bench/end_to_end/lsa3-existing-path-audit.json"))
    args = p.parse_args()

    if args.sandbox.exists():
        shutil.rmtree(args.sandbox)
    args.sandbox.mkdir(parents=True, exist_ok=True)
    os.environ["RADIOMIND_HOME"] = str(args.sandbox)

    # Copy config from default
    cfg_src = Path.home() / ".radiomind" / "config.toml"
    cfg_content = cfg_src.read_text()
    (args.sandbox / "config.toml").write_text(
        cfg_content.replace(str(Path.home() / ".radiomind"), str(args.sandbox))
    )

    config_path = args.sandbox / "config.toml"
    from run_longmemeval_mem0 import llm_call

    def _internal_llm(prompt: str, system: str = "") -> str:
        return llm_call(
            prompt, config_path,
            model="deepseek-v3.2", max_tokens=2500,
            profile="dashscope", system=(system or None),
        )

    from radiomind.core.mind import RadioMind
    mind = RadioMind(llm=_internal_llm)
    mind.initialize()

    data = json.loads(DATASET.read_text())
    by_qid = {q.get("question_id") or q.get("id"): q for q in data}

    records: list[dict] = []
    for qid, lsa2_label in TARGETS:
        print(f"\n=== {qid} ({lsa2_label}) ===", flush=True)
        target = by_qid.get(qid)
        if not target:
            print(f"  qid not found in dataset", flush=True)
            records.append({"qid": qid, "error": "qid_not_in_dataset"})
            continue

        question = target["question"]
        gold = str(target.get("answer"))
        gold_ids = list(target.get("answer_session_ids", []))
        domain = f"lsa3_{qid}"
        print(f"  Q: {question[:100]}", flush=True)
        print(f"  gold: {gold[:100]}", flush=True)
        print(f"  gold session ids: {gold_ids}", flush=True)
        print(f"  ingesting...", flush=True)
        try:
            n_ingested = _ingest_qid(mind, target, domain)
            print(f"  ingested {n_ingested} turns", flush=True)
        except Exception as e:
            print(f"  ingest FAILED: {e}", flush=True)
            records.append({"qid": qid, "error": f"ingest_failed: {e}"})
            continue

        retrieve = _probe_retrieve(mind, question, domain, gold_ids, top_k=200)
        print(f"  gold turns in top-{retrieve['top_k']}: "
              f"{retrieve['gold_hits_in_top_k']} (first 5 ranks: "
              f"{retrieve['gold_ranks_first_5']})", flush=True)

        # Build mem_results structure for skill probes
        results_for_skills = mind.search(question, domain=domain, max_results=30)
        skill = _probe_skills(mind, question, results_for_skills, qid)
        print(f"  skill fires:", flush=True)
        for k in ("role_mismatch_guard", "cashback_hint", "person_age_hint",
                  "numeric_cardinal_fires", "evidence_candidates_fires"):
            v = skill.get(k)
            print(f"    {k}: {v}", flush=True)

        records.append({
            "qid": qid,
            "lsa2_label": lsa2_label,
            "question": question,
            "gold": gold,
            "gold_session_ids": gold_ids,
            "domain": domain,
            "ingested_turns": n_ingested,
            "retrieve": retrieve,
            "skills": skill,
        })

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"records": records},
                                    indent=2, ensure_ascii=False))
    print(f"\nsaved → {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
