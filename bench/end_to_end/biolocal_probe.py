#!/usr/bin/env python3
"""biolocal_probe.py — BioLocalRetrieval-1a offline retrieval feasibility probe.

READ-ONLY experiment. Does NOT touch RadioMind runtime, does NOT change the
default retrieval path, does NOT call any cloud service, does NOT run the full
n=100 benchmark. It ingests a curated set of archived LME-S qids into a throwaway
sandbox store, then scores FOUR retrieval tiers over the *full* candidate pool of
each qid and reports gold-evidence rank / coverage / latency:

  A  FTS/BM25 only            (current local default — the baseline)
  B  FTS + typed facets       (role / number / entity / time / phrase overlap)
  C  FTS + facets + HDC        (deterministic bipolar hypervector association)
  D  local semantic embedder   (on-device ONNX MiniLM, upper bound) — only if the
     embedder is installed; remote embedding/rerank is NOT called here (it would
     need consent + upload, deferred — see ManagedRetrieval-1b).

Gold is measured at TURN level via the dataset's `has_answer` flag (more precise
than the session-level signal earlier diagnostics used).

Usage:
  ~/.radiomind-bench-venv/bin/python bench/end_to_end/biolocal_probe.py
  ~/.radiomind-bench-venv/bin/python bench/end_to_end/biolocal_probe.py --qids bb7c3b45,c18a7dc8
  # report an existing result table without re-running:
  ~/.radiomind-bench-venv/bin/python bench/end_to_end/biolocal_probe.py --report bench/end_to_end/biolocal-1a-result.json

Output: bench/end_to_end/biolocal-1a-result.json + a stdout summary table.

All weights are FIXED and documented (not tuned to the gold) to avoid overfitting
a 14-qid curated subset; the goal is a directional feasibility signal, not a SOTA
number.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DATASET = Path.home() / "Library/Caches/radiomind-data/longmemeval_s_cleaned.json"
DEFAULT_OUT = REPO / "bench/end_to_end/biolocal-1a-result.json"

# ---- curated qid set (archived samples — do not invent new data) -------------
# 1. counting-cluster unstable (B-1 / B-1.5)
COUNTING = ["9ee3ecd6", "gpt4_194be4b3", "d3ab962e", "c18a7dc8", "b46e15ed"]
# 2. number-turn-pushed-out + ordering
OTHER_PROBLEM = ["bb7c3b45", "gpt4_d6585ce8"]
# 3. target-pack required / observe lines (helper-backed, mostly passing)
TARGET_PACK = ["031748ae_abs", "gpt4_93159ced_abs", "gpt4_93159ced",
               "9aaed6a3", "gpt4_d12ceb0e", "d851d5ba", "gpt4_7abb270c"]
TARGET_QIDS = COUNTING + OTHER_PROBLEM + TARGET_PACK
N_CONTROLS = 5  # do-no-harm controls (first dataset qids not in TARGET set)

# ---- fixed scoring weights (documented; not gold-tuned) ----------------------
W_NUMBER = 0.40   # shared normalized numbers/amounts/percentages
W_ENTITY = 0.30   # shared Title-Case / brand-like entity tokens
W_PHRASE = 0.25   # query content-bigram present verbatim in candidate
W_ROLE = 0.08     # candidate is a user turn (most answers are user-stated facts)
W_TIME = 0.10     # candidate session month == question month
W_HDC = 0.35      # C-tier: bipolar hypervector association score (mapped 0..1)
HDC_DIM = 4096

TOPN = 30         # report window
POOL_LIMIT = 5000  # full candidate pool ceiling per qid


# ============================== facet extraction =============================
_NUM_RE = re.compile(r"\$?\s?(\d[\d,]*(?:\.\d+)?)\s?(%?)")
_CAP_RE = re.compile(r"\b([A-Z][a-zA-Z0-9&'\-]+(?:\s+[A-Z][a-zA-Z0-9&'\-]+)*)\b")
_WORD_RE = re.compile(r"[a-z0-9]+")
_ROLE_RE = re.compile(r"^\s*\[(user|assistant)\]")
_STOP_ENT = {"I", "The", "A", "An", "My", "Im", "Id", "Ill", "Ive", "You",
             "It", "We", "They", "He", "She", "This", "That", "But", "And",
             "So", "If", "When", "What", "Great", "Sure", "Yes", "No", "Of"}


def _numbers(text: str) -> set[str]:
    out = set()
    for m in _NUM_RE.finditer(text):
        val = m.group(1).replace(",", "")
        if m.group(2) == "%":
            val += "%"
        # drop bare years-as-noise? keep — years matter for temporal qs.
        out.add(val)
    return out


def _entities(text: str) -> set[str]:
    # strip the leading [role] tag so it isn't read as an entity
    text = _ROLE_RE.sub("", text)
    out = set()
    for m in _CAP_RE.finditer(text):
        phrase = m.group(1).strip()
        head = phrase.split()[0]
        if head in _STOP_ENT and len(phrase.split()) == 1:
            continue
        # keep multi-word or non-stop single tokens
        toks = [w for w in phrase.split() if w not in _STOP_ENT]
        if toks:
            out.add(" ".join(toks).lower())
    return out


def _content_bigrams(text: str) -> set[str]:
    words = _WORD_RE.findall(_ROLE_RE.sub("", text).lower())
    words = [w for w in words if len(w) > 2]
    return {f"{a} {b}" for a, b in zip(words, words[1:])}


def _facets(text: str, role: str, month: str) -> dict:
    return {
        "numbers": _numbers(text),
        "entities": _entities(text),
        "bigrams": _content_bigrams(text),
        "role": role,
        "month": month,
    }


def _month(date_str: str) -> str:
    if not date_str:
        return ""
    m = re.search(r"(\d{4})[-/](\d{1,2})", date_str)
    return f"{m.group(1)}-{int(m.group(2)):02d}" if m else ""


# ============================== HDC (deterministic) ==========================
def _atom(token: str, dim: int):
    import numpy as np
    h = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    seed = int.from_bytes(h, "big") % (2**32)
    rng = np.random.default_rng(seed)
    return rng.integers(0, 2, size=dim, dtype=np.int8) * 2 - 1  # bipolar ±1


def _hypervector(facets: dict, dim: int):
    import numpy as np
    acc = np.zeros(dim, dtype=np.float32)
    n = 0
    for tok in facets["numbers"]:
        acc += _atom("num:" + tok, dim); n += 1
    for tok in facets["entities"]:
        acc += _atom("ent:" + tok, dim); n += 1
    if facets["role"]:
        acc += _atom("role:" + facets["role"], dim); n += 1
    if facets["month"]:
        acc += _atom("month:" + facets["month"], dim); n += 1
    # a few content tokens so HDC isn't blind when facets are sparse
    for tok in list(facets["bigrams"])[:12]:
        acc += _atom("bg:" + tok, dim); n += 1
    if n == 0:
        return None
    norm = np.linalg.norm(acc)
    return acc / norm if norm > 0 else None


def _cos(a, b) -> float:
    import numpy as np
    if a is None or b is None:
        return 0.0
    return float(np.dot(a, b))  # both unit-normalized


# ============================== ingest (reused pattern) ======================
def _ingest_qid(mind, target: dict, domain: str) -> int:
    turns = []
    for s_idx, session in enumerate(target["haystack_sessions"]):
        sid = (target["haystack_session_ids"][s_idx]
               if s_idx < len(target.get("haystack_session_ids", [])) else f"s{s_idx}")
        sdate = (target["haystack_dates"][s_idx]
                 if s_idx < len(target.get("haystack_dates", [])) else "")
        for t_idx, turn in enumerate(session):
            content = turn.get("content", "")
            if not content:
                continue
            turns.append({
                "role": turn.get("role", "?"),
                "content": f"[{turn.get('role','?')}] {content}",
                "metadata": {"turn_id": f"{sid}_t{t_idx}",
                             "session_date": sdate,
                             "role": turn.get("role", "?")},
            })
    mind.ingest_turns_raw(turns, domain=domain, run_aggregation=True,
                          run_refinement=False)
    return len(turns)


def _gold_turn_ids(target: dict) -> set[str]:
    """Turn-level gold: turns flagged has_answer inside answer sessions."""
    gold_sids = set(target.get("answer_session_ids", []))
    out = set()
    for s_idx, session in enumerate(target["haystack_sessions"]):
        sid = (target["haystack_session_ids"][s_idx]
               if s_idx < len(target.get("haystack_session_ids", [])) else f"s{s_idx}")
        for t_idx, turn in enumerate(session):
            if not turn.get("content"):
                continue
            if turn.get("has_answer") and (sid in gold_sids or not gold_sids):
                out.add(f"{sid}_t{t_idx}")
    return out


# ============================== ranking tiers ================================
def _candidate_pool(mind, domain: str) -> list[dict]:
    """Full pool: every stored entry in the domain (raw turns + aggregates)."""
    entries = mind._store.list_by_domain(domain, limit=POOL_LIMIT)
    pool = []
    for e in entries:
        meta = e.metadata if isinstance(e.metadata, dict) else {}
        tid = meta.get("turn_id", "")
        pool.append({
            "turn_id": tid,
            "content": e.content or "",
            "role": meta.get("role", ""),
            "month": _month(meta.get("session_date", "")),
            "is_turn": bool(tid),
        })
    return pool


def _fts_scores(mind, question: str, domain: str, pool_size: int) -> dict:
    """A-tier: production FTS retrieval. Returns turn_id/content-key -> score."""
    results = mind.search(question, domain=domain, max_results=pool_size,
                          fuse_habits=False)
    scores = {}
    for r in results:
        entry = getattr(r, "entry", r)
        meta = entry.metadata if isinstance(entry.metadata, dict) else {}
        key = meta.get("turn_id", "") or ("c:" + (entry.content or "")[:80])
        scores[key] = float(getattr(r, "score", 0.0))
    return scores


def _key(cand: dict) -> str:
    return cand["turn_id"] or ("c:" + cand["content"][:80])


def _rank_metrics(ranked: list[dict], gold: set[str]) -> dict:
    """ranked = list of cand dicts in score order. gold = turn_id set."""
    best = None
    hits = 0
    gold_ranks = []
    for i, c in enumerate(ranked, 1):
        if c["turn_id"] in gold:
            if best is None:
                best = i
            if i <= TOPN:
                hits += 1
            gold_ranks.append(i)
    total = len(gold)
    return {
        "gold_total": total,
        "best_rank": best if best is not None else None,
        "hits_at_30": hits,
        "recall_at_30": round(hits / total, 3) if total else None,
        "gold_ranks": sorted(gold_ranks)[:10],
        "in_top30": hits > 0,
    }


def _explain_top_gold(ranked: list[dict], gold: set[str], qf: dict) -> dict:
    """Why did the best-ranked gold turn score — which facets overlapped."""
    for c in ranked:
        if c["turn_id"] in gold:
            cf = _facets(c["content"], c["role"], c["month"])
            return {
                "turn_id": c["turn_id"],
                "shared_numbers": sorted(qf["numbers"] & cf["numbers"]),
                "shared_entities": sorted(qf["entities"] & cf["entities"]),
                "shared_bigrams": sorted(qf["bigrams"] & cf["bigrams"])[:4],
                "role_user": c["role"] == "user",
                "month_match": bool(qf["month"]) and qf["month"] == cf["month"],
            }
    return {}


def probe_qid(mind, target: dict, idx: int, embedder) -> dict:
    qid = target["question_id"]
    question = target["question"]
    q_date = target.get("question_date", "")
    domain = f"biolocal_{idx}"
    gold = _gold_turn_ids(target)

    n_turns = _ingest_qid(mind, target, domain)
    pool = _candidate_pool(mind, domain)
    qf = _facets(question, "user", _month(q_date))
    q_hv = _hypervector(qf, HDC_DIM)

    # ---- A: FTS ----
    t0 = time.time()
    fts = _fts_scores(mind, question, domain, len(pool) + 50)
    a_max = max(fts.values()) if fts else 1.0
    for c in pool:
        c["fts"] = fts.get(_key(c), 0.0)
        c["fts_norm"] = (c["fts"] / a_max) if a_max > 0 else 0.0
    ranked_A = sorted(pool, key=lambda c: c["fts_norm"], reverse=True)
    lat_A = time.time() - t0

    # ---- B: FTS + facets ----
    t0 = time.time()
    for c in pool:
        cf = _facets(c["content"], c["role"], c["month"])
        c["_cf"] = cf
        num_ov = len(qf["numbers"] & cf["numbers"])
        ent_ov = len(qf["entities"] & cf["entities"])
        phr_ov = len(qf["bigrams"] & cf["bigrams"])
        score = (c["fts_norm"]
                 + W_NUMBER * min(num_ov, 3)
                 + W_ENTITY * min(ent_ov, 3)
                 + W_PHRASE * min(phr_ov, 3)
                 + (W_ROLE if c["role"] == "user" else 0.0)
                 + (W_TIME if qf["month"] and qf["month"] == cf["month"] else 0.0))
        c["score_B"] = score
    ranked_B = sorted(pool, key=lambda c: c["score_B"], reverse=True)
    lat_B = time.time() - t0

    # ---- C: B + HDC ----
    t0 = time.time()
    for c in pool:
        hv = _hypervector(c["_cf"], HDC_DIM)
        sim = (_cos(q_hv, hv) + 1.0) / 2.0  # map [-1,1] -> [0,1]
        c["hdc"] = round(sim, 4)
        c["score_C"] = c["score_B"] + W_HDC * sim
    ranked_C = sorted(pool, key=lambda c: c["score_C"], reverse=True)
    lat_C = time.time() - t0

    tiers = {
        "A_fts": {**_rank_metrics(ranked_A, gold), "latency_ms": round(lat_A * 1000, 1),
                  "needs_llm": False, "needs_remote": False},
        "B_facets": {**_rank_metrics(ranked_B, gold), "latency_ms": round(lat_B * 1000, 1),
                     "needs_llm": False, "needs_remote": False,
                     "explain_top_gold": _explain_top_gold(ranked_B, gold, qf)},
        "C_hdc": {**_rank_metrics(ranked_C, gold), "latency_ms": round(lat_C * 1000, 1),
                  "needs_llm": False, "needs_remote": False},
    }

    # ---- D: local semantic (on-device ONNX), upper bound — only if installed ----
    if embedder is not None:
        import numpy as np, struct
        t0 = time.time()

        def _emb(text: str):
            b = embedder.encode(text)
            if not b:
                return None
            v = np.frombuffer(b, dtype=np.float32).copy()
            n = np.linalg.norm(v)
            return v / n if n > 0 else None
        qv = _emb(question)
        for c in pool:
            cv = _emb(c["content"])
            c["score_D"] = float(np.dot(qv, cv)) if (qv is not None and cv is not None) else -1.0
        ranked_D = sorted(pool, key=lambda c: c["score_D"], reverse=True)
        lat_D = time.time() - t0
        tiers["D_local_semantic"] = {
            **_rank_metrics(ranked_D, gold), "latency_ms": round(lat_D * 1000, 1),
            "needs_llm": False, "needs_remote": False,
            "note": "on-device ONNX MiniLM-384; NOT remote",
        }
    else:
        tiers["D_local_semantic"] = {
            "status": "not_run",
            "reason": "local ONNX embedder absent; remote embedding deferred "
                      "(needs consent + upload — ManagedRetrieval-1b)",
        }

    # cleanup heavy refs
    for c in pool:
        c.pop("_cf", None)

    return {
        "qid": qid,
        "question": question[:140],
        "question_type": target.get("question_type", "?"),
        "gold_turns": sorted(gold),
        "pool_size": len(pool),
        "turns_ingested": n_turns,
        "tiers": tiers,
    }


# ============================== driver / reporting ===========================
def _load_embedder():
    try:
        from radiomind.storage.embedding import EmbeddingEncoder, check_embedding_available
        ok, _ = check_embedding_available()
        if not ok:
            return None
        home = Path(os.environ.get("RADIOMIND_HOME", "/tmp/rm-biolocal"))
        enc = EmbeddingEncoder(home / "models" / "embedding")
        return enc if enc.load() else None
    except Exception:
        return None


def _select_qids(data: dict, requested: list[str] | None) -> list[str]:
    by = {r["question_id"]: r for r in data}
    if requested:
        return [q for q in requested if q in by]
    qids = [q for q in TARGET_QIDS if q in by]
    # controls: first dataset qids not already chosen
    chosen = set(qids)
    for r in data:
        if len(qids) >= len(TARGET_QIDS) + N_CONTROLS:
            break
        if r["question_id"] not in chosen:
            qids.append(r["question_id"]); chosen.add(r["question_id"])
    return qids


def _print_report(result: dict) -> None:
    rows = result["results"]
    print(f"\nBioLocalRetrieval-1a — {len(rows)} qids "
          f"(D={'local-semantic' if result['embedder_present'] else 'NOT RUN'})")
    print("=" * 110)
    hdr = f"{'qid':18} {'type':16} {'gold':4} | " \
          f"{'A best/hit':12} {'B best/hit':12} {'C best/hit':12} {'D best/hit':12}"
    print(hdr); print("-" * 110)
    for r in rows:
        t = r["tiers"]
        def cell(tier):
            d = t.get(tier, {})
            if d.get("status") == "not_run":
                return "—"
            br = d.get("best_rank"); h = d.get("hits_at_30"); tot = d.get("gold_total")
            return f"{(br if br else '∞')}/{h}/{tot}"
        print(f"{r['qid']:18} {r['question_type'][:16]:16} {len(r['gold_turns']):4} | "
              f"{cell('A_fts'):12} {cell('B_facets'):12} {cell('C_hdc'):12} {cell('D_local_semantic'):12}")
    print("-" * 110)
    print("cells = best_rank / hits@30 / gold_total   (∞ = gold not retrieved at all)")
    # aggregate deltas
    print(_aggregate(rows))


def _aggregate(rows: list[dict]) -> str:
    import statistics as st
    def br(d):
        v = d.get("best_rank")
        return v if v else 9999
    lines = ["\nAggregate (best_rank, lower=better; recall@30):"]
    for tier in ["A_fts", "B_facets", "C_hdc", "D_local_semantic"]:
        present = [r["tiers"][tier] for r in rows
                   if r["tiers"].get(tier, {}).get("status") != "not_run"]
        if not present:
            lines.append(f"  {tier:18} not run"); continue
        ranks = [br(d) for d in present]
        rec = [d.get("recall_at_30") or 0 for d in present]
        in30 = sum(1 for d in present if d.get("in_top30"))
        lines.append(f"  {tier:18} median_best_rank={st.median(ranks):>6.1f}  "
                     f"mean_recall@30={st.mean(rec):.3f}  in_top30={in30}/{len(present)}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--qids", default="", help="comma list; default = curated set")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--sandbox", default="/tmp/rm-biolocal")
    ap.add_argument("--report", default="", help="re-print an existing result json")
    args = ap.parse_args()

    if args.report:
        _print_report(json.loads(Path(args.report).read_text()))
        return 0

    if not DATASET.exists():
        print(f"dataset missing: {DATASET}", file=sys.stderr)
        return 2

    os.environ["RADIOMIND_HOME"] = args.sandbox
    os.environ.setdefault("RADIOMIND_REMOTE_RETRIEVAL", "0")  # never remote here
    sandbox = Path(args.sandbox)
    if sandbox.exists():
        shutil.rmtree(sandbox)
    sandbox.mkdir(parents=True, exist_ok=True)

    data = json.loads(DATASET.read_text())
    by = {r["question_id"]: r for r in data}
    requested = [q.strip() for q in args.qids.split(",") if q.strip()] or None
    qids = _select_qids(data, requested)

    from radiomind.core.mind import RadioMind
    mind = RadioMind()
    mind.initialize()
    embedder = _load_embedder()
    # CRITICAL: A/B/C must use pure FTS. mind.search() auto-routes to vector
    # (knn) when an embedder is loaded, which would contaminate the FTS baseline
    # and the fts_norm feeding B/C. Detach the embedder from the search path; the
    # D tier uses the standalone `embedder` ref directly (embedder.encode), not
    # mind.search, so D is unaffected.
    mind._embedder = None
    mind._reranker = None

    results = []
    t_all = time.time()
    for i, qid in enumerate(qids):
        t0 = time.time()
        try:
            res = probe_qid(mind, by[qid], i, embedder)
            results.append(res)
            t = res["tiers"]
            print(f"[{i+1}/{len(qids)}] {qid:18} pool={res['pool_size']:4} "
                  f"A={t['A_fts'].get('best_rank')} B={t['B_facets'].get('best_rank')} "
                  f"C={t['C_hdc'].get('best_rank')} "
                  f"({time.time()-t0:.1f}s)", flush=True)
        except Exception as e:
            print(f"[{i+1}/{len(qids)}] {qid} FAILED: {type(e).__name__}: {e}", flush=True)
    mind.shutdown()

    out = {
        "experiment": "BioLocalRetrieval-1a",
        "dataset": str(DATASET),
        "embedder_present": embedder is not None,
        "weights": {"W_NUMBER": W_NUMBER, "W_ENTITY": W_ENTITY, "W_PHRASE": W_PHRASE,
                    "W_ROLE": W_ROLE, "W_TIME": W_TIME, "W_HDC": W_HDC, "HDC_DIM": HDC_DIM},
        "topn": TOPN,
        "target_qids": [q for q in TARGET_QIDS if q in by],
        "control_qids": [q for q in qids if q not in TARGET_QIDS],
        "elapsed_s": round(time.time() - t_all, 1),
        "results": results,
    }
    Path(args.out).write_text(json.dumps(out, indent=2))
    print(f"\nwrote {args.out}")
    _print_report(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
