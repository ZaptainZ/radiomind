"""Regress 18 LME-S questions that failed post-refactor.

Tests whether the C1-C7 activations (skills + temporal anchors + profile
injection + tag boosts + behavior log + trinity migration) collectively
shift any of these from FAIL → PASS.

Cost: ~18 × 3-4 min = ~70 min, ~$5-8.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from run_longmemeval_mem0 import llm_call, _parse_judge_verdict  # noqa: E402


# Load the 18 wrong qids from the post-refactor run.
# REGRESS_QIDS env var allows narrowing to a subset (comma-separated).
POST_JSON = Path(__file__).parent / "lme-s-n100-post-refactor.json"
_all_wrong = [
    q["question_id"] for q in json.loads(POST_JSON.read_text())["per_query"]
    if not q["correct"]
]

# Dataset errata: qids whose gold labels are known-incorrect after haystack
# audit. RadioMind's disagreement on these is correct; skip them unless
# explicitly requested via REGRESS_QIDS so they don't distort fix-impact
# measurements. See dataset_errata.json for the audit trail.
ERRATA_JSON = Path(__file__).parent / "dataset_errata.json"
_errata: dict = {}
if ERRATA_JSON.exists():
    _errata = json.loads(ERRATA_JSON.read_text()).get("longmemeval_s", {}) or {}
ERRATA_QIDS = set(_errata.keys())

_filter = (os.environ.get("REGRESS_QIDS") or "").strip()
if _filter:
    # Explicit request — honor every qid, even if not in the historical
    # post-refactor failure list (useful after a new n=100 run surfaces
    # regressions that weren't in the original 18).
    TARGET_QIDS = [q.strip() for q in _filter.split(",") if q.strip()]
else:
    # Default: drop errata; measure what we can actually fix
    TARGET_QIDS = [q for q in _all_wrong if q not in ERRATA_QIDS]
    if ERRATA_QIDS:
        print(
            f"[errata] skipping {len(ERRATA_QIDS)} known dataset-gold errors: "
            f"{sorted(ERRATA_QIDS)}",
            flush=True,
        )

DATASET = Path("/tmp/longmemeval-data/longmemeval_s_cleaned.json")


def _question_id(q: dict, idx: int) -> str:
    return q.get("question_id") or f"q{idx}"


def main() -> int:
    sandbox = Path(tempfile.mkdtemp(prefix="rm-activated-regress-"))
    os.environ["RADIOMIND_HOME"] = str(sandbox)
    cfg_src = Path.home() / ".radiomind" / "config.toml"
    cfg_dst = sandbox / "config.toml"
    if cfg_src.exists():
        cfg_dst.write_text(
            cfg_src.read_text().replace(str(Path.home() / ".radiomind"), str(sandbox))
        )
    # Dev mode: deepseek-v3.2 via TokenPlan (~20× cheaper than gpt-4o)
    # Both answer and judge share the cheap model. Not A2A-comparable
    # with Mem0's published 0.934 but gives delta signal for architecture
    # changes without burning budget.
    answer_model = os.environ.get("REGRESS_ANSWER_MODEL", "deepseek-v3.2")
    profile = os.environ.get("REGRESS_PROFILE", "openai")  # TokenPlan
    judge_model = os.environ.get("REGRESS_JUDGE_MODEL", answer_model)
    judge_profile = os.environ.get("REGRESS_JUDGE_PROFILE", profile)

    def _llm(prompt, system=""):
        return llm_call(prompt, cfg_dst, model=answer_model, max_tokens=2500,
                        profile=profile, system=(system or None))

    sys.path.insert(0, str(Path(__file__).parent))
    from mem0_protocol.longmemeval_prompts import (  # noqa: E402
        get_answer_generation_prompt, get_judge_prompt,
    )
    from radiomind import RadioMind

    data = json.loads(DATASET.read_text())
    by_qid = {_question_id(q, i): (i, q) for i, q in enumerate(data)}

    results = []
    for qid in TARGET_QIDS:
        if qid not in by_qid:
            print(f"SKIP {qid} (not in dataset)")
            continue
        idx, q = by_qid[qid]
        question = q["question"]
        gold = q["answer"]
        q_date = q.get("question_date", "")
        qtype = q.get("question_type", "")
        print(f"\n[{qid} {qtype}]")
        print(f"  Q: {question[:100]}")

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
        stats = mind.ingest_turns_raw(
            turns, domain=domain, run_aggregation=False, run_refinement=False,
        )
        print(f"  ingest: {stats['ingested']}t, "
              f"anchors={stats.get('temporal_anchors',0)}, "
              f"card={stats.get('cardinal_updates',{})}, "
              f"profile={stats.get('profile_fragments',0)}")

        # Retrieve
        search_results = mind.search(question, domain=domain, max_results=200)
        mem_results = []
        for r in search_results:
            sdate = (r.entry.metadata or {}).get("session_date", "")
            mem_results.append({
                "memory": r.entry.content,
                "score": float(getattr(r, "score", 0.0)),
                "created_at": sdate,
            })

        # All answer-side sections
        sections = {}
        try:
            sections["cardinal"] = mind.get_numeric_cardinal(query=question, domain=domain, user_id="")
        except Exception:
            sections["cardinal"] = ""
        try:
            sections["temporal"] = mind.run_temporal_precision(
                query=question, retrieved_memories=mem_results,
                reference_date=q_date or "", domain=domain,
            )
        except Exception:
            sections["temporal"] = ""
        try:
            sections["open_domain"] = mind.run_open_domain_specific(
                query=question, retrieved_memories=mem_results, domain=domain,
            )
        except Exception:
            sections["open_domain"] = ""
        try:
            sections["profile"] = mind.profile_hint(query=question)
        except Exception:
            sections["profile"] = ""
        try:
            sections["preference_context"] = mind.run_preference_context(
                query=question, retrieved_memories=mem_results, domain=domain,
            )
        except Exception:
            sections["preference_context"] = ""

        atomic = ""
        try:
            if not sections["cardinal"]:
                atoms = mind.decompose_for_query(
                    query=question, retrieved=search_results[:30], domain=domain, promote=False,
                )
                if atoms:
                    lines = ["DRAFT ATOMIC VIEW (VERIFY against memories):"]
                    for a in atoms[:15]:
                        count_tag = f" [×{a.count}]" if a.count > 1 else ""
                        lines.append(f'- {a.fact}{count_tag} (conf {a.confidence:.2f})')
                    atomic = "\n".join(lines) + "\n\n"
        except Exception:
            pass
        sections["atomic"] = atomic

        print(f"  sections: " + " ".join(
            f"{k}={'✓' if v else '✗'}" for k, v in sections.items()
        ))

        # Compose answer prompt
        ans_prompt = get_answer_generation_prompt(
            question=question, search_results=mem_results, question_date=q_date or "",
        )
        for key in ("atomic", "cardinal", "temporal", "open_domain",
                    "profile", "preference_context"):
            if sections.get(key):
                ans_prompt = sections[key] + ans_prompt
        try:
            calib = mind.get_meta_calibration()
            if calib:
                ans_prompt = ans_prompt + "\n\n" + calib
        except Exception:
            pass

        try:
            # 2500 is needed for verbose <mem_thinking> reasoning on
            # complex multi-hop questions; 1500 cuts some off before
            # the final answer, which the judge then rejects as
            # no-answer. Cost delta is trivial at this scale.
            answer = llm_call(ans_prompt, cfg_dst, model=answer_model,
                              max_tokens=2500, profile=profile)
        except Exception as e:
            answer = f"[answer error: {e}]"
        print(f"  answer: {answer[:120].replace(chr(10), chr(32))}")

        # Judge
        judge_prompt = get_judge_prompt(
            question_type=qtype, question_id=qid,
            question=question, answer=gold, response=answer,
            question_date=q_date or "",
        )
        try:
            # 2000 (was 1200): gpt-4o judge sometimes runs out before
            # writing the trailing yes/no, dropping the verdict mid-
            # sentence. Same fix mirrored in run_longmemeval_mem0.py.
            verdict = llm_call(judge_prompt, cfg_dst, model=judge_model,
                               max_tokens=2000, profile=judge_profile)
            is_correct = _parse_judge_verdict(verdict)
        except Exception as e:
            verdict = f"[judge error: {e}]"
            is_correct = False
        flag = "PASS" if is_correct else "FAIL"
        print(f"  → {flag}")

        results.append({
            "qid": qid, "qtype": qtype, "correct": is_correct,
            "answer": str(answer)[:3500],
            "gold": str(gold)[:120],
            "sections": {k: bool(v) for k, v in sections.items()},
            "prefixed": (
                sections.get("temporal") or sections.get("open_domain")
                or sections.get("cardinal") or sections.get("atomic") or ""
            )[:2500],
            "verdict": str(verdict)[:800],
        })
        mind.shutdown()

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    for r in results:
        flag = "✓" if r["correct"] else "✗"
        print(f"{flag} [{r['qtype'][:15]:15}] {r['qid']}: {r['answer'][:80]}")
    passes = sum(1 for r in results if r["correct"])
    print(f"\n{passes}/{len(results)} flipped FAIL → PASS")
    # Save per-question record
    outpath = Path(__file__).parent / "activated-regress-results.json"
    outpath.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"Saved → {outpath}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
