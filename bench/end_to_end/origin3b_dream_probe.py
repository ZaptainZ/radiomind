"""Origin-3b dream probe (bench-only, probe-scale, run on a sandbox COPY).

Given an already-seeded sandbox copy, this script:
  1. snapshots the memories table (id, domain, level, status, content)
  2. measures gold-evidence retrieval ranks for the probe qid (top-200)
  3. runs mind.trigger_dream()  (the ONLY mutation between measurements)
  4. snapshots + measures again
  5. writes a structured JSON: dream result, store diff (archived /
     content-changed / added), ranks before/after

The ingest-variance confound is removed by construction: the copy is
byte-identical to the base sandbox, so dream is the single delta. The
answer-only x5 before/after comparison runs separately via the runner CLI
(base sandbox vs dreamed copy).

Usage:
  RADIOMIND-free; pass --sandbox explicitly. Example:
    python origin3b_dream_probe.py --sandbox /tmp/rm-sandbox-o3b-d3ab-dream \
        --qid d3ab962e --domain lme_0 --out o3b-dream-diff-d3ab962e.json
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent


def load_question(qid: str) -> dict:
    dataset = Path(os.environ.get(
        "RADIOMIND_LME_S_DATASET",
        Path.home() / "Library" / "Caches" / "radiomind-data"
        / "longmemeval_s_cleaned.json"))
    data = json.loads(dataset.read_text())
    for q in data:
        if str(q.get("question_id")) == qid:
            return q
    raise SystemExit(f"qid {qid} not in dataset")


def snapshot_store(sandbox: Path) -> list[dict]:
    db = sandbox / "data" / "radiomind.db"
    if not db.exists():
        raise SystemExit(f"no store at {db} — sandbox not seeded?")
    con = sqlite3.connect(str(db))
    try:
        rows = con.execute(
            "SELECT id, domain, level, status, content FROM memories "
            "ORDER BY id").fetchall()
    finally:
        con.close()
    return [{"id": r[0], "domain": r[1], "level": r[2],
             "status": r[3], "content": r[4]} for r in rows]


def diff_snapshots(before: list[dict], after: list[dict]) -> dict:
    b = {r["id"]: r for r in before}
    a = {r["id"]: r for r in after}
    status_changed = [
        {"id": i, "before_status": b[i]["status"],
         "after_status": a[i]["status"], "content": b[i]["content"][:200]}
        for i in b if i in a and b[i]["status"] != a[i]["status"]]
    content_changed = [
        {"id": i, "before": b[i]["content"][:300], "after": a[i]["content"][:300]}
        for i in b if i in a and b[i]["content"] != a[i]["content"]]
    added = [{"id": i, "level": a[i]["level"], "content": a[i]["content"][:200]}
             for i in a if i not in b]
    removed = [{"id": i, "content": b[i]["content"][:200]}
               for i in b if i not in a]
    return {
        "n_before": len(before), "n_after": len(after),
        "status_changed": status_changed,
        "content_changed": content_changed,
        "added": added, "removed": removed,
    }


def evidence_ranks(mind, question: str, domain: str,
                   answer_session_ids: list[str], top_k: int = 200) -> dict:
    results = mind.search(question, domain=domain, max_results=top_k)
    gold = []
    for rank, r in enumerate(results, 1):
        md = (r.entry.metadata or {}) if getattr(r, "entry", None) else {}
        turn_id = str(md.get("turn_id", ""))
        if any(turn_id.startswith(str(sid)) for sid in answer_session_ids):
            gold.append({"rank": rank, "turn_id": turn_id})
    in30 = sum(1 for g in gold if g["rank"] <= 30)
    return {"total_results": len(results), "gold_hits": gold,
            "gold_in_top30": in30, "gold_in_top200": len(gold)}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--sandbox", required=True)
    p.add_argument("--qid", required=True)
    p.add_argument("--domain", default="lme_0")
    p.add_argument("--out", required=True)
    p.add_argument("--answer-model", default="deepseek-v3.2")
    p.add_argument("--answer-profile", default="dashscope")
    args = p.parse_args()

    sandbox = Path(args.sandbox)
    os.environ["RADIOMIND_HOME"] = str(sandbox)
    sys.path.insert(0, str(BENCH_DIR))
    from run_longmemeval_mem0 import llm_call  # same creds path as the runner

    q = load_question(args.qid)
    config_path = Path.home() / ".radiomind" / "config.toml"

    from radiomind.core.mind import RadioMind

    def _internal_llm(prompt: str, system: str = "") -> str:
        return llm_call(prompt, config_path, model=args.answer_model,
                        max_tokens=2500, profile=args.answer_profile,
                        system=(system or None))

    mind = RadioMind(llm=_internal_llm)
    mind.initialize()

    before = snapshot_store(sandbox)
    ranks_before = evidence_ranks(
        mind, q["question"], args.domain, q.get("answer_session_ids", []))

    dr = mind.trigger_dream()
    dream_result = {
        "merged": dr.merged, "pruned": dr.pruned,
        "insights": len(dr.new_insights or []),
        "duration_s": round(dr.duration_s, 2),
    }

    after = snapshot_store(sandbox)
    ranks_after = evidence_ranks(
        mind, q["question"], args.domain, q.get("answer_session_ids", []))

    out = {
        "probe": "origin3b-dream",
        "qid": args.qid, "domain": args.domain,
        "sandbox": str(sandbox),
        "question": q["question"],
        "gold": q.get("answer"),
        "answer_session_ids": q.get("answer_session_ids", []),
        "dream_result": dream_result,
        "store_diff": diff_snapshots(before, after),
        "evidence_ranks_before": ranks_before,
        "evidence_ranks_after": ranks_after,
    }
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(json.dumps({
        "dream_result": dream_result,
        "diff_counts": {k: (len(v) if isinstance(v, list) else v)
                        for k, v in out["store_diff"].items()},
        "gold_top30_before": ranks_before["gold_in_top30"],
        "gold_top30_after": ranks_after["gold_in_top30"],
        "gold_top200_before": ranks_before["gold_in_top200"],
        "gold_top200_after": ranks_after["gold_in_top200"],
    }, indent=2))
    print(f"saved → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
