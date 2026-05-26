"""AAS-2: age_interval evidence-priority live probe.

Read-only audit. Reuses the LSA-3 sandbox
(/tmp/rm-lsa3-existing-path) which already has c18a7dc8
ingested. For the c18a7dc8 query:

  1. What does mind.search(question, top=30) return?
  2. What does _find_event_mentions("graduated from college",
     retrieved) return? (Expect: niece-only.)
  3. What does _find_event_via_trinity(...) return?
     (Does it locate the user's Bachelor's turn? With what
     age_at_event?)
  4. What does _find_age_at_event_in_store(mind,
     "graduated from college", domain) return?
     (Does it surface the age-25 turn even with zero token
     overlap?)
  5. Enumerate all FACT-layer entries that match the
     _age_at_event regex to confirm the age-25 entry is
     present and unique-enough not to false-positive.

No code change. Output JSON for review.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

DATASET = Path.home() / "Library/Caches/radiomind-data/longmemeval_s_cleaned.json"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--sandbox", type=Path,
                   default=Path("/tmp/rm-lsa3-existing-path"))
    p.add_argument("--out", type=Path,
                   default=Path("bench/end_to_end/aas2-age-interval-probe.json"))
    args = p.parse_args()

    if not args.sandbox.exists():
        print(f"sandbox missing: {args.sandbox}", flush=True)
        print("re-run lsa3_existing_path_regression.py first", flush=True)
        return 2
    os.environ["RADIOMIND_HOME"] = str(args.sandbox)

    config_path = args.sandbox / "config.toml"
    from run_longmemeval_mem0 import llm_call

    def _internal_llm(prompt: str, system: str = "") -> str:
        return llm_call(
            prompt, config_path,
            model="deepseek-v3.2", max_tokens=2500,
            profile="dashscope", system=(system or None),
        )

    from radiomind.core.mind import RadioMind
    from radiomind.skills.age_interval import (
        _find_event_mentions, _find_event_via_trinity,
        _find_age_at_event_in_store, _age_at_event,
        _WHEN_PRONOUN_RE, _SINCE_PRONOUN_RE,
    )
    from radiomind.core.types import MemoryLevel

    mind = RadioMind(llm=_internal_llm)
    mind.initialize()

    data = json.loads(DATASET.read_text())
    target = next(q for q in data if (q.get("question_id") or q.get("id")) == "c18a7dc8")
    question = target["question"]
    gold = str(target.get("answer"))
    domain = "lsa3_c18a7dc8"

    print(f"Q: {question}", flush=True)
    print(f"gold: {gold}", flush=True)

    # Extract phrase via skill's own regex
    wm = _WHEN_PRONOUN_RE.search(question)
    sm = _SINCE_PRONOUN_RE.search(question)
    phrase = (wm.group(1) if wm else (sm.group(1) if sm else "")).strip().rstrip("?.!")
    print(f"extracted phrase: {phrase!r}", flush=True)

    # Step 1: retrieve top-30
    results = mind.search(question, domain=domain, max_results=30)
    retrieved = []
    for i, r in enumerate(results, 1):
        entry = getattr(r, "entry", r)
        content = getattr(entry, "content", "") or ""
        meta = getattr(entry, "metadata", {}) or {}
        if not isinstance(meta, dict):
            meta = {}
        retrieved.append({
            "rank": i,
            "turn_id": meta.get("turn_id", ""),
            "session_date": meta.get("session_date", ""),
            "preview": content[:160].replace("\n", " "),
            "_full": content,
        })

    # Step 2: _find_event_mentions
    fem = _find_event_mentions(phrase, results)
    fem_out = [{"date": d, "preview": c[:200].replace("\n", " ")} for c, d in fem]
    print(f"\n_find_event_mentions({phrase!r}, top-30) → {len(fem_out)} hits:",
          flush=True)
    for h in fem_out:
        print(f"  [{h['date']}] {h['preview']}", flush=True)

    # Step 3: _find_event_via_trinity
    print(f"\n_find_event_via_trinity({phrase!r}, top-30, llm) ...",
          flush=True)
    try:
        esc = _find_event_via_trinity(phrase, results, _internal_llm)
        if esc is None:
            esc_out = None
            print("  → None", flush=True)
        else:
            c, d, age = esc
            esc_out = {"preview": c[:200].replace("\n", " "),
                       "date": d, "age_at_event": age}
            print(f"  → date={d}, age={age}, content={c[:160]!r}", flush=True)
    except Exception as e:
        esc_out = {"error": str(e)}
        print(f"  → ERR {e}", flush=True)

    # Step 4: _find_age_at_event_in_store
    print(f"\n_find_age_at_event_in_store(mind, {phrase!r}, {domain!r}) ...",
          flush=True)
    try:
        scan = _find_age_at_event_in_store(mind, phrase, domain)
        if scan is None:
            scan_out = None
            print("  → None", flush=True)
        else:
            c, d, age = scan
            scan_out = {"preview": c[:300].replace("\n", " "),
                        "date": d, "age_at_event": age}
            print(f"  → date={d}, age={age}, content={c[:200]!r}", flush=True)
    except Exception as e:
        scan_out = {"error": str(e)}
        print(f"  → ERR {e}", flush=True)

    # Step 5: enumerate ALL FACT-layer entries with _age_at_event match
    print(f"\nFACT-layer enumeration: entries matching `at the age of N / "
          f"when I was N / aged N` in domain {domain}", flush=True)
    fact_age_entries: list[dict] = []
    try:
        facts = mind._store.list_by_domain(
            domain, level=MemoryLevel.FACT, limit=500,
        )
        for entry in facts:
            age = _age_at_event(entry.content or "")
            if age is None:
                continue
            meta = entry.metadata or {}
            fact_age_entries.append({
                "age_at_event": age,
                "turn_id": meta.get("turn_id", ""),
                "session_date": meta.get("session_date", ""),
                "preview": (entry.content or "")[:300].replace("\n", " "),
            })
    except Exception as e:
        print(f"  ERR listing facts: {e}", flush=True)
    print(f"  found {len(fact_age_entries)} FACT entries with `at the age of N`",
          flush=True)
    for f in fact_age_entries:
        print(f"  age={f['age_at_event']}, sdate={f['session_date']}, "
              f"tid={f['turn_id']}", flush=True)
        print(f"    {f['preview'][:200]}", flush=True)

    out_payload = {
        "qid": "c18a7dc8",
        "question": question,
        "gold": gold,
        "extracted_phrase": phrase,
        "retrieved_top_30": retrieved,
        "step2_find_event_mentions": fem_out,
        "step3_find_event_via_trinity": esc_out,
        "step4_find_age_at_event_in_store": scan_out,
        "step5_fact_age_entries": fact_age_entries,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out_payload, indent=2, ensure_ascii=False))
    print(f"\nsaved → {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
