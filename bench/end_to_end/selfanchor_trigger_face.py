"""SelfAnchor-1b trigger-face audit.

Confirms the store-scan supplement does NOT mis-fire on qids that
match a helper trigger but should NOT be recovered:

  - 157a136e: age_interval `older` trigger matches, but gold needs
    a user age that isn't in the data (input limitation). The
    store has KIN ages (grandma 75 etc.) — self-age scan must
    return None (kin-guard), NOT mis-recover an age.
  - 6613b389: age_interval `before` trigger — mode gate keeps the
    rewrite dormant regardless; scan run here for extra safety.
  - e25c3b8d: SavingsHint trigger; paid already in retrieve and
    retail fails same-item proximity → supplement path not reached.
    Scan run here to confirm what it WOULD return (information).

Read-only. Ingests into a per-qid sandbox (reused if present).
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


def _ingest(mind, target, domain):
    turns = []
    for s_idx, session in enumerate(target["haystack_sessions"]):
        sid = target["haystack_session_ids"][s_idx]
        sdate = target["haystack_dates"][s_idx]
        for t_idx, turn in enumerate(session):
            content = turn.get("content", "")
            if not content:
                continue
            turns.append({
                "role": turn.get("role", "?"),
                "content": f"[{turn.get('role','?')}] {content}",
                "metadata": {"turn_id": f"{sid}_t{t_idx}",
                             "session_date": sdate, "role": turn.get("role", "?")},
            })
    mind.ingest_turns_raw(turns, domain=domain,
                          run_aggregation=True, run_refinement=False)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--qid", required=True)
    p.add_argument("--item", default=None, help="item phrase for paid scan")
    args = p.parse_args()

    data = json.loads(DATASET.read_text())
    target = next(q for q in data if (q.get("question_id") or q.get("id")) == args.qid)

    sandbox = Path(f"/tmp/rm-tface-{args.qid}")
    reuse = sandbox.exists() and (sandbox / "config.toml").exists()
    if not reuse:
        if sandbox.exists():
            shutil.rmtree(sandbox)
        sandbox.mkdir(parents=True, exist_ok=True)
        cfg = (Path.home() / ".radiomind" / "config.toml").read_text()
        (sandbox / "config.toml").write_text(
            cfg.replace(str(Path.home() / ".radiomind"), str(sandbox)))
    os.environ["RADIOMIND_HOME"] = str(sandbox)
    config_path = sandbox / "config.toml"
    from run_longmemeval_mem0 import llm_call

    def _llm(pr, s=""):
        return llm_call(pr, config_path, model="deepseek-v3.2",
                        max_tokens=2500, profile="dashscope", system=(s or None))
    from radiomind.core.mind import RadioMind
    mind = RadioMind(llm=_llm)
    mind.initialize()
    domain = f"tface_{args.qid}"
    if not reuse:
        _ingest(mind, target, domain)

    from radiomind.core.self_anchor import (
        scan_current_age_user_turns, scan_paid_price_user_turns,
    )
    age = scan_current_age_user_turns(mind, domain)
    paid = scan_paid_price_user_turns(mind, domain, args.item) if args.item else None

    print(f"\n=== trigger-face: {args.qid} ===")
    print(f"  gold: {str(target.get('answer'))[:50]}")
    print(f"  scan_current_age → {age}")
    if args.item:
        print(f"  scan_paid_price({args.item!r}) → {paid}")
    out = {
        "qid": args.qid,
        "gold": str(target.get("answer"))[:60],
        "current_age_scan": None if age is None else {
            "value": age.value, "turn_id": age.source_turn_id,
            "quote": age.quote},
        "paid_scan": None if paid is None else {
            "value": paid.value, "turn_id": paid.source_turn_id},
    }
    Path(f"bench/end_to_end/selfanchor-tface-{args.qid}.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False))
    print(f"  saved → bench/end_to_end/selfanchor-tface-{args.qid}.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
