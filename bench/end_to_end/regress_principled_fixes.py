"""Target test for 3 real regressions from lme-s-n100-post-refactor.json.

Runs the same bench harness path (full ingest → retrieve → cardinal →
temporal_resolver → decompose → answer → judge) on just these qids:

  - 2311e44b_abs (Sapiens abstention) — Fix 1 (decomposer evidence guard)
  - gpt4_b0863698 (5K days ago)       — Fix 2+3 (answer_shape, temporal_resolver)
  - gpt4_1916e0ea (54 days between)   — Fix 3 (temporal_resolver)

Expects all three to PASS. Cheap (~3 questions × ~3 min = 10 min, ~$3).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from run_longmemeval_mem0 import llm_call, _parse_judge_verdict  # noqa: E402


def _question_id(q: dict, idx: int) -> str:
    return q.get("question_id") or f"q{idx}"

TARGET_QIDS = {
    "2311e44b_abs": "Sapiens abstention",
    "gpt4_b0863698": "5K days ago",
    "gpt4_1916e0ea": "54 days between",
}

DATASET = Path(
    os.environ.get(
        "RADIOMIND_LME_S_DATASET",
        str(Path.home() / "Library/Caches/radiomind-data/longmemeval_s_cleaned.json"),
    )
)


def main() -> int:
    sandbox = Path(tempfile.mkdtemp(prefix="rm-principled-"))
    os.environ["RADIOMIND_HOME"] = str(sandbox)
    cfg_src = Path.home() / ".radiomind" / "config.toml"
    cfg_dst = sandbox / "config.toml"
    if cfg_src.exists():
        cfg_dst.write_text(
            cfg_src.read_text().replace(str(Path.home() / ".radiomind"), str(sandbox))
        )
    answer_model = "openai/gpt-4o"
    profile = "openrouter"

    def _llm(prompt, system=""):
        return llm_call(prompt, cfg_dst, model=answer_model, max_tokens=2500,
                        profile=profile, system=(system or None))

    sys.path.insert(0, str(Path(__file__).parent))
    from mem0_protocol.longmemeval_prompts import (  # noqa: E402
        get_answer_generation_prompt, JUDGE_PROMPT,
    )
    from radiomind import RadioMind

    data = json.loads(DATASET.read_text())
    by_qid = {_question_id(q, i): (i, q) for i, q in enumerate(data)}

    results = []
    for qid, label in TARGET_QIDS.items():
        if qid not in by_qid:
            print(f'SKIP {qid}: not found')
            continue
        idx, q = by_qid[qid]
        question = q["question"]
        gold = q["answer"]
        q_date = q.get("question_date", "")
        print(f'\n{"="*70}\n[{qid}] {label}\n{"="*70}')
        print(f'Q: {question[:120]}')
        print(f'GOLD: {gold[:120]}')

        mind = RadioMind(llm=_llm)
        mind.initialize()
        domain = f"lme_{idx}"
        turns = []
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
        print(f'ingesting {len(turns)} turns...', flush=True)
        mind.ingest_turns_raw(turns, domain=domain,
                              run_aggregation=False, run_refinement=False)

        # Retrieve
        search_results = mind.search(question, domain=domain, max_results=200)
        mem_results = []
        for r in search_results:
            sdate = (r.entry.metadata or {}).get("session_date", "")
            mem_results.append({
                "memory": r.entry.content, "score": float(getattr(r, "score", 0.0)),
                "created_at": sdate,
            })

        # Route attention
        cardinal_section = ""
        try:
            cardinal_section = mind.get_numeric_cardinal(query=question, domain=domain, user_id="")
        except Exception:
            pass
        temporal_section = ""
        open_domain_section = ""
        try:
            temporal_section = mind.run_temporal_precision(
                query=question, retrieved_memories=mem_results, reference_date=q_date or "",
            )
        except Exception:
            pass
        try:
            open_domain_section = mind.run_open_domain_specific(
                query=question, retrieved_memories=mem_results,
            )
        except Exception:
            pass
        atomic_section = ""
        try:
            if not cardinal_section:
                atoms = mind.decompose_for_query(
                    query=question, retrieved=search_results[:30], domain=domain, promote=False,
                )
                if atoms:
                    lines = ["DRAFT ATOMIC VIEW (VERIFY against memories):"]
                    for a in atoms[:15]:
                        count_tag = f" [×{a.count}]" if a.count > 1 else ""
                        lines.append(f'- {a.fact}{count_tag} (conf {a.confidence:.2f})')
                    atomic_section = "\n".join(lines) + "\n\n"
        except Exception:
            pass

        # Report which sections fired (diagnostic)
        print(f'  sections: card={bool(cardinal_section)} tmp={bool(temporal_section)} '
              f'odm={bool(open_domain_section)} atm={bool(atomic_section)}')
        if temporal_section:
            print(f'  TEMPORAL: {temporal_section.strip()[:300]}')

        ans_prompt = get_answer_generation_prompt(
            question=question, search_results=mem_results, question_date=q_date or "",
        )
        for sec in (atomic_section, cardinal_section, temporal_section, open_domain_section):
            if sec:
                ans_prompt = sec + ans_prompt
        try:
            answer = llm_call(ans_prompt, cfg_dst, model=answer_model,
                              max_tokens=1500, profile=profile)
        except Exception as e:
            answer = f"[answer error: {e}]"
        print(f'ANSWER: {answer[:200]}')

        # Judge
        from mem0_protocol.longmemeval_prompts import get_judge_prompt
        qtype = q.get("question_type", "")
        judge_prompt = get_judge_prompt(
            question_type=qtype, question_id=qid,
            question=question, answer=gold, response=answer,
            question_date=q_date or "",
        )
        try:
            verdict = llm_call(judge_prompt, cfg_dst, model=answer_model,
                               max_tokens=1200, profile=profile)
            correct = _parse_judge_verdict(verdict)
        except Exception as e:
            verdict = f"[judge error: {e}]"
            correct = False
        print(f'VERDICT: {"PASS" if correct else "FAIL"}')
        results.append((qid, label, correct))
        mind.shutdown()

    print(f'\n{"="*70}\nSUMMARY')
    for qid, label, c in results:
        print(f'  {qid} ({label}): {"PASS" if c else "FAIL"}')
    passes = sum(1 for _, _, c in results if c)
    print(f'\n{passes}/{len(results)} PASS')
    return 0


if __name__ == "__main__":
    sys.exit(main())
