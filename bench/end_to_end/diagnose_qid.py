"""diagnose_qid — Phase 1 layered probe for a single LME-S qid.

Read-only. NO model behavior change. NO judge call. NO full e2e.
Captures every layer's signal so future audits start from one
JSON snapshot instead of 4 ad-hoc scripts.

Usage:
  python diagnose_qid.py --qid bb7c3b45
  python diagnose_qid.py --qid c18a7dc8 --sandbox /tmp/rm-diag --keep-sandbox

Outputs:
  - stdout: human-readable per-layer summary
  - JSON file (default bench/end_to_end/diagnose-<qid>.json) with:
      qid, question, gold, qtype, answer_session_ids
      ingest_stats {turns, sessions}
      retrieve_top_30 [{rank, turn_id, session_id, is_gold_session,
                       score, content_preview}]
      helper_signals {
        role_mismatch_guard: str (or ""),
        cashback_arithmetic_hint: str,
        savings_arithmetic_hint: str,
        person_age_average_hint: str,
        temporal_endpoint_support_guard: str,
        run_temporal_precision: str,
        run_open_domain_specific: str,
      }
      structured_skill_section: {name, conf, computed_answer} or None
      jab_what_if {gold_is_abstain, would_veto_canonical_abstain}

Out-of-scope for Phase 1:
  - Diff vs baseline artifact (Phase 1.5)
  - LLM answer / judge (use existing runner --qids for that)
  - Mutating helpers (no behavior change)
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


def _ingest_qid(mind, target: dict, domain: str) -> dict:
    """Ingest haystack into the per-qid domain. Returns stats."""
    turns: list[dict] = []
    n_sessions = 0
    for s_idx, session in enumerate(target["haystack_sessions"]):
        sid = (target["haystack_session_ids"][s_idx]
               if s_idx < len(target.get("haystack_session_ids", []))
               else f"s{s_idx}")
        sdate = (target["haystack_dates"][s_idx]
                 if s_idx < len(target.get("haystack_dates", []))
                 else "")
        n_sessions += 1
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
    return {
        "turns_ingested": stats.get("ingested", len(turns)),
        "sessions": n_sessions,
        "turns_total": len(turns),
    }


# Match the runner's top_k=200 default (see run_longmemeval_mem0.py
# line 441). Earlier diagnostic versions used top_k=30 which caused
# SavingsHint and other multi-anchor helpers to falsely report
# "silent" because one anchor was ranked outside the smaller window.
RUNNER_TOP_K = 200


def _probe_retrieve(mind, question: str, domain: str,
                    gold_sids: set[str],
                    top_k: int = RUNNER_TOP_K) -> list[dict]:
    results = mind.search(question, domain=domain, max_results=top_k)
    out: list[dict] = []
    for i, r in enumerate(results, 1):
        entry = getattr(r, "entry", r)
        content = getattr(entry, "content", "") or ""
        meta = getattr(entry, "metadata", {}) or {}
        if not isinstance(meta, dict):
            meta = {}
        tid = meta.get("turn_id", "")
        session_id = tid.rsplit("_t", 1)[0] if "_t" in tid else ""
        out.append({
            "rank": i,
            "turn_id": tid,
            "session_id": session_id,
            "is_gold_session": session_id in gold_sids,
            "score": round(float(getattr(r, "score", 0.0)), 4),
            "content_preview": content[:160].replace("\n", " "),
        })
    return out


def _build_mem_results(mind, question: str, domain: str,
                      top_k: int = RUNNER_TOP_K) -> list[dict]:
    """Build the runner-format mem_results list. Uses top_k=200
    by default to match what helpers see in production."""
    results = mind.search(question, domain=domain, max_results=top_k)
    out = []
    for r in results[:top_k]:
        sdate = (r.entry.metadata or {}).get("session_date", "")
        out.append({
            "memory": r.entry.content,
            "score": float(getattr(r, "score", 0.0)),
            "created_at": sdate,
        })
    return out


def _safe(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        return f"[error: {e.__class__.__name__}: {e}]"


def _probe_helpers(mind, question: str, mem_results: list[dict],
                   q_date: str, domain: str) -> dict:
    """Probe each registered helper / skill section in isolation.
    Returns both raw signal strings AND structured diagnose_*
    records (Phase 1.5 — refusal-reason instrumentation)."""
    signals: dict[str, str] = {}
    proofs: dict[str, dict] = {}

    # role_mismatch_guard
    from radiomind.core.role_mismatch_guard import role_mismatch_guard
    signals["role_mismatch_guard"] = _safe(
        role_mismatch_guard, question, mem_results,
    )

    # cashback_arithmetic_hint + savings_arithmetic_hint
    # IMPORTANT: pass mind/domain so these signals exercise the SAME
    # SelfAnchor store-scan path the runner uses. Without them the
    # diagnostic would silently skip the supplement and disagree with
    # production (e.g. self_anchor_probe says recovered=true while the
    # signal shows "").
    from radiomind.core.arithmetic_hint import (
        cashback_arithmetic_hint, savings_arithmetic_hint,
        diagnose_savings, diagnose_cashback,
    )
    signals["cashback_arithmetic_hint"] = _safe(
        cashback_arithmetic_hint, question, mem_results,
        mind=mind, domain=domain,
    )
    signals["savings_arithmetic_hint"] = _safe(
        savings_arithmetic_hint, question, mem_results,
        mind=mind, domain=domain,
    )
    proofs["savings"] = _safe(diagnose_savings, question, mem_results)
    proofs["cashback"] = _safe(diagnose_cashback, question, mem_results)

    # person_age_average_hint
    from radiomind.core.typed_event_hint import (
        person_age_average_hint, diagnose_person_age,
    )
    signals["person_age_average_hint"] = _safe(
        person_age_average_hint, question, mem_results,
        mind=mind, domain=domain,
    )
    proofs["person_age"] = _safe(
        diagnose_person_age, question, mem_results,
    )

    # temporal_endpoint_support_guard
    from radiomind.core.temporal_endpoint_guard import (
        temporal_endpoint_support_guard,
    )
    signals["temporal_endpoint_support_guard"] = _safe(
        temporal_endpoint_support_guard,
        question, mem_results,
        mind=mind, domain=domain,
    )

    # Skill-registry route (age_interval, temporal, etc.)
    signals["run_temporal_precision"] = _safe(
        mind.run_temporal_precision,
        query=question, retrieved_memories=mem_results,
        reference_date=q_date, domain=domain,
    )
    signals["run_open_domain_specific"] = _safe(
        mind.run_open_domain_specific,
        query=question, retrieved_memories=mem_results, domain=domain,
    )

    # age_interval diagnose runs AFTER run_temporal_precision so it
    # can parse the STRUCTURED SKILL section that the runner injects.
    from radiomind.core.age_interval_commit import diagnose_age_interval
    proofs["age_interval"] = _safe(
        diagnose_age_interval,
        question, mem_results,
        temporal_section=signals.get("run_temporal_precision", "") or "",
    )

    return {"signals": signals, "proofs": proofs}


def _probe_self_anchor(mind, domain: str, proofs: dict,
                       question: str) -> dict:
    """SelfAnchor-1c: when a helper's refusal is a self-anchor recall
    gap, show whether the store-scan supplement WOULD recover it, with
    the same proof fields the production hint carries (recovered /
    source_turn_id / scan_scope / quote).

    Mirrors the production wiring: only probes a scan when the matching
    helper refused for the corresponding self-anchor reason.
    """
    from radiomind.core.self_anchor import (
        scan_current_age_user_turns, scan_paid_price_user_turns,
        scan_cashback_rate_user_turns,
    )
    out: dict = {}

    def _proof_to_dict(p):
        if p is None or not hasattr(p, "value"):
            return {"recovered": False}
        return {
            "recovered": True,
            "value": p.value,
            "source_turn_id": p.source_turn_id,
            "scan_scope": p.scan_scope,
            "quote": p.quote,
        }

    # current age — relevant to age_interval (current_age_not_in_retrieved)
    # and person_age (kin_role_missing=['self'])
    ai = proofs.get("age_interval") or {}
    pa = proofs.get("person_age") or {}
    age_relevant = (
        ai.get("refusal_reason") == "current_age_not_in_retrieved"
        or pa.get("missing_roles") == ["self"]
    )
    if age_relevant:
        out["current_age"] = _proof_to_dict(
            _safe(scan_current_age_user_turns, mind, domain)
            if mind is not None else None)

    # paid price — relevant to SavingsHint
    sv = proofs.get("savings") or {}
    if sv.get("refusal_reason") == "paid_anchor_not_found_in_user_turns":
        anchor = sv.get("anchor")
        if anchor:
            out["paid_price"] = _proof_to_dict(
                _safe(scan_paid_price_user_turns, mind, domain, anchor))

    # cashback rate — relevant to cashback (SelfAnchor-2b). Probe only
    # when retrieve-side refused for a rate-missing reason AND a
    # merchant is known. Also surface whether the amount IS present,
    # since 2b only supplements the rate (not the amount).
    cb = proofs.get("cashback") or {}
    _RATE_MISSING = {
        "no_cashback_rate_in_memories", "rate_merchant_mismatch",
        "rate_anchor_unscoped", "rate_not_supporting_target_merchant",
    }
    if cb.get("refusal_reason") in _RATE_MISSING and cb.get("merchant"):
        d = _proof_to_dict(
            _safe(scan_cashback_rate_user_turns, mind, domain,
                  cb.get("merchant")))
        d["amount_in_retrieve"] = cb.get("amount") is not None
        out["cashback_rate"] = d
    return out


def _probe_store_anchors(mind, domain: str, question: str) -> dict:
    """Scan the full domain FACT store and contrast against retrieve
    top-K. Surfaces anchors that exist in the store but didn't make
    it into retrieved context — the helper-vs-retrieve-recall
    distinction the user/Codex flagged.

    Probes these anchor families (independent of helper code):
      - dollar amounts: `$N` in FACT entries
      - age phrases (strict): `at the age of N` / `when I was N`
      - age phrases (loose):  `at age N` / `aged N` / etc.

    Returns counts + sample snippets.
    """
    out: dict = {
        "fact_entries_total": 0,
        "dollar_amounts_in_store": [],
        "age_strict_in_store": [],
        "age_loose_in_store": [],
    }
    try:
        from radiomind.core.types import MemoryLevel
        facts = mind._store.list_by_domain(
            domain, level=MemoryLevel.FACT, limit=500,
        )
    except Exception as e:
        out["error"] = str(e)
        return out
    out["fact_entries_total"] = len(facts)
    DOL_RE = re.compile(r"\$\s*(\d[\d,]*(?:\.\d+)?)")
    STRICT_AGE = re.compile(
        r"(?:at\s+the\s+age\s+of|when\s+I\s+was|aged)\s+(\d{1,3})",
        re.IGNORECASE,
    )
    LOOSE_AGE = re.compile(
        r"\b(?:at\s+(?:the\s+)?age(?:\s+of)?|aged|when\s+i\s+was|"
        r"i\s+(?:was|am)|when\s+i\s+turned|turned)\s+(\d{1,3})\b",
        re.IGNORECASE,
    )
    for f in facts[:500]:
        text = (f.content or "")[:600]
        for m in DOL_RE.finditer(text):
            out["dollar_amounts_in_store"].append({
                "amount": m.group(1),
                "snippet": text[max(0, m.start()-30):m.end()+50],
            })
        for m in STRICT_AGE.finditer(text):
            out["age_strict_in_store"].append({
                "age": int(m.group(1)),
                "snippet": text[max(0, m.start()-30):m.end()+50],
            })
        for m in LOOSE_AGE.finditer(text):
            out["age_loose_in_store"].append({
                "age": int(m.group(1)),
                "snippet": text[max(0, m.start()-30):m.end()+50],
            })
    # Cap sample sizes for JSON readability
    out["dollar_amounts_in_store"] = out["dollar_amounts_in_store"][:15]
    out["age_strict_in_store"] = out["age_strict_in_store"][:10]
    out["age_loose_in_store"] = out["age_loose_in_store"][:10]
    return out


def _parse_structured_skill(section: str) -> dict | None:
    """Extract STRUCTURED SKILL parameters if present."""
    if not section or "STRUCTURED SKILL" not in section:
        return None
    mh = re.search(
        r"STRUCTURED SKILL \((\w+), conf=([\d.]+)\)", section,
    )
    ma = re.search(r"Computed answer:\s*(.+?)\s*(?:\n|$)", section)
    if not mh:
        return None
    try:
        conf = float(mh.group(2))
    except (TypeError, ValueError):
        conf = None
    return {
        "skill_name": mh.group(1),
        "confidence": conf,
        "computed_answer": ma.group(1).strip() if ma else None,
    }


def _jab_what_if(gold: str) -> dict:
    """What would the JAB-1a veto decide if the response were a
    canonical abstain? (Read-only probe — no judge call.)"""
    from jab1_abstain_veto import is_abstain_gold, should_veto
    canonical_abstain = "The information provided is not enough."
    return {
        "gold": gold[:100],
        "gold_is_abstain": is_abstain_gold(gold),
        "would_veto_canonical_abstain": should_veto(
            gold, canonical_abstain,
        ),
    }


def _print_summary(rec: dict) -> None:
    print("\n" + "=" * 78)
    print(f"diagnose_qid: {rec['qid']}")
    print("=" * 78)
    print(f"\nQ:    {rec['question']}")
    print(f"gold: {rec['gold'][:140]}")
    print(f"qtype: {rec.get('qtype')}")
    print(f"answer_session_ids: {rec.get('answer_session_ids', [])}")
    ing = rec["ingest_stats"]
    print(f"\ningest: {ing['turns_ingested']} turns / "
          f"{ing['sessions']} sessions")

    rw = rec["retrieve_window"]
    print(f"\nretrieve (top_k={rw['top_k_probed']}): "
          f"{rw['gold_hits_in_top_200']} gold-session hits in top-200, "
          f"{rw['gold_hits_in_top_30']} in top-30 "
          f"(first 10 ranks: {rw['gold_ranks_first_10']})")
    rt = rec["retrieve_top_30_preview"]
    for r in rt[:10]:
        gold_mark = "★" if r["is_gold_session"] else " "
        print(f"  {gold_mark} rank {r['rank']:>2} score={r['score']:.4f} "
              f"{r['turn_id']:<24} {r['content_preview'][:80]}")
    if len(rt) > 10:
        print(f"  ... ({len(rt)-10} more in JSON)")

    print(f"\nhelper signals (non-empty only):")
    fired = 0
    for k, v in rec["helper_signals"].items():
        if v and not v.startswith("[error"):
            fired += 1
            print(f"\n  ↪ {k}:")
            print(f"    {v[:300].strip()}")
    if not fired:
        print("  (all helpers silent)")

    # Phase 1.5 — refusal-reason proofs
    print(f"\nhelper proofs (refusal reasons / proof state):")
    for k, p in rec.get("helper_proofs", {}).items():
        if not isinstance(p, dict):
            print(f"  {k}: {p}")
            continue
        fired_flag = p.get("fired", False)
        reason = p.get("refusal_reason")
        mark = "✓ FIRED" if fired_flag else f"✗ refused: {reason}"
        # Show key extracted state
        extras = []
        for key in ("anchor", "paid_amounts", "retail_amounts",
                    "computed_saving", "rate", "merchant", "amount",
                    "computed_cashback", "kin_ages", "missing_roles",
                    "ambiguous_roles", "computed_mean",
                    "skill_name", "skill_conf", "skill_computed",
                    "found_age_at_event_strict",
                    "found_age_variant_loose", "found_current_age",
                    "variant_mismatch_detected"):
            if key in p and p[key] not in (None, [], {}):
                extras.append(f"{key}={p[key]!r}")
        print(f"  {k:<14} {mark}")
        if extras:
            print(f"    state: {'; '.join(extras[:5])}")

    # SelfAnchor-1c — store-scan recovery probe
    sap = rec.get("self_anchor_probe", {})
    if sap:
        print(f"\nself-anchor store-scan probe:")
        for kind, p in sap.items():
            if p.get("recovered"):
                print(f"  ↪ {kind}: RECOVERED value={p.get('value')} "
                      f"from {p.get('source_turn_id')} "
                      f"scope={p.get('scan_scope')}")
                print(f"     quote: {p.get('quote','')[:90]}")
            else:
                print(f"  ↪ {kind}: not recoverable")

    # Phase 1.5 — store anchor probe
    sa = rec.get("store_anchor_probe", {})
    print(f"\nstore anchor probe (FACT-layer):")
    print(f"  FACT entries total: {sa.get('fact_entries_total', 0)}")
    print(f"  $ amounts in store: {len(sa.get('dollar_amounts_in_store', []))} samples")
    for d in (sa.get('dollar_amounts_in_store') or [])[:5]:
        print(f"    ${d.get('amount')}: {d.get('snippet','')[:100]}")
    print(f"  age (strict) in store: "
          f"{len(sa.get('age_strict_in_store', []))} hits")
    for d in (sa.get('age_strict_in_store') or [])[:3]:
        print(f"    age={d.get('age')}: {d.get('snippet','')[:100]}")
    print(f"  age (loose) in store: "
          f"{len(sa.get('age_loose_in_store', []))} hits")
    for d in (sa.get('age_loose_in_store') or [])[:3]:
        print(f"    age={d.get('age')}: {d.get('snippet','')[:100]}")

    ss = rec.get("structured_skill_section")
    if ss:
        print(f"\nSTRUCTURED SKILL: {ss}")
    else:
        print(f"\nSTRUCTURED SKILL: (none fired)")

    print(f"\nJAB-1a what-if:")
    j = rec["jab_what_if"]
    print(f"  gold_is_abstain={j['gold_is_abstain']}; "
          f"would_veto_canonical_abstain={j['would_veto_canonical_abstain']}")
    print()


_CANON_ABSTAIN = "The information provided is not enough."


def _probe_closure_view(question: str, mem_results: list[dict],
                        mind, domain: str, temporal_section: str = "") -> dict:
    """Phase2-2b: project the closure rewrite decision for this qid —
    "would a committer commit, or a suppressor downgrade, this answer?"

    Read-only what-if. Calls the REAL proof builders + gates with
    deterministic sample answers; does NOT change runner behaviour or
    ordering and builds no dispatcher. Preserves the two-family polarity
    split (see 2026-06-01 diagnostic-ux audit): committers commit on a
    pure abstain; suppressors downgrade a concrete over-commit.

    Scope (2b): cashback committer + role/TESG suppressors. age committer
    is deferred until a shared age proof resolver is extracted (the audit
    flags that hand-reconstructing age's gates here would duplicate the
    production gate sequence).
    """
    out: dict = {"committers": {}, "suppressors": {}}

    # ---- committer: cashback ----
    try:
        from radiomind.core.arithmetic_hint import (
            resolve_cashback_proof, cashback_proof_to_result,
        )
        from radiomind.core.proof_result import commit_on_abstain
        pdict = resolve_cashback_proof(
            question, mem_results, mind=mind, domain=domain,
        )
        if pdict is None:
            out["committers"]["cashback"] = {"proof_available": False}
        else:
            pr = cashback_proof_to_result(pdict)
            sample_concrete = "You earned $1.23 in cashback at TestMart."
            out["committers"]["cashback"] = {
                "proof_available": True,
                "proof": {
                    "kind": pr.kind, "value": pr.value, "inputs": pr.inputs,
                    "sources": [{"turn_id": s.turn_id, "quote": s.quote,
                                 "role": s.role} for s in pr.sources],
                    "recompute_ok": pr.recompute_ok, "subject": pr.subject,
                    "scan_scope": pr.scan_scope, "rendered": pr.rendered,
                },
                "would_commit_on_canonical_abstain":
                    commit_on_abstain(pr, _CANON_ABSTAIN) == pr.rendered,
                "would_overwrite_concrete_answer":
                    commit_on_abstain(pr, sample_concrete) != sample_concrete,
            }
    except Exception as e:  # diagnostic must never crash the probe
        out["committers"]["cashback"] = {"error": repr(e)}

    # ---- committer: age_interval (Phase2-2c) ----
    try:
        from radiomind.core.age_interval_commit import (
            resolve_age_interval_proof,
        )
        from radiomind.core.proof_result import commit_on_abstain
        pr = resolve_age_interval_proof(
            question, mem_results, temporal_section, mind=mind, domain=domain)
        if pr is None:
            out["committers"]["age_interval"] = {"proof_available": False}
        else:
            sample_concrete = "You are 7 years older."
            out["committers"]["age_interval"] = {
                "proof_available": True,
                "proof": {
                    "kind": pr.kind, "value": pr.value, "inputs": pr.inputs,
                    "sources": [{"turn_id": s.turn_id, "quote": s.quote,
                                 "role": s.role} for s in pr.sources],
                    "recompute_ok": pr.recompute_ok, "subject": pr.subject,
                    "scan_scope": pr.scan_scope, "confidence": pr.confidence,
                    "rendered": pr.rendered,
                },
                "would_commit_on_canonical_abstain":
                    commit_on_abstain(pr, _CANON_ABSTAIN) == pr.rendered,
                "would_overwrite_concrete_answer":
                    commit_on_abstain(pr, sample_concrete) != sample_concrete,
            }
    except Exception as e:
        out["committers"]["age_interval"] = {"error": repr(e)}

    # ---- suppressor: role ----
    try:
        from radiomind.core.role_mismatch_guard import (
            detect_role_mismatch, maybe_rewrite_with_guard,
        )
        det = detect_role_mismatch(question, mem_results)
        sample = "You manage a team of 12 engineers."
        supp = maybe_rewrite_with_guard(question, mem_results, sample)
        byp = maybe_rewrite_with_guard(question, mem_results, _CANON_ABSTAIN)
        out["suppressors"]["role"] = {
            "detection": det,
            "would_suppress_sample_overcommit": supp != sample,
            "would_bypass_canonical_abstain": byp == _CANON_ABSTAIN,
            "rendered_if_suppressed": supp if supp != sample else None,
        }
    except Exception as e:
        out["suppressors"]["role"] = {"error": repr(e)}

    # ---- suppressor: temporal endpoint ----
    try:
        from radiomind.core.temporal_endpoint_guard import (
            detect_temporal_endpoint_mismatch,
            maybe_rewrite_with_temporal_guard,
        )
        det = detect_temporal_endpoint_mismatch(
            question, mem_results, mind=mind, domain=domain)
        sample = "You worked there for 5 years."
        supp = maybe_rewrite_with_temporal_guard(
            question, mem_results, sample, mind=mind, domain=domain)
        byp = maybe_rewrite_with_temporal_guard(
            question, mem_results, _CANON_ABSTAIN, mind=mind, domain=domain)
        out["suppressors"]["temporal_endpoint"] = {
            "detection": det,
            "would_suppress_sample_overcommit": supp != sample,
            "would_bypass_canonical_abstain": byp == _CANON_ABSTAIN,
            "rendered_if_suppressed": supp if supp != sample else None,
        }
    except Exception as e:
        out["suppressors"]["temporal_endpoint"] = {"error": repr(e)}

    return out


def _print_closure_view(cv: dict) -> None:
    if not cv:
        return
    print("=== closure_view (Phase2: would a closure rewrite the answer?) ===")
    for name, v in (cv.get("committers") or {}).items():
        if v.get("error"):
            print(f"  committer {name}: error {v['error']}"); continue
        if not v.get("proof_available"):
            print(f"  committer {name}: no proof → would NOT commit"); continue
        pr = v.get("proof", {})
        print(f"  committer {name}: value={pr.get('value')} "
              f"recompute_ok={pr.get('recompute_ok')} "
              f"commit_on_abstain={v.get('would_commit_on_canonical_abstain')} "
              f"overwrite_concrete={v.get('would_overwrite_concrete_answer')}")
        print(f"      rendered: {pr.get('rendered')!r}")
    for name, v in (cv.get("suppressors") or {}).items():
        if v.get("error"):
            print(f"  suppressor {name}: error {v['error']}"); continue
        print(f"  suppressor {name}: detected={'yes' if v.get('detection') else 'no'} "
              f"suppress_overcommit={v.get('would_suppress_sample_overcommit')} "
              f"bypass_abstain={v.get('would_bypass_canonical_abstain')}")
    print()


def _classify_layer(retrieval: dict, det: dict, closure: dict,
                    structured) -> tuple[str, str]:
    """Conservative diagnosis.layer (DX-2a). Only the labels the deterministic
    sections can prove; answer/judge/parked labels are left to DX-2b's e2e
    overlay."""
    committers = closure.get("committers") or {}
    suppressors = closure.get("suppressors") or {}
    for n, v in committers.items():
        if v.get("proof_available") and v.get("would_commit_on_abstain"):
            return ("closure_ready",
                    f"{n} committer proof ready; if e2e abstains it's a "
                    f"trust-gap or answer-path issue")
    for n, v in suppressors.items():
        if v.get("detected"):
            return ("closure_ready",
                    f"{n} suppressor detected; would downgrade an overcommit")
    if det.get("refused"):
        r = det["refused"][0]
        return "helper_refusal", f"{r['helper']} refused: {r['reason']}"
    if det.get("fired"):
        return ("proof_ready",
                f"helper(s) {det['fired']} produced proof; line may be "
                f"hint-only (no closure)")
    if retrieval.get("gold_hits_top_200") == 0:
        return "retrieval_gap", "no gold sessions in top-200 retrieve"
    if structured:
        return ("skill_route_gap",
                "structured skill present but no closure/helper resolved it")
    return "unknown", "insufficient deterministic evidence to localize"


def build_path_summary(rec: dict) -> dict:
    """DX-2a: derive a single failure-location path from the existing
    diagnose sections (retrieval -> helper proof -> skill route -> closure
    decision -> diagnosis). Pure projection — no new probes, no LLM. Prefers
    helper_proofs / closure_view over raw helper_signals."""
    rw = rec.get("retrieve_window") or {}
    retrieval = {
        "gold_hits_top_200": rw.get("gold_hits_in_top_200"),
        "gold_hits_top_30": rw.get("gold_hits_in_top_30"),
    }

    proofs = rec.get("helper_proofs") or {}
    fired, refused = [], []
    for name, p in proofs.items():
        if not isinstance(p, dict):
            continue
        reason = p.get("refusal_reason")
        if reason:
            refused.append({"helper": name, "reason": reason})
        else:
            fired.append(name)

    cv = rec.get("closure_view") or {}
    committers = cv.get("committers") or {}
    suppressors = cv.get("suppressors") or {}
    closure_decision = {
        "committers": {
            n: ({"error": True} if not isinstance(v, dict) or "error" in v else {
                "proof_available": bool(v.get("proof_available")),
                "would_commit_on_abstain":
                    v.get("would_commit_on_canonical_abstain"),
                "would_overwrite_concrete":
                    v.get("would_overwrite_concrete_answer"),
            })
            for n, v in committers.items()
        },
        "suppressors": {
            n: {
                "detected": bool(v.get("detection")) if isinstance(v, dict) else False,
                "would_suppress_overcommit":
                    v.get("would_suppress_sample_overcommit")
                    if isinstance(v, dict) else None,
            }
            for n, v in suppressors.items()
        },
    }
    deterministic_layer = {
        "fired": fired,
        "refused": refused,
        "proofs_available": [
            n for n, v in committers.items()
            if isinstance(v, dict) and v.get("proof_available")
        ],
    }

    sig = rec.get("helper_signals") or {}

    def _route(key):
        v = sig.get(key)
        if v is None:
            return "absent"
        return "fired" if str(v).strip() else "silent"

    structured = rec.get("structured_skill_section")
    skill_route = {
        "temporal_precision": _route("run_temporal_precision"),
        "open_domain_specific": _route("run_open_domain_specific"),
        # DX-2a gap: diagnose_qid does not probe run_list_ordering yet.
        "list_ordering": "not_probed",
        "structured_skill": (
            structured.get("skill_name") if isinstance(structured, dict)
            else ("present" if structured else None)),
    }

    layer, reason = _classify_layer(
        retrieval, deterministic_layer, closure_decision, structured)
    return {
        "qid": rec.get("qid"),
        "retrieval": retrieval,
        "deterministic_layer": deterministic_layer,
        "skill_route": skill_route,
        "closure_decision": closure_decision,
        "diagnosis": {"layer": layer, "reason": reason},
    }


def _print_path_summary(s: dict) -> None:
    if not s:
        return
    r = s.get("retrieval") or {}
    det = s.get("deterministic_layer") or {}
    cl = s.get("closure_decision") or {}
    dx = s.get("diagnosis") or {}
    print("=== PATH SUMMARY (DX-2a: where did this qid fail?) ===")
    print(f"  retrieval:     gold {r.get('gold_hits_top_200')}/200, "
          f"{r.get('gold_hits_top_30')}/30")
    fired = ", ".join(det.get("fired") or []) or "none"
    refused = ", ".join(f"{x['helper']}({x['reason']})"
                        for x in (det.get("refused") or [])) or "none"
    print(f"  deterministic: fired=[{fired}] refused=[{refused}] "
          f"proofs={det.get('proofs_available') or []}")
    print(f"  skill route:   {s.get('skill_route')}")
    commit_acts = [n for n, v in (cl.get('committers') or {}).items()
                   if v.get('would_commit_on_abstain')]
    supp_acts = [n for n, v in (cl.get('suppressors') or {}).items()
                 if v.get('detected')]
    print(f"  closure:       would-commit={commit_acts or 'none'} "
          f"suppressors-detected={supp_acts or 'none'}")
    print(f"  >> diagnosis:  {dx.get('layer')} — {dx.get('reason')}")
    print()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--qid", required=True)
    p.add_argument("--sandbox", type=Path, default=None,
                   help="Per-qid sandbox path. Defaults to "
                        "/tmp/rm-diagnose-qid-<qid> so multiple qids "
                        "don't clobber each other.")
    p.add_argument("--keep-sandbox", action="store_true",
                   help="Skip wiping the sandbox; reuse if already "
                        "ingested for this qid.")
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args()
    if args.sandbox is None:
        args.sandbox = Path(f"/tmp/rm-diagnose-qid-{args.qid}")

    if not DATASET.exists():
        print(f"dataset missing: {DATASET}", flush=True)
        return 2
    data = json.loads(DATASET.read_text())
    target = next(
        (q for q in data
         if (q.get("question_id") or q.get("id")) == args.qid),
        None,
    )
    if target is None:
        print(f"qid {args.qid} not in dataset", flush=True)
        return 2

    # Sandbox setup
    domain = f"diag_{args.qid}"
    already_ingested = (
        args.keep_sandbox and args.sandbox.exists()
        and (args.sandbox / "config.toml").exists()
    )
    if not already_ingested:
        if args.sandbox.exists():
            shutil.rmtree(args.sandbox)
        args.sandbox.mkdir(parents=True, exist_ok=True)
        cfg_src = Path.home() / ".radiomind" / "config.toml"
        cfg_content = cfg_src.read_text()
        (args.sandbox / "config.toml").write_text(
            cfg_content.replace(str(Path.home() / ".radiomind"),
                                  str(args.sandbox))
        )
    os.environ["RADIOMIND_HOME"] = str(args.sandbox)
    config_path = args.sandbox / "config.toml"

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

    # Ingest (skip if reusing)
    if not already_ingested:
        ingest_stats = _ingest_qid(mind, target, domain)
    else:
        ingest_stats = {"turns_ingested": -1, "sessions": -1,
                         "turns_total": -1, "note": "reused sandbox"}

    question = target["question"]
    gold = str(target.get("answer", ""))
    q_date = target.get("question_date", "")
    qtype = target.get("question_type", "?")
    gold_sids = set(target.get("answer_session_ids", []))

    # retrieve display: capture top-200 for accurate gold-recall
    # counts, but the JSON / human summary will show top-30 head
    # for readability.
    retrieve_full = _probe_retrieve(mind, question, domain, gold_sids,
                                    top_k=RUNNER_TOP_K)
    retrieve = retrieve_full[:30]
    # mem_results uses the runner's full window so helper probes
    # see the same input shape as production.
    mem_results = _build_mem_results(mind, question, domain,
                                     top_k=RUNNER_TOP_K)
    probe_out = _probe_helpers(
        mind, question, mem_results, q_date, domain,
    )
    helper_signals = probe_out["signals"]
    helper_proofs = probe_out["proofs"]
    structured = _parse_structured_skill(
        helper_signals.get("run_temporal_precision", "") or "",
    )
    store_anchors = _probe_store_anchors(mind, domain, question)
    self_anchor = _probe_self_anchor(mind, domain, helper_proofs, question)
    closure_view = _safe(
        _probe_closure_view, question, mem_results, mind, domain,
        helper_signals.get("run_temporal_precision", "") or "",
    )

    # Aggregate gold-recall stats across the full top-200 window
    gold_in_top200 = sum(1 for r in retrieve_full if r["is_gold_session"])
    gold_in_top30 = sum(1 for r in retrieve if r["is_gold_session"])
    gold_ranks_top30 = [r["rank"] for r in retrieve
                        if r["is_gold_session"]][:10]

    rec = {
        "qid": args.qid,
        "question": question,
        "gold": gold,
        "qtype": qtype,
        "answer_session_ids": list(gold_sids),
        "question_date": q_date,
        "ingest_stats": ingest_stats,
        "retrieve_window": {
            "top_k_probed": RUNNER_TOP_K,
            "gold_hits_in_top_200": gold_in_top200,
            "gold_hits_in_top_30": gold_in_top30,
            "gold_ranks_first_10": gold_ranks_top30,
        },
        "retrieve_top_30_preview": retrieve,
        "helper_signals": helper_signals,
        "helper_proofs": helper_proofs,
        "self_anchor_probe": self_anchor,
        "store_anchor_probe": store_anchors,
        "structured_skill_section": structured,
        "jab_what_if": _jab_what_if(gold),
        "closure_view": closure_view,
    }

    out = args.out or Path(
        f"bench/end_to_end/diagnose-{args.qid}.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    rec["path_summary"] = _safe(build_path_summary, rec)
    out.write_text(json.dumps(rec, indent=2, ensure_ascii=False))

    _print_path_summary(rec.get("path_summary") or {})
    _print_summary(rec)
    _print_closure_view(rec.get("closure_view") or {})
    print(f"saved → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
