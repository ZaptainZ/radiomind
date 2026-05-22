"""NAR-1: isolated re-ingest of d851d5ba — recall stability baseline.

Runs `n` independent fresh-sandbox ingests of the d851d5ba haystack,
dumps `cardinal_entries` after each run, and computes the per-run
recall matrix:

  - Did `charity_donations` capture all 4 gold events?
  - Where did the missing ones go (other entity_class)?
  - Did spurious non-charity events leak into `charity_donations`?

No answer LLM is invoked. Only ingest + post-ingest aggregator state.

Gold for d851d5ba (audit-derived):
  E1: $1,000  charity bake sale / children's hospital  (answer_5cdf9bd2_2)
  E2: $250    Run for Hunger / food bank               (answer_5cdf9bd2_1)
  E3: $500    charity fitness challenge / American Cancer Society
                                                       (answer_5cdf9bd2_3)
  E4: $2,000  charity event / local animal shelter     (answer_5cdf9bd2_4)
  TOTAL: $3,750
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


DATASET = Path("/tmp/longmemeval-data/longmemeval_s_cleaned.json")
TARGET_QID = "d851d5ba"

GOLD_EVENTS: list[tuple[int, str]] = [
    (1000, "bake sale / children's hospital"),
    (250, "Run for Hunger / food bank"),
    (500, "fitness challenge / American Cancer Society"),
    (2000, "animal shelter"),
]
GOLD_TOTAL = 3750


def _load_target(dataset_path: Path) -> dict:
    data = json.loads(dataset_path.read_text())
    for q in data:
        qid = q.get("question_id") or q.get("id")
        if qid == TARGET_QID:
            return q
    raise SystemExit(f"qid {TARGET_QID} not found in {dataset_path}")


def _build_turns(q: dict) -> list[dict]:
    turns: list[dict] = []
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
    return turns


def _dump_cardinals(db_path: Path, domain: str) -> list[dict]:
    """Read cardinal_entries for the given domain. Returns a list of
    flattened records with history_json parsed."""
    if not db_path.exists():
        return []
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.execute(
            "SELECT user_id, domain, entity_class, count, total_amount, "
            "evidence_json, history_json, members_json "
            "FROM cardinal_entries WHERE domain = ?",
            (domain,),
        )
        out: list[dict] = []
        for row in cur.fetchall():
            (user_id, dom, cls, cnt, total, ev_json, hist_json, mem_json) = row
            try:
                history = json.loads(hist_json) if hist_json else []
            except Exception:
                history = []
            try:
                evidence = json.loads(ev_json) if ev_json else []
            except Exception:
                evidence = []
            try:
                members = json.loads(mem_json) if mem_json else []
            except Exception:
                members = []
            out.append({
                "user_id": user_id,
                "domain": dom,
                "entity_class": cls,
                "count": cnt,
                "total_amount": total,
                "evidence": evidence,
                "members": members,
                "history": history,
            })
        return out
    finally:
        conn.close()


def _match_gold(event_amt: float | int, phrase: str) -> int | None:
    """Return gold event index (1-4) if (amount, phrase) matches a gold
    event, else None.

    Match policy: exact amount match. Phrase isn't required to mention
    the charity context — we just want to know whether the amount made
    it into ANY cardinal entry. The class column carries the answer to
    "did it land in charity_donations".
    """
    try:
        amt_i = int(round(float(event_amt)))
    except (TypeError, ValueError):
        return None
    for i, (g_amt, _label) in enumerate(GOLD_EVENTS):
        if amt_i == g_amt:
            return i + 1
    return None


def _classify_history_amounts(records: list[dict]) -> list[dict]:
    """For every history event across all entity_class rows, attach a
    parsed amount and a gold-match index. Returns a flat list of:
      { entity_class, turn_id, phrase, delta, amount, gold_idx }
    """
    import re
    AMT_RE = re.compile(r"\+?\$?([\d,]+(?:\.\d+)?)")
    out: list[dict] = []
    for rec in records:
        cls = rec["entity_class"]
        for h in rec.get("history", []) or []:
            phrase = str(h.get("phrase") or "").strip()
            delta = str(h.get("delta") or "").strip()
            tid = str(h.get("turn_id") or "").strip()
            reason = str(h.get("reason") or "").strip()
            m = AMT_RE.search(delta)
            if not m:
                continue
            try:
                amt = float(m.group(1).replace(",", ""))
            except ValueError:
                continue
            gold_idx = _match_gold(amt, phrase)
            out.append({
                "entity_class": cls,
                "turn_id": tid,
                "phrase": phrase,
                "delta": delta,
                "amount": amt,
                "reason": reason,
                "gold_idx": gold_idx,
            })
    return out


def _run_once(
    iteration: int,
    sandbox_root: Path,
    target_q: dict,
    answer_model: str,
    answer_profile: str,
    config_src: Path,
) -> dict:
    sandbox = sandbox_root / f"run{iteration}"
    if sandbox.exists():
        shutil.rmtree(sandbox)
    sandbox.mkdir(parents=True, exist_ok=True)

    os.environ["RADIOMIND_HOME"] = str(sandbox)

    cfg_content = config_src.read_text()
    (sandbox / "config.toml").write_text(
        cfg_content.replace(str(Path.home() / ".radiomind"), str(sandbox))
    )
    config_path = sandbox / "config.toml"

    from run_longmemeval_mem0 import llm_call

    def _internal_llm(prompt: str, system: str = "") -> str:
        return llm_call(
            prompt, config_path,
            model=answer_model, max_tokens=2500,
            profile=answer_profile, system=(system or None),
        )

    # Reload mind module path each iteration — Python caches imports;
    # since we vary RADIOMIND_HOME, ensure the next initialize() picks
    # up the new sandbox. RadioMind reads home from the env variable on
    # initialize(), so a fresh instance is enough.
    from radiomind.core.mind import RadioMind  # noqa: WPS433

    mind = RadioMind(llm=_internal_llm)
    mind.initialize()

    domain = "nar1"
    turns = _build_turns(target_q)
    t0 = time.time()
    stats = mind.ingest_turns_raw(
        turns, domain=domain,
        run_aggregation=True,
        run_refinement=False,  # refinement adds noise; NAR-1 only cares about aggregation
    )
    elapsed = time.time() - t0

    # Dump cardinals
    knowledge_db = sandbox / "data" / "knowledge.db"
    records = _dump_cardinals(knowledge_db, domain=domain)
    events = _classify_history_amounts(records)

    # Summary per run
    charity_recs = [r for r in records if r["entity_class"] == "charity_donations"]
    charity_events = [e for e in events if e["entity_class"] == "charity_donations"]
    charity_total = sum(e["amount"] for e in charity_events)
    charity_gold_hits = {e["gold_idx"] for e in charity_events if e["gold_idx"]}

    # Where missing gold events ended up
    missing_gold = []
    for gi in (1, 2, 3, 4):
        if gi in charity_gold_hits:
            continue
        landings = [
            {"class": e["entity_class"], "amount": e["amount"],
             "turn_id": e["turn_id"], "phrase": e["phrase"][:120]}
            for e in events
            if e["gold_idx"] == gi
        ]
        missing_gold.append({"gold_idx": gi, "amount": GOLD_EVENTS[gi-1][0],
                             "label": GOLD_EVENTS[gi-1][1],
                             "landed_in": landings})

    summary = {
        "iteration": iteration,
        "ingest_elapsed_s": elapsed,
        "stats": stats,
        "n_classes": len(records),
        "charity": {
            "count": charity_recs[0]["count"] if charity_recs else 0,
            "total_amount": charity_recs[0]["total_amount"] if charity_recs else None,
            "gold_hit": sorted(charity_gold_hits),
            "events": [
                {"amount": e["amount"], "phrase": e["phrase"][:140],
                 "turn_id": e["turn_id"], "delta": e["delta"],
                 "reason": e["reason"], "gold_idx": e["gold_idx"]}
                for e in charity_events
            ],
            "scoped_total_from_events": charity_total,
        },
        "missing_gold": missing_gold,
        "all_classes_summary": [
            {"class": r["entity_class"], "count": r["count"],
             "total_amount": r["total_amount"]}
            for r in records
        ],
    }
    return summary


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=5,
                   help="Number of isolated ingest iterations")
    p.add_argument("--sandbox-root", type=Path,
                   default=Path("/tmp/rm-nar1-d851d5ba"))
    p.add_argument("--answer-model", default="deepseek-v3.2")
    p.add_argument("--answer-profile", default="dashscope")
    p.add_argument("--out", type=Path,
                   default=Path("bench/end_to_end/nar1-d851d5ba-matrix.json"))
    args = p.parse_args()

    config_src = Path.home() / ".radiomind" / "config.toml"
    if not config_src.exists():
        print(f"missing config at {config_src}")
        return 2

    target_q = _load_target(DATASET)
    print(f"loaded {TARGET_QID}: question={target_q['question'][:80]!r}")
    print(f"haystack: {len(target_q['haystack_sessions'])} sessions")
    print(f"answer model: {args.answer_model} profile={args.answer_profile}")
    print(f"sandbox root: {args.sandbox_root}, runs: {args.n}\n")

    summaries: list[dict] = []
    for i in range(1, args.n + 1):
        print(f"=== run {i}/{args.n} ===", flush=True)
        try:
            s = _run_once(
                i, args.sandbox_root, target_q,
                args.answer_model, args.answer_profile, config_src,
            )
            summaries.append(s)
            print(
                f"  run {i}: charity_count={s['charity']['count']} "
                f"total={s['charity']['total_amount']} "
                f"gold_hit={s['charity']['gold_hit']} "
                f"elapsed={s['ingest_elapsed_s']:.0f}s",
                flush=True,
            )
            for m in s["missing_gold"]:
                landed = m["landed_in"] or [{"class": "<not extracted>"}]
                print(
                    f"    missing E{m['gold_idx']} (${m['amount']:,}, "
                    f"{m['label']!r}): landed_in={[x['class'] for x in landed]}",
                    flush=True,
                )
        except Exception as e:
            print(f"  run {i} FAILED: {e}", flush=True)
            summaries.append({"iteration": i, "error": str(e)})

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"qid": TARGET_QID,
                                    "n_runs": args.n,
                                    "summaries": summaries},
                                   indent=2, ensure_ascii=False))
    print(f"\nsaved → {args.out}")
    print("\n=== aggregate ===")
    hits_dist: dict[int, int] = {}
    totals_dist: dict[int | None, int] = {}
    for s in summaries:
        if "error" in s:
            continue
        n_hit = len(s["charity"]["gold_hit"])
        hits_dist[n_hit] = hits_dist.get(n_hit, 0) + 1
        t = s["charity"]["total_amount"]
        t_key = int(t) if t is not None else None
        totals_dist[t_key] = totals_dist.get(t_key, 0) + 1
    print(f"gold_hit count distribution: {hits_dist}")
    print(f"charity total_amount distribution: {totals_dist}")
    pass_runs = sum(1 for s in summaries
                    if "error" not in s
                    and (s["charity"]["total_amount"] or 0) == GOLD_TOTAL
                    and len(s["charity"]["gold_hit"]) == 4)
    print(f"PASS (4/4 gold hit AND total=${GOLD_TOTAL}): "
          f"{pass_runs}/{args.n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
