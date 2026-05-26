"""TSI-1: Trust-in-Structured-skill cohort audit (read-only).

For each LME-S V8.2.2a-judge-fixed in-scope FAIL qid (per LSA-2),
determine:

  - Does any registered skill fire on the question + retrieved
    memories? Which one, what answer, what confidence.
  - Did the artifact's final answer match the skill's output?
  - Is this a "trust gap" (skill produces high-conf answer, LLM
    final answer abstains or contradicts)?

Output a per-qid record so we can decide:
  - If only `age_interval` shows the trust gap → narrow age_interval
    commit contract (small change).
  - If multiple skills show it → broader proof-bearing commit
    contract (large change, design first).

This is READ-ONLY — no code change, no fix attempt. Just data
to inform the next design decision per Codex (2026-05-26 P1.3).

To minimize wall time, reuses the LSA-3 sandbox for the 3 qids
already ingested (c18a7dc8 / b46e15ed / gpt4_93159ced_abs). For
the other 5 in-scope FAILs, runs a question-only trigger
pre-screen (free regex over the registered skill triggers)
without re-ingesting. The pre-screen reports whether any skill
*could* fire; if none could, no trust gap is possible.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

DATASET = Path.home() / "Library/Caches/radiomind-data/longmemeval_s_cleaned.json"
V822A_ARTIFACT = Path("bench/end_to_end/lme-s-v822a-n100.judge-fixed.json")
LSA3_SANDBOX = Path("/tmp/rm-lsa3-existing-path")

# Per LSA-2 inventory: 8 in-scope FAILS on V8.2.2a baseline.
IN_SCOPE_FAILS = [
    ("1c0ddc50",           "preference advice"),
    ("b6025781",           "preference advice"),
    ("d6233ab6",           "preference advice"),
    ("c18a7dc8",           "age delta — LSA-3 already audited (in sandbox)"),
    ("b46e15ed",           "event-cluster interval — in sandbox"),
    ("gpt4_93159ced_abs",  "temporal endpoint — TESG-1 just fixed"),
    ("gpt4_ab202e7f",      "kitchen count — entity normalization"),
    ("gpt4_d6585ce8",      "concert ordering"),
]

IN_SANDBOX = {"c18a7dc8", "b46e15ed", "gpt4_93159ced_abs"}


# ------------------------------------------------------------------
# Skill trigger pre-screen — read-only regex over question text.
# Mirrors the trigger lines from each registered skill.
# ------------------------------------------------------------------

# age_interval._TRIGGER_RE
AGE_TRIG = re.compile(
    r"how\s+many\s+(?:years?|months?)\s+"
    r"(older|younger|since|between|after|before|apart)",
    re.IGNORECASE,
)
# event_interval — match() returns True unconditionally, so pre-screen
# checks resolve() trigger: "between A and B" / "from A to B" shapes
EVENT_INT_TRIG = re.compile(
    r"how\s+(?:long|many\s+(?:days?|weeks?|months?|years?))\s+"
    r"(?:between|from|since|after|before|until)",
    re.IGNORECASE,
)
# cardinality skill — count questions
CARD_TRIG = re.compile(
    r"how\s+many\s+(?!years?\b|months?\b)\w+",
    re.IGNORECASE,
)
# temporal skill — date/time arithmetic
TEMP_TRIG = re.compile(
    r"\b(?:how\s+long|when\s+(?:did|do|does|will|was)|"
    r"what\s+date|on\s+what\s+date|how\s+many\s+(?:days?|months?|years?))\b",
    re.IGNORECASE,
)
# chain_reasoning — multi-hop inference
CHAIN_TRIG = re.compile(
    r"\b(?:what|which|who)\s+(?:do\s+i|does\s+the|"
    r"is\s+the\s+(?:relationship|connection))\b",
    re.IGNORECASE,
)
# list_ordering — sequence/order questions
LIST_TRIG = re.compile(
    r"\b(?:in\s+(?:what|which)\s+order|first|second|third|last|"
    r"earliest|latest|sequence)\b",
    re.IGNORECASE,
)


def screen_question(question: str) -> list[str]:
    """Return the names of skills whose trigger regex matches the
    question text. Read-only — does NOT ingest or call any LLM."""
    matches: list[str] = []
    if AGE_TRIG.search(question): matches.append("age_interval")
    if EVENT_INT_TRIG.search(question): matches.append("event_interval")
    if CARD_TRIG.search(question): matches.append("cardinality")
    if TEMP_TRIG.search(question): matches.append("temporal")
    if CHAIN_TRIG.search(question): matches.append("chain_reasoning")
    if LIST_TRIG.search(question): matches.append("list_ordering")
    return matches


# ------------------------------------------------------------------
# Live probe — only for the 3 qids already in LSA-3 sandbox.
# ------------------------------------------------------------------

def probe_skill_on_sandbox(qid: str, question: str, mind, llm) -> dict:
    """For a qid whose haystack is already in the LSA-3 sandbox,
    call run_temporal_precision to capture the structured-skill
    output that the runner would actually inject as
    `temporal_section`."""
    domain = f"lsa3_{qid}"
    out: dict = {"qid": qid, "domain": domain}
    try:
        results = mind.search(question, domain=domain, max_results=30)
        mem_results = []
        for r in results[:30]:
            sdate = (r.entry.metadata or {}).get("session_date", "")
            mem_results.append({
                "memory": r.entry.content,
                "score": float(getattr(r, "score", 0.0)),
                "created_at": sdate,
            })
        try:
            temporal_section = mind.run_temporal_precision(
                query=question, retrieved_memories=mem_results,
                reference_date="", domain=domain,
            )
        except Exception as e:
            temporal_section = ""
            out["temporal_section_error"] = str(e)
        out["temporal_section"] = temporal_section
        out["skill_fired"] = bool(
            temporal_section and "STRUCTURED SKILL" in temporal_section
        )
        if out["skill_fired"]:
            # Extract skill name + conf + computed answer
            m_name = re.search(
                r"STRUCTURED SKILL \((\w+), conf=([\d.]+)\)",
                temporal_section,
            )
            if m_name:
                out["skill_name"] = m_name.group(1)
                out["skill_conf"] = float(m_name.group(2))
            m_ans = re.search(
                r"Computed answer:\s*(.+?)\s*(?:\n|$)",
                temporal_section,
            )
            if m_ans:
                out["skill_answer"] = m_ans.group(1).strip()
    except Exception as e:
        out["probe_error"] = str(e)
    return out


def main() -> int:
    if not V822A_ARTIFACT.exists():
        print(f"missing artifact: {V822A_ARTIFACT}", flush=True)
        return 2
    artifact = json.loads(V822A_ARTIFACT.read_text())
    by_qid = {r["question_id"]: r for r in artifact["per_query"]}
    data = json.loads(DATASET.read_text())
    ds_by_qid = {(q.get("question_id") or q.get("id")): q for q in data}

    # Pre-screen all 8 qids
    records: list[dict] = []
    for qid, label in IN_SCOPE_FAILS:
        artifact_rec = by_qid.get(qid, {})
        ds_rec = ds_by_qid.get(qid, {})
        question = artifact_rec.get("q") or ds_rec.get("question", "")
        gold = artifact_rec.get("gold") or str(ds_rec.get("answer", ""))
        artifact_answer = artifact_rec.get("answer", "")
        artifact_correct = artifact_rec.get("correct")
        triggered = screen_question(question)
        records.append({
            "qid": qid,
            "lsa2_label": label,
            "question": question,
            "gold": gold,
            "artifact_final_answer": artifact_answer,
            "artifact_correct": artifact_correct,
            "screen_triggers": triggered,
            "in_sandbox": qid in IN_SANDBOX,
        })

    # Live probe on the 3 in-sandbox qids
    if LSA3_SANDBOX.exists():
        os.environ["RADIOMIND_HOME"] = str(LSA3_SANDBOX)
        config_path = LSA3_SANDBOX / "config.toml"
        from run_longmemeval_mem0 import llm_call

        def _llm(prompt: str, system: str = "") -> str:
            return llm_call(
                prompt, config_path,
                model="deepseek-v3.2", max_tokens=2500,
                profile="dashscope", system=(system or None),
            )
        from radiomind.core.mind import RadioMind
        mind = RadioMind(llm=_llm)
        mind.initialize()
        for r in records:
            if not r["in_sandbox"]:
                continue
            probe = probe_skill_on_sandbox(r["qid"], r["question"], mind, _llm)
            r["probe"] = probe

    # Summary
    print(f"\n=== TSI-1 cohort audit ({len(records)} qids) ===\n")
    for r in records:
        print(f"--- {r['qid']} ({r['lsa2_label']}) ---")
        print(f"  Q: {r['question'][:100]}")
        print(f"  gold:   {r['gold'][:80]}")
        print(f"  artifact answer: {(r['artifact_final_answer'] or '')[:100]}")
        print(f"  artifact_correct: {r['artifact_correct']}")
        print(f"  screen triggers: {r['screen_triggers'] or '(none)'}")
        if r["in_sandbox"]:
            p = r.get("probe", {})
            if p.get("skill_fired"):
                print(f"  → skill: {p.get('skill_name')} "
                      f"(conf={p.get('skill_conf')}) → '{p.get('skill_answer')}'")
                # Trust gap heuristic: skill said X with conf>=0.7, but
                # artifact final answer was abstain or differed.
                skill_ans = str(p.get("skill_answer") or "").strip()
                artifact_ans = str(r['artifact_final_answer'] or "").strip()
                from jab1_abstain_veto import is_abstain_response
                trust_gap = False
                if p.get("skill_conf", 0) >= 0.7 and skill_ans:
                    if is_abstain_response(artifact_ans):
                        trust_gap = True
                    elif skill_ans.lower() not in artifact_ans.lower():
                        trust_gap = True
                r["trust_gap_likely"] = trust_gap
                print(f"  TRUST GAP: {trust_gap}")
            else:
                print(f"  → no skill fired (temporal_section empty)")
                r["trust_gap_likely"] = False
        else:
            r["trust_gap_likely"] = None  # not probed
        print()

    # Aggregate
    print(f"\n=== Aggregate ===")
    probed = [r for r in records if r["in_sandbox"]]
    gaps = [r for r in probed if r.get("trust_gap_likely")]
    print(f"  probed (in-sandbox): {len(probed)}")
    print(f"  trust-gap candidates: {len(gaps)} ({[g['qid'] for g in gaps]})")
    print(f"  skill-trigger pre-screen distribution:")
    from collections import Counter
    for trigs, n in Counter(
        tuple(r['screen_triggers']) for r in records
    ).items():
        print(f"    {trigs!r}: {n}")

    Path("bench/end_to_end/tsi1-cohort-audit.json").write_text(
        json.dumps(records, indent=2, ensure_ascii=False),
    )
    print(f"\nsaved → bench/end_to_end/tsi1-cohort-audit.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
