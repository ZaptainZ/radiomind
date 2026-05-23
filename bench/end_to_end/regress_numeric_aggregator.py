"""Targeted regression: does NumericAggregator fix the 5 multi-session errors?

Loads the exact 5 LME-S questions that failed in lme-s-FINAL-gpt4o-n100.json
due to aggregation miscounts, ingests each question's haystack the same way
the benchmark harness does, then checks what NumericAggregator surfaces.

Runs WITHOUT the answer/judge LLM — directly inspects the cardinal view.
If the cardinal is correct, the downstream LLM will almost certainly
answer correctly (at least for the number).

Usage:
    python bench/end_to_end/regress_numeric_aggregator.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

# Make the bench harness's llm_call + config available to the regression.
sys.path.insert(0, str(Path(__file__).parent))
from run_longmemeval_mem0 import llm_call  # noqa: E402


TARGET_QIDS = {
    "gpt4_194be4b3": "How many musical instruments do I currently own?",
    "d851d5ba": "How much money did I raise for charity in total?",
    "d3ab962e": "What is the total distance of the hikes I did on two consecutive weekends?",
    "gpt4_ab202e7f": "How many kitchen items did I replace or fix?",
    "bb7c3b45": "How much did I save on the Jimmy Choo heels?",
}

GOLD_EXPECTED = {
    "gpt4_194be4b3": {"entity_class": "musical_instruments", "target_count": 4},
    "d851d5ba": {"entity_class": "charity_donations", "target_total": 3750.0},
    "d3ab962e": {"entity_class": "hikes", "target_count": 2},  # gold says 8 miles total; we at least need 2 hike events
    "gpt4_ab202e7f": {"entity_class": "kitchen_items", "target_count": 5},
    "bb7c3b45": {"entity_class": None, "target_amount": 300.0},  # saved on heels
}

DATASET = Path(
    os.environ.get(
        "RADIOMIND_LME_S_DATASET",
        str(Path.home() / "Library/Caches/radiomind-data/longmemeval_s_cleaned.json"),
    )
)


def _question_id(q, idx):
    return q.get("question_id") or f"q{idx}"


def main() -> int:
    sandbox = Path(tempfile.mkdtemp(prefix="rm-regress-numagg-"))
    os.environ["RADIOMIND_HOME"] = str(sandbox)

    # Copy user's real config.toml into sandbox so llm_call can read
    # OpenRouter credentials — bench harnesses use this same pattern.
    import shutil
    cfg_src = Path.home() / ".radiomind" / "config.toml"
    cfg_dst = sandbox / "config.toml"
    if cfg_src.exists():
        cfg_content = cfg_src.read_text().replace(
            str(Path.home() / ".radiomind"), str(sandbox),
        )
        cfg_dst.write_text(cfg_content)

    # Bench LLM callable used for KG + decomposer + NumericAggregator
    # classifier. gpt-4o via OpenRouter — same model FINAL n=100 used,
    # so this reflects true bench-time behavior, not a cheaper proxy.
    answer_model = os.environ.get("REGRESS_MODEL", "openai/gpt-4o")
    answer_profile = os.environ.get("REGRESS_PROFILE", "openrouter")

    def _internal_llm(prompt: str, system: str = "") -> str:
        return llm_call(
            prompt, cfg_dst,
            model=answer_model, max_tokens=2500,
            profile=answer_profile, system=(system or None),
        )

    from radiomind import RadioMind

    data = json.loads(DATASET.read_text())
    by_qid = {_question_id(q, i): (i, q) for i, q in enumerate(data)}

    results = []
    for qid, question in TARGET_QIDS.items():
        if qid not in by_qid:
            print(f"[{qid}] NOT FOUND IN DATASET", flush=True)
            continue
        idx, q = by_qid[qid]

        print(f"\n{'='*70}\n[{qid}] {question}\n{'='*70}", flush=True)
        print(f"  gold fragment: {q.get('answer','')[:120]}", flush=True)

        mind = RadioMind(llm=_internal_llm)
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
        stats = mind.ingest_turns_raw(
            turns, domain=domain, run_aggregation=False, run_refinement=False,
        )
        print(f"  ingested: {stats['ingested']} turns, "
              f"cardinal_updates={stats.get('cardinal_updates','?')}", flush=True)

        all_cards = mind.list_cardinals(domain=domain, user_id="")
        print(f"  cardinals found: {len(all_cards)}", flush=True)
        for e in sorted(all_cards, key=lambda x: -x.count)[:20]:
            line = f"    - {e.entity_class}: count={e.count}"
            if e.total_amount is not None:
                line += f" total=${e.total_amount:,.0f}"
            if e.members:
                line += f" members={e.members[:6]}"
            print(line, flush=True)

        view = mind.get_numeric_cardinal(question, domain=domain, user_id="")
        print(f"\n  cardinal view:\n{view or '  (empty)'}", flush=True)

        verdict = "?"
        expected = GOLD_EXPECTED.get(qid, {})
        if expected.get("target_count") is not None:
            ec = expected["entity_class"]
            hit = next((x for x in all_cards if x.entity_class == ec), None)
            if hit and hit.count == expected["target_count"]:
                verdict = "PASS"
            elif hit:
                verdict = f"FAIL count={hit.count} (expected {expected['target_count']})"
            else:
                verdict = f"FAIL no {ec} entry"
        elif expected.get("target_total") is not None:
            ec = expected["entity_class"]
            hit = next((x for x in all_cards if x.entity_class == ec), None)
            if hit and abs((hit.total_amount or 0) - expected["target_total"]) < 1:
                verdict = "PASS"
            elif hit:
                verdict = f"FAIL total=${hit.total_amount} (expected ${expected['target_total']})"
            else:
                verdict = f"FAIL no {ec} entry"
        elif expected.get("target_amount") is not None:
            verdict = "SKIP (single-event amount query, no class expected)"

        print(f"  VERDICT: {verdict}", flush=True)
        results.append((qid, verdict))

        mind.shutdown()

    print(f"\n{'='*70}\nSUMMARY")
    for qid, v in results:
        print(f"  {qid}: {v}")
    passes = sum(1 for _, v in results if v == "PASS")
    print(f"\n{passes}/{len(results)} PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
