#!/usr/bin/env python3
"""reranker_alt_probe.py — RerankerAlternative-1a offline probe.

READ-ONLY. No runtime change, no default-path change, no cloud, no full benchmark.
Asks: can a lightweight, deterministic, LOCAL rerank approach part of the heavy
cross-encoder reranker's benefit — so the 2.3GB reranker can stay an optional
advanced mode rather than the only quality lever above embedding?

Baseline 0: local ONNX MiniLM dense ranking (REQUIRED — if absent, BLOCKED; we do
NOT fall back to remote). Then four lightweight reranks over the dense candidate
pool:
  A  hubness correction      score = cos(q,d) - alpha * mean_sim_to_neighbors(d)
  B  MMR / redundancy-aware   greedy: lambda*rel - (1-lambda)*max_redundancy
  C  query-adaptive RRF       type-weighted fusion of dense/FTS/facet/temporal
  D  graph diffusion (PPR)    personalized PageRank over memory/entity/number/
                              session/domain/time nodes; final = dense + beta*graph

Metrics per qid per method: recall@5/10/30, gold best_rank, hits@30, top-30
redundancy (same session/domain/entity), latency_ms, needs_model/needs_remote,
debug explanation. Gold is turn-level (`has_answer`).

Run (py3.12 venv WITH the embedding extra — bench venv py3.13 can't load ONNX):
  /tmp/rm-rc-venv/bin/python bench/end_to_end/reranker_alt_probe.py
  ... --report bench/end_to_end/reranker-alt-1a-result.json

All weights are FIXED and documented (alpha .2 / lambda .75 / beta .5 / RRF k 60);
not tuned to gold. 14-qid curated subset → directional signal, not SOTA.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from biolocal_probe import (  # noqa: E402  reuse — do not reinvent data
    DATASET, TARGET_QIDS, _ingest_qid, _gold_turn_ids, _candidate_pool, _select_qids,
)

REPO = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO / "bench/end_to_end/reranker-alt-1a-result.json"

ALPHA = 0.2     # A: hubness down-weight
LAMBDA = 0.75   # B: MMR relevance vs diversity
BETA = 0.5      # D: graph contribution
RRF_K = 60
POOL = 150      # dense candidate pool to rerank (top by dense cosine)
TOPN = 30


# ----------------------------- embedding -----------------------------
def _load_embedder():
    from radiomind.storage.embedding import EmbeddingEncoder, check_embedding_available
    ok, msg = check_embedding_available()
    if not ok:
        return None, msg
    home = Path(os.environ.get("RADIOMIND_HOME", "/tmp/rm-rerankalt"))
    enc = EmbeddingEncoder(home / "models" / "embedding")
    return (enc, "") if enc.load() else (None, "embedder.load() failed")


def _embed_matrix(embedder, texts):
    import numpy as np
    vecs = []
    for t in texts:
        b = embedder.encode(t)
        if not b:
            vecs.append(None); continue
        v = np.frombuffer(b, dtype=np.float32).copy()
        n = np.linalg.norm(v)
        vecs.append(v / n if n > 0 else v)
    dim = next((len(v) for v in vecs if v is not None), 384)
    return np.array([v if v is not None else np.zeros(dim, dtype=np.float32) for v in vecs])


# ----------------------------- metrics -----------------------------
def _metrics(order, pool, gold, lat_ms, explain=""):
    """order = list of pool indices ranked best-first."""
    ranks = [i + 1 for i, idx in enumerate(order) if pool[idx]["turn_id"] in gold]
    total = len(gold)
    def rec(k):
        return round(sum(1 for r in ranks if r <= k) / total, 3) if total else None
    # top-30 redundancy: 1 - distinct(session|domain)/n  (higher = more repetitive)
    top = [pool[idx] for idx in order[:TOPN]]
    sids = [t["turn_id"].rsplit("_t", 1)[0] if "_t" in t["turn_id"] else t["turn_id"] for t in top]
    distinct = len(set(s for s in sids if s))
    redundancy = round(1 - distinct / len(top), 3) if top else 0.0
    return {
        "recall_at_5": rec(5), "recall_at_10": rec(10), "recall_at_30": rec(30),
        "best_rank": ranks[0] if ranks else None,
        "hits_at_30": sum(1 for r in ranks if r <= TOPN),
        "gold_total": total,
        "redundancy_top30": redundancy,
        "latency_ms": round(lat_ms, 1),
        "needs_model": True,   # all use the ONNX dense base
        "needs_remote": False,
        "explain": explain,
    }


# ----------------------------- methods -----------------------------
def _baseline(dense, pool, gold):
    import numpy as np
    t = time.time()
    order = list(np.argsort(-dense))
    return _metrics(order, pool, gold, (time.time() - t) * 1000,
                    "ONNX dense cosine ranking"), order


def _method_a(dense, E, topN_idx, pool, gold):
    """Hubness correction: down-weight candidates similar to everything."""
    import numpy as np
    t = time.time()
    sub = E[topN_idx]                      # (m, d)
    sim = sub @ sub.T                       # (m, m)
    np.fill_diagonal(sim, 0.0)
    neighbor_mean = sim.mean(axis=1)        # hubness proxy
    adj = dense[topN_idx] - ALPHA * neighbor_mean
    reordered = [topN_idx[i] for i in np.argsort(-adj)]
    rest = [i for i in np.argsort(-dense) if i not in set(topN_idx)]
    order = reordered + list(rest)
    demoted = int((neighbor_mean > neighbor_mean.mean()).sum())
    return _metrics(order, pool, gold, (time.time() - t) * 1000,
                    f"alpha={ALPHA}; {demoted}/{len(topN_idx)} candidates above-mean hubness down-weighted")


def _redundancy_penalty(a, b):
    """deterministic structural redundancy between two pool items (0..1)."""
    pen = 0.0
    sa = a["turn_id"].rsplit("_t", 1)[0]; sb = b["turn_id"].rsplit("_t", 1)[0]
    if sa and sa == sb:
        pen += 0.5
    if a.get("role") and a["role"] == b.get("role"):
        pen += 0.1
    return min(pen, 1.0)


def _method_b(dense, E, topN_idx, pool, gold):
    """MMR: greedy relevance - redundancy (embedding + structural)."""
    import numpy as np
    t = time.time()
    cand = list(topN_idx)
    selected: list[int] = []
    while cand and len(selected) < TOPN:
        best, best_score = None, -1e9
        for c in cand:
            if selected:
                emb_red = max(float(E[c] @ E[s]) for s in selected)
                struct_red = max(_redundancy_penalty(pool[c], pool[s]) for s in selected)
                red = max(emb_red, struct_red)
            else:
                red = 0.0
            score = LAMBDA * float(dense[c]) - (1 - LAMBDA) * red
            if score > best_score:
                best, best_score = c, score
        selected.append(best); cand.remove(best)
    rest = [i for i in np.argsort(-dense) if i not in set(selected)]
    order = selected + list(rest)
    return _metrics(order, pool, gold, (time.time() - t) * 1000,
                    f"lambda={LAMBDA}; greedy diversity over {len(topN_idx)} dense candidates")


def _classify_query(query):
    from radiomind.storage import facet_rerank as fr
    import re
    ql = query.lower()
    if fr._CJK_RE.search(query):
        return "cjk"
    if fr._SKIP_RE.search(query):
        return "temporal_or_ordering"
    ok, _ = fr.should_rerank(query)
    if ok:
        return "anchored"
    return "open"


_WEIGHTS = {
    # dense, fts, facet, temporal
    "anchored":            (1.0, 0.6, 1.2, 0.0),
    "temporal_or_ordering":(1.0, 0.6, 0.0, 1.0),
    "open":                (1.4, 0.4, 0.2, 0.0),
    "cjk":                 (0.8, 1.2, 0.0, 0.0),
}


def _method_c(dense, pool, gold, query, store):
    """Query-adaptive RRF over dense / FTS / facet / temporal rankings."""
    import numpy as np
    import re
    from radiomind.storage import facet_rerank as fr
    t = time.time()
    qtype = _classify_query(query)
    w_dense, w_fts, w_facet, w_temporal = _WEIGHTS[qtype]
    tid_to_idx = {pool[i]["turn_id"]: i for i in range(len(pool)) if pool[i]["turn_id"]}

    rankings: list[tuple[float, list[int]]] = []
    rankings.append((w_dense, list(np.argsort(-dense))))

    # FTS (OR — AND is empty for NL questions)
    try:
        fts = store.search_fts_or(query, limit=POOL) or store.search_fts(query, limit=POOL)
    except Exception:
        fts = []
    fts_order = [tid_to_idx[(r.entry.metadata or {}).get("turn_id", "")]
                 for r in fts if (r.entry.metadata or {}).get("turn_id", "") in tid_to_idx]
    if fts_order:
        rankings.append((w_fts, fts_order))

    # facet ranking (reuse deterministic facet scoring)
    if w_facet > 0:
        qf = fr.query_facets(query)
        scored = []
        for i, c in enumerate(pool):
            bonus, _ = fr._facet_bonus(qf, c["content"], c.get("role", ""), c.get("month", ""))
            scored.append((bonus, i))
        facet_order = [i for b, i in sorted(scored, key=lambda x: -x[0]) if b > 0]
        if facet_order:
            rankings.append((w_facet, facet_order))

    # temporal: date-bearing prior
    if w_temporal > 0:
        dated = [i for i, c in enumerate(pool) if re.search(r"\d{4}", c["content"])]
        if dated:
            rankings.append((w_temporal, dated))

    rrf = {}
    for w, order in rankings:
        for rank, idx in enumerate(order, 1):
            rrf[idx] = rrf.get(idx, 0.0) + w / (RRF_K + rank)
    order = [i for i, _ in sorted(rrf.items(), key=lambda x: -x[1])]
    order += [i for i in np.argsort(-dense) if i not in rrf]
    return _metrics(order, pool, gold, (time.time() - t) * 1000,
                    f"qtype={qtype} weights(dense/fts/facet/temporal)={_WEIGHTS[qtype]}; "
                    f"{len(rankings)} signals")


def _method_d(dense, pool, gold, query):
    """Personalized-PageRank diffusion over a per-qid facet graph."""
    import numpy as np
    from radiomind.storage import facet_rerank as fr
    t = time.time()
    # graph nodes: memory indices (0..n-1) + facet nodes (strings)
    n = len(pool)
    facet_id: dict[str, int] = {}
    edges: list[tuple[int, int]] = []  # (memory_idx, facet_node_idx)

    def fnode(key):
        if key not in facet_id:
            facet_id[key] = n + len(facet_id)
        return facet_id[key]

    for i, c in enumerate(pool):
        cf = fr.query_facets(c["content"], c.get("month", ""))
        sid = c["turn_id"].rsplit("_t", 1)[0] if "_t" in c["turn_id"] else ""
        keys = ([f"ent:{e}" for e in cf["entities"]] + [f"num:{x}" for x in cf["numbers"]]
                + ([f"sess:{sid}"] if sid else []) + ([f"month:{c['month']}"] if c.get("month") else []))
        for k in keys:
            edges.append((i, fnode(k)))

    total = n + len(facet_id)
    if total == 0 or not edges:
        order = list(np.argsort(-dense))
        return _metrics(order, pool, gold, (time.time() - t) * 1000, "no graph edges; dense fallback")

    A = np.zeros((total, total), dtype=np.float32)
    for m, f in edges:
        A[m, f] = 1.0; A[f, m] = 1.0
    col = A.sum(axis=0); col[col == 0] = 1.0
    M = A / col  # column-stochastic

    # restart vector: query facet nodes + top-10 dense memory nodes
    qf = fr.query_facets(query)
    p = np.zeros(total, dtype=np.float32)
    for e in qf["entities"]:
        if f"ent:{e}" in facet_id:
            p[facet_id[f"ent:{e}"]] = 1.0
    for x in qf["numbers"]:
        if f"num:{x}" in facet_id:
            p[facet_id[f"num:{x}"]] = 1.0
    for idx in np.argsort(-dense)[:10]:
        p[idx] += 1.0
    if p.sum() == 0:
        p[np.argsort(-dense)[:10]] = 1.0
    p /= p.sum()

    r = p.copy()
    for _ in range(3):  # 3 diffusion steps
        r = 0.15 * p + 0.85 * (M @ r)
    g = r[:n]
    g = g / (g.max() or 1.0)
    d = dense / (dense.max() or 1.0)
    final = d + BETA * g
    order = list(np.argsort(-final))
    activated = sum(1 for e in qf["entities"] if f"ent:{e}" in facet_id) + \
                sum(1 for x in qf["numbers"] if f"num:{x}" in facet_id)
    return _metrics(order, pool, gold, (time.time() - t) * 1000,
                    f"beta={BETA}; {len(facet_id)} facet nodes, {activated} query-activated")


# ----------------------------- driver -----------------------------
def probe_qid(mind, embedder, target, idx):
    import numpy as np
    qid = target["question_id"]; query = target["question"]
    domain = f"rerankalt_{idx}"
    _ingest_qid(mind, target, domain)
    gold = _gold_turn_ids(target)
    pool = _candidate_pool(mind, domain)
    if not pool:
        return None
    E = _embed_matrix(embedder, [c["content"] for c in pool])
    q = _embed_matrix(embedder, [query])[0]
    dense = E @ q
    topN_idx = list(np.argsort(-dense)[:POOL])

    base, _ = _baseline(dense, pool, gold)
    methods = {
        "0_dense_baseline": base,
        "A_hubness": _method_a(dense, E, topN_idx, pool, gold),
        "B_mmr": _method_b(dense, E, topN_idx, pool, gold),
        "C_qa_rrf": _method_c(dense, pool, gold, query, mind._store),
        "D_graph": _method_d(dense, pool, gold, query),
    }
    return {"qid": qid, "question": query[:140],
            "question_type": target.get("question_type", "?"),
            "gold_turns": sorted(gold), "pool_size": len(pool), "methods": methods}


def _agg(rows):
    import statistics as st
    out = {}
    for m in ["0_dense_baseline", "A_hubness", "B_mmr", "C_qa_rrf", "D_graph"]:
        vals = [r["methods"][m] for r in rows]
        def mean(key):
            xs = [v[key] for v in vals if v.get(key) is not None]
            return round(st.mean(xs), 3) if xs else None
        br = [v["best_rank"] or 9999 for v in vals]
        out[m] = {"recall@5": mean("recall_at_5"), "recall@10": mean("recall_at_10"),
                  "recall@30": mean("recall_at_30"),
                  "median_best_rank": st.median(br),
                  "mean_redundancy@30": mean("redundancy_top30"),
                  "mean_latency_ms": mean("latency_ms")}
    return out


def _print(result):
    rows = result["results"]
    print(f"\nRerankerAlternative-1a — {len(rows)} qids (baseline=ONNX dense)")
    agg = result["aggregate"]
    print("=" * 96)
    print(f"{'method':18} {'r@5':>6} {'r@10':>6} {'r@30':>6} {'med_rank':>9} {'redund':>7} {'lat_ms':>8}")
    print("-" * 96)
    for m, a in agg.items():
        print(f"{m:18} {str(a['recall@5']):>6} {str(a['recall@10']):>6} {str(a['recall@30']):>6} "
              f"{a['median_best_rank']:>9} {str(a['mean_redundancy@30']):>7} {str(a['mean_latency_ms']):>8}")
    print("-" * 96)
    # per-qid best_rank
    print(f"\n{'qid':16} {'type':14} {'base':>5} {'A':>5} {'B':>5} {'C':>5} {'D':>5}")
    for r in rows:
        m = r["methods"]
        def br(k):
            return m[k]["best_rank"] or "∞"
        print(f"{r['qid']:16} {r['question_type'][:14]:14} "
              f"{br('0_dense_baseline'):>5} {br('A_hubness'):>5} {br('B_mmr'):>5} "
              f"{br('C_qa_rrf'):>5} {br('D_graph'):>5}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--qids", default="")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--sandbox", default="/tmp/rm-rerankalt")
    ap.add_argument("--report", default="")
    args = ap.parse_args()

    if args.report:
        _print(json.loads(Path(args.report).read_text())); return 0
    if not DATASET.exists():
        print(f"dataset missing: {DATASET}", file=sys.stderr); return 2

    os.environ["RADIOMIND_HOME"] = args.sandbox
    os.environ["RADIOMIND_REMOTE_RETRIEVAL"] = "0"
    sb = Path(args.sandbox)
    if sb.exists():
        shutil.rmtree(sb)
    sb.mkdir(parents=True, exist_ok=True)

    embedder, msg = _load_embedder()
    if embedder is None:
        print(f"BLOCKED: ONNX embedding baseline unavailable ({msg}). "
              f"Install radiomind[embedding]; NOT falling back to remote.", file=sys.stderr)
        return 3

    data = json.loads(DATASET.read_text())
    by = {r["question_id"]: r for r in data}
    requested = [q.strip() for q in args.qids.split(",") if q.strip()] or None
    qids = _select_qids(data, requested)

    from radiomind.core.mind import RadioMind
    mind = RadioMind(); mind.initialize()
    mind._embedder = None; mind._reranker = None  # keep mind.search = FTS for method C

    results = []
    t_all = time.time()
    for i, qid in enumerate(qids):
        t0 = time.time()
        try:
            res = probe_qid(mind, embedder, by[qid], i)
            if res:
                results.append(res)
                print(f"[{i+1}/{len(qids)}] {qid:16} pool={res['pool_size']:4} "
                      f"({time.time()-t0:.1f}s)", flush=True)
        except Exception as e:
            print(f"[{i+1}/{len(qids)}] {qid} FAILED: {type(e).__name__}: {e}", flush=True)
    mind.shutdown()

    out = {"experiment": "RerankerAlternative-1a", "dataset": str(DATASET),
           "params": {"ALPHA": ALPHA, "LAMBDA": LAMBDA, "BETA": BETA, "RRF_K": RRF_K,
                      "POOL": POOL, "TOPN": TOPN},
           "target_qids": [q for q in TARGET_QIDS if q in by],
           "control_qids": [q for q in qids if q not in TARGET_QIDS],
           "elapsed_s": round(time.time() - t_all, 1),
           "results": results, "aggregate": _agg(results)}
    Path(args.out).write_text(json.dumps(out, indent=2))
    print(f"\nwrote {args.out}")
    _print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
