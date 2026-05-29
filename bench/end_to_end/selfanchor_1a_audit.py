"""SelfAnchor-1a: store-vs-retrieve self-anchor recall audit.

For one cohort qid, compare where the self anchor the helper
needs lives:
  - raw haystack user turns (ground truth — does it exist at all)
  - ingested store (FACT layer, role=user) — present after ingest
  - retrieve top-200 — does search surface it

Output matrix per qid:
  anchor_kind / in_raw / in_store / in_retrieve / regex_recoverable
  / risk_note

Read-only. Ingests into a per-qid sandbox (reused if present).
NO helper change, NO global search change.
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

# current-age first-person patterns
_CUR_AGE = [
    re.compile(r"\bas\s+a\s+(\d{2})[-\s]year[-\s]old\b", re.IGNORECASE),
    re.compile(r"\b(\d{2})[-\s]year[-\s]old\b", re.IGNORECASE),
    re.compile(r"\bi\s+(?:just\s+)?turned\s+(\d{2})\b", re.IGNORECASE),
    re.compile(r"\bi(?:'m|\s+am)\s+(\d{2})\s+years?\s+old\b", re.IGNORECASE),
    re.compile(r"\bi(?:'m|\s+am)\s+(?:now\s+|currently\s+)?(\d{2})\b", re.IGNORECASE),
]
_PAID = [
    re.compile(r"(?:got|bought|purchased|grabbed|snagged|picked\s+up)\s+[^.?\n]{0,40}?\bfor\s+(?:only\s+|just\s+)?\$\s*(\d[\d,]*(?:\.\d+)?)", re.IGNORECASE),
    re.compile(r"\bpaid\s+(?:only\s+|just\s+)?\$\s*(\d[\d,]*(?:\.\d+)?)", re.IGNORECASE),
]


def _scan(texts, kind):
    pats = _CUR_AGE if kind == "current_age" else _PAID
    hits = []
    for tid, c in texts:
        for p in pats:
            m = p.search(c)
            if m:
                v = m.group(1)
                if kind == "current_age":
                    iv = int(v)
                    if not (15 <= iv <= 99):
                        continue
                hits.append((tid, v, c[max(0, m.start()-25):m.end()+25].replace("\n", " ")))
                break
    return hits


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
    p.add_argument("--kind", required=True, choices=["current_age", "paid"])
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args()

    data = json.loads(DATASET.read_text())
    target = next(q for q in data if (q.get("question_id") or q.get("id")) == args.qid)
    question = target["question"]

    # 1. raw haystack user turns
    raw_user = []
    for s_idx, sess in enumerate(target["haystack_sessions"]):
        sid = target["haystack_session_ids"][s_idx]
        for t_idx, t in enumerate(sess):
            if t.get("role") == "user":
                raw_user.append((f"{sid}_t{t_idx}", t.get("content", "")))
    raw_hits = _scan(raw_user, args.kind)

    # sandbox
    sandbox = Path(f"/tmp/rm-selfanchor-{args.qid}")
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
    from radiomind.core.types import MemoryLevel
    mind = RadioMind(llm=_llm)
    mind.initialize()
    domain = f"selfanchor_{args.qid}"
    if not reuse:
        _ingest(mind, target, domain)

    # 2. store FACT layer, role=user entries
    facts = mind._store.list_by_domain(domain, level=MemoryLevel.FACT, limit=1000)
    store_user = []
    for f in facts:
        meta = f.metadata or {}
        content = f.content or ""
        # raw user turns carry role meta or "[user]" prefix
        is_user = (isinstance(meta, dict) and meta.get("role") == "user") \
            or content.lower().startswith("[user]")
        if is_user:
            store_user.append((meta.get("turn_id", "?") if isinstance(meta, dict) else "?", content))
    store_hits = _scan(store_user, args.kind)

    # 3. retrieve top-200
    results = mind.search(question, domain=domain, max_results=200)
    retr = []
    for r in results:
        meta = r.entry.metadata or {}
        content = r.entry.content or ""
        is_user = (isinstance(meta, dict) and meta.get("role") == "user") \
            or content.lower().startswith("[user]")
        if is_user:
            retr.append((meta.get("turn_id", "?") if isinstance(meta, dict) else "?", content))
    retr_hits = _scan(retr, args.kind)

    rec = {
        "qid": args.qid, "kind": args.kind, "question": question,
        "gold": str(target.get("answer", ""))[:60],
        "raw_user_turns": len(raw_user),
        "store_user_turns": len(store_user),
        "retrieve_user_turns": len(retr),
        "in_raw": [{"tid": t, "val": v} for t, v, _ in raw_hits],
        "in_store": [{"tid": t, "val": v} for t, v, _ in store_hits],
        "in_retrieve": [{"tid": t, "val": v} for t, v, _ in retr_hits],
        "regex_recoverable": len(raw_hits) > 0,
    }
    # verdict
    if not raw_hits:
        rec["verdict"] = "not_in_data (input limitation)"
    elif not store_hits:
        rec["verdict"] = "lost_at_ingest (not in store)"
    elif not retr_hits:
        rec["verdict"] = "RECOVERABLE: in store, missed by retrieve"
    else:
        rec["verdict"] = "in_retrieve (helper-side issue, not recall)"

    print(f"\n=== SelfAnchor-1a: {args.qid} ({args.kind}) ===")
    print(f"  gold: {rec['gold']}")
    print(f"  user turns: raw={rec['raw_user_turns']} store={rec['store_user_turns']} retrieve={rec['retrieve_user_turns']}")
    print(f"  anchor in raw:      {rec['in_raw']}")
    print(f"  anchor in store:    {rec['in_store']}")
    print(f"  anchor in retrieve: {rec['in_retrieve']}")
    print(f"  VERDICT: {rec['verdict']}")

    out = args.out or Path(f"bench/end_to_end/selfanchor-1a-{args.qid}.json")
    out.write_text(json.dumps(rec, indent=2, ensure_ascii=False))
    print(f"  saved → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
