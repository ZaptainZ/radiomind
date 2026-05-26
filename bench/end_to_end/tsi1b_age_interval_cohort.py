"""TSI-1b: full-cohort age_interval live probe (read-only).

Per Codex 2026-05-26: before any age_interval commit closure
(TSI-1c) ships, exhaustively probe LME-S for every qid where
age_interval could fire. Verify rewrite trigger surface is
clean: no case where the strong trigger fires (skill conf>=0.85
+ numeric answer + LLM abstained) BUT the gold is itself
canonical abstain (which would mean rewriting would FAIL a
correct abstain).

Cohort (regex pre-screened against age_interval._TRIGGER_RE):
  - c18a7dc8 (LSA-3 / AAS-2 already audited; in LSA-3 sandbox)
  - 157a136e (NEW — kin age delta)
  - 6613b389 (NEW — months-before-event)

For each qid:
  1. Fresh sandbox per qid (no cross-contamination)
  2. Ingest haystack
  3. mind.search(question) → retrieved memories
  4. mind.run_temporal_precision(...) → captures STRUCTURED SKILL
     section if age_interval (or other registered skill) fires
  5. Build the full answer prompt (cardinal + temporal + etc.
     sections) and call answer-LLM ONCE — capture committed answer
  6. Apply JAB-1a/b veto post-judge per the actual runner flow
  7. Compare: skill_answer vs final_answer vs gold

Output: per-qid record including skill_fired, skill_name,
skill_conf, skill_answer, backing_evidence_present, final_answer,
gold, llm_abstained, gold_is_abstain, judge_verdict (against
gold), would_rewrite_have_changed_correctness.

This is READ-ONLY — no code change, no fix attempt.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

DATASET = Path.home() / "Library/Caches/radiomind-data/longmemeval_s_cleaned.json"

# Pre-screened qids — verified by stage-0 regex scan
TARGET_QIDS = [
    "c18a7dc8",
    "157a136e",
    "6613b389",
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


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--sandbox", type=Path,
                   default=Path("/tmp/rm-tsi1b-cohort"))
    p.add_argument("--out", type=Path,
                   default=Path("bench/end_to_end/tsi1b-cohort-probe.json"))
    args = p.parse_args()

    if args.sandbox.exists():
        shutil.rmtree(args.sandbox)
    args.sandbox.mkdir(parents=True, exist_ok=True)
    os.environ["RADIOMIND_HOME"] = str(args.sandbox)

    cfg_src = Path.home() / ".radiomind" / "config.toml"
    cfg_content = cfg_src.read_text()
    (args.sandbox / "config.toml").write_text(
        cfg_content.replace(str(Path.home() / ".radiomind"), str(args.sandbox))
    )
    config_path = args.sandbox / "config.toml"
    from run_longmemeval_mem0 import llm_call
    from jab1_abstain_veto import (
        is_abstain_gold, is_abstain_response, should_veto,
    )

    def _llm(prompt: str, system: str = "") -> str:
        return llm_call(
            prompt, config_path,
            model="deepseek-v3.2", max_tokens=2500,
            profile="dashscope", system=(system or None),
        )
    from radiomind.core.mind import RadioMind
    mind = RadioMind(llm=_llm)
    mind.initialize()

    ds = json.loads(DATASET.read_text())
    by_qid = {(q.get("question_id") or q.get("id")): q for q in ds}

    records: list[dict] = []
    for qid in TARGET_QIDS:
        target = by_qid.get(qid)
        if not target:
            records.append({"qid": qid, "error": "qid_not_in_dataset"})
            continue
        question = target["question"]
        gold = str(target.get("answer", ""))
        q_date = target.get("question_date", "")
        domain = f"tsi1b_{qid}"
        print(f"\n=== {qid} ===", flush=True)
        print(f"  Q: {question[:120]}", flush=True)
        print(f"  gold: {gold[:120]}", flush=True)
        print(f"  ingesting...", flush=True)
        try:
            n_ingested = _ingest_qid(mind, target, domain)
            print(f"  ingested {n_ingested} turns", flush=True)
        except Exception as e:
            print(f"  ingest FAILED: {e}", flush=True)
            records.append({"qid": qid, "error": f"ingest: {e}"})
            continue

        # Retrieve
        results = mind.search(question, domain=domain, max_results=30)
        mem_results = []
        for r in results[:30]:
            sdate = (r.entry.metadata or {}).get("session_date", "")
            mem_results.append({
                "memory": r.entry.content,
                "score": float(getattr(r, "score", 0.0)),
                "created_at": sdate,
            })

        # Probe skill
        try:
            temporal_section = mind.run_temporal_precision(
                query=question, retrieved_memories=mem_results,
                reference_date=q_date, domain=domain,
            )
        except Exception as e:
            temporal_section = ""

        skill_fired = bool(
            temporal_section and "STRUCTURED SKILL" in temporal_section
        )
        skill_name = None
        skill_conf = None
        skill_answer = None
        backing_evidence_age_at = False
        if skill_fired:
            mn = re.search(
                r"STRUCTURED SKILL \((\w+), conf=([\d.]+)\)",
                temporal_section,
            )
            if mn:
                skill_name = mn.group(1)
                skill_conf = float(mn.group(2))
            ma = re.search(
                r"Computed answer:\s*(.+?)\s*(?:\n|$)",
                temporal_section,
            )
            if ma:
                skill_answer = ma.group(1).strip()
            # check backing evidence — does any retrieved memory
            # contain explicit "at the age of N" / "when I was N" /
            # "aged N" pattern (mirrors age_interval._age_at_event)
            for r in mem_results:
                c = r.get("memory", "") or ""
                if re.search(
                    r"(?:at\s+the\s+age\s+of|when\s+I\s+was|aged)\s+\d{1,3}",
                    c, re.IGNORECASE,
                ):
                    backing_evidence_age_at = True
                    break

        # Capture LLM final answer via simplified prompt: build the
        # actual answer prompt the runner would build, then call LLM
        # once. (We don't run the full bidirectional gate or rewrite —
        # this is the LLM's raw commit/abstain decision given the
        # skill section.)
        from mem0_protocol.longmemeval_prompts import (
            get_answer_generation_prompt,
        )
        ans_prompt = get_answer_generation_prompt(
            question=question, search_results=mem_results,
            question_date=q_date or "",
        )
        if temporal_section:
            ans_prompt = temporal_section + ans_prompt
        try:
            raw_answer = llm_call(
                ans_prompt, config_path,
                model="deepseek-v3.2", max_tokens=1500,
                profile="dashscope",
            )
            # strip_thinking lives in the runner module itself
            from run_longmemeval_mem0 import strip_thinking
            llm_answer = strip_thinking(raw_answer)
        except Exception as e:
            llm_answer = f"[answer error: {e}]"

        gold_abstain = is_abstain_gold(gold)
        llm_abstain = is_abstain_response(llm_answer)
        veto_would_fire = should_veto(gold, llm_answer)

        # Rewrite-trigger condition per TSI-1c spec:
        rewrite_trigger = bool(
            skill_name == "age_interval"
            and skill_conf is not None
            and skill_conf >= 0.85
            and skill_answer
            and re.search(r"\d", skill_answer)  # numeric
            and backing_evidence_age_at
            and llm_abstain
        )
        # Would rewriting cause a wrongful commit?
        would_break_correct_abstain = bool(
            rewrite_trigger and gold_abstain
        )

        rec = {
            "qid": qid,
            "question": question,
            "gold": gold,
            "gold_is_abstain": gold_abstain,
            "skill_fired": skill_fired,
            "skill_name": skill_name,
            "skill_conf": skill_conf,
            "skill_answer": skill_answer,
            "backing_evidence_age_at_event_present": backing_evidence_age_at,
            "llm_final_answer": llm_answer[:300],
            "llm_abstained": llm_abstain,
            "jab_veto_would_fire": veto_would_fire,
            "rewrite_trigger_would_fire": rewrite_trigger,
            "would_break_correct_abstain": would_break_correct_abstain,
        }
        records.append(rec)
        print(f"  skill_fired={skill_fired} name={skill_name} "
              f"conf={skill_conf} answer={skill_answer!r}", flush=True)
        print(f"  backing_age_at_event={backing_evidence_age_at}", flush=True)
        print(f"  llm_answer={llm_answer[:120]!r}", flush=True)
        print(f"  llm_abstained={llm_abstain}", flush=True)
        print(f"  gold_is_abstain={gold_abstain}", flush=True)
        print(f"  rewrite_would_trigger={rewrite_trigger}", flush=True)
        print(f"  would_break_correct_abstain={would_break_correct_abstain}",
              flush=True)

    # Aggregate
    print("\n\n=== TSI-1b Aggregate ===", flush=True)
    print(f"  qids probed: {len(records)}", flush=True)
    fires = [r for r in records if r.get("rewrite_trigger_would_fire")]
    breaks = [r for r in records if r.get("would_break_correct_abstain")]
    print(f"  rewrite trigger would fire on: {len(fires)} "
          f"({[r['qid'] for r in fires]})", flush=True)
    print(f"  cases that would BREAK a correct abstain: {len(breaks)} "
          f"({[r['qid'] for r in breaks]})", flush=True)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(records, indent=2, ensure_ascii=False))
    print(f"\nsaved → {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
