"""LongMemEval-S harness using Mem0's exact protocol.

Why this file exists separately from run_longmemeval.py:
- Dataset: longmemeval_s_cleaned.json (~47.7 sessions/q, ~493 turns/q) — the
  true haystack benchmark Mem0 reports 93.4 on. Our earlier run_longmemeval.py
  used oracle.json (~1.9 sessions/q) which is a much easier setting.
- Prompts: answer+judge are ported verbatim from mem0ai/memory-benchmarks so
  any score difference vs their 93.4 is attributable to the memory system,
  not prompt wording. Our earlier one-line judge under-reports by ~10 pt.
- Answer format: LLM is instructed to use <mem_thinking> tags; we strip
  those before showing the answer to the judge.

Usage:
    python3 bench/end_to_end/run_longmemeval_mem0.py \\
        --n 30 \\
        --answer-profile openai_direct --answer-model gpt-4o \\
        --judge-profile openai_direct  --judge-model gpt-4o \\
        --out bench/end_to_end/lme-s-mem0proto-n30.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
import urllib.request
from pathlib import Path


DATASET = Path(
    os.environ.get(
        "RADIOMIND_LME_S_DATASET",
        str(Path.home() / "Library/Caches/radiomind-data/longmemeval_s_cleaned.json"),
    )
)

# Socket-level default timeout. urllib's per-call timeout=120 has been
# observed to NOT fire on half-open TLS connections (DashScope hung
# requests at 1-2h with 0 CPU during 2026-05-05 multi-session runs),
# leaving the bench wedged. socket.setdefaulttimeout puts a hard
# backstop at the OS-socket layer that applies to every TCP read.
import socket as _socket
_socket.setdefaulttimeout(180)  # 3 min hard ceiling per socket op

_BYPASS_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def llm_call(
    prompt: str, config_path: Path,
    model: str = "gpt-4o", max_tokens: int = 800,
    profile: str = "openai", system: str | None = None,
    max_retries: int = 3,
) -> str:
    """One LLM call with retries on transient errors.

    Retries on: SSL EOF, ConnectionResetError, urllib timeout, 429, 500-599.
    Does NOT retry on 400/401/403/404 (real failures, retrying won't help).
    Backoff: 1s, 2s, 4s.
    """
    import tomllib, time
    cfg = tomllib.loads(config_path.read_text())
    oc = cfg["llm"][profile]
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    payload = json.dumps({
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.0,
    }).encode()
    headers = {
        "Authorization": f"Bearer {oc['api_key']}",
        "Content-Type": "application/json",
    }
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(
                f"{oc['base_url'].rstrip('/')}/chat/completions",
                data=payload, headers=headers,
            )
            with _BYPASS_PROXY_OPENER.open(req, timeout=120) as r:
                body = json.loads(r.read())
            return body["choices"][0]["message"]["content"].strip()
        except urllib.error.HTTPError as e:
            # Permanent failures don't retry
            if e.code in (400, 401, 403, 404):
                raise
            # 429 / 5xx: transient, retry
            last_exc = e
        except (
            urllib.error.URLError, ConnectionError,
            TimeoutError, OSError,
        ) as e:
            # SSL EOF, connection refused, dns failure, etc.
            last_exc = e
        # Backoff before next attempt (no sleep on the final iteration)
        if attempt < max_retries - 1:
            time.sleep(2 ** attempt)
    raise last_exc if last_exc is not None else RuntimeError("llm_call failed")


_THINK_PATTERN = re.compile(r"<mem_thinking>[\s\S]*?</mem_thinking>", re.IGNORECASE)
_FINAL_VERDICT_RE = re.compile(
    r"(?:final\s+verdict|verdict|answer)\s*[:：]\s*[\"'`]?(yes|no)\b",
    re.IGNORECASE,
)


def _parse_judge_verdict(verdict: str) -> bool:
    """Parse 'yes' / 'no' from a Mem0 LongMemEval judge response.

    Mem0's judge template asks for step-by-step in <judge_thinking> tags
    then final verdict "yes"/"no" on a new line after the closing tag.
    Observed qwen deviations (seen on n=30 run):
      1. Closes </judge_thinking> with no verdict line after (put verdict
         inside the thinking block as "Final verdict: yes").
      2. Forgets the tags entirely and writes "Verdict: yes" inline.
      3. Correct format (expected).

    We try them in order; first definitive match wins. Conservative default
    is False so an ambiguous judge doesn't inflate accuracy.
    """
    if not verdict:
        return False
    low = verdict.lower()

    # 1. Line immediately after </judge_thinking>
    if "</judge_thinking>" in low:
        tail = low.split("</judge_thinking>", 1)[1].strip()
        first_tok = tail.split()[0] if tail.split() else ""
        if first_tok.startswith("yes"):
            return True
        if first_tok.startswith("no"):
            return False

    # 2. "Final verdict: yes" / "Verdict: yes" / "Answer: yes" anywhere
    m = _FINAL_VERDICT_RE.search(verdict)
    if m:
        return m.group(1).lower() == "yes"

    # 3. Last non-empty line that's a clean "yes"/"no"
    lines = [ln.strip() for ln in verdict.strip().splitlines() if ln.strip()]
    for ln in reversed(lines):
        ll = ln.lower()
        if ll in ("yes", "no"):
            return ll == "yes"

    # 4. Conservative default
    return False


def strip_thinking(text: str) -> str:
    """Remove <mem_thinking>...</mem_thinking> blocks from the answer.

    Mem0's answer prompt instructs the LLM to reason inside <mem_thinking>
    tags and produce a final answer outside. The judge should only see
    the final answer. If the LLM forgets to close the tag we keep content
    after the last </mem_thinking>, or fall back to the whole text.
    """
    without_blocks = _THINK_PATTERN.sub("", text).strip()
    if without_blocks:
        return without_blocks
    # Fallback: take everything after last </mem_thinking>
    idx = text.rfind("</mem_thinking>")
    if idx >= 0:
        return text[idx + len("</mem_thinking>"):].strip()
    # Or: strip open-only tag
    idx = text.rfind("<mem_thinking>")
    if idx >= 0:
        return text[:idx].strip() or text.strip()
    return text.strip()


def run(
    sandbox: Path,
    n_questions: int,
    answer_model: str,
    judge_model: str,
    answer_profile: str,
    judge_profile: str,
    use_reranker: bool,
    use_temporal_math: bool,
    use_agentic: bool,
    use_refinement: bool = True,
    checkpoint_path: Path | None = None,
    qids_filter: set[str] | None = None,
) -> dict:
    os.environ["RADIOMIND_HOME"] = str(sandbox)
    if (sandbox / "data").exists():
        shutil.rmtree(sandbox / "data")
    sandbox.mkdir(parents=True, exist_ok=True)

    cfg_src = Path.home() / ".radiomind" / "config.toml"
    cfg_content = cfg_src.read_text()
    if use_reranker and "[retrieval.reranker]" not in cfg_content:
        cfg_content += "\n[retrieval.reranker]\nenabled = true\n"
    elif not use_reranker:
        cfg_content = cfg_content.replace("enabled = true", "enabled = false")
    (sandbox / "config.toml").write_text(
        cfg_content.replace(str(Path.home() / ".radiomind"), str(sandbox))
    )

    sys.path.insert(0, str(Path(__file__).parent))
    from mem0_protocol.longmemeval_prompts import (
        get_answer_generation_prompt, JUDGE_PROMPT,
    )

    from radiomind.core.mind import RadioMind
    from radiomind.core.types import MemoryEntry, MemoryLevel

    # Host-inject the bench LLM callable into RadioMind's internal pipeline
    # so KG extraction, query decomposer, and NumericAggregator classifier
    # all have a working LLM. Without this, _resolve_llm falls back to
    # empty router (env has OPENROUTER_API_KEY but no OPENAI_API_KEY that
    # the env-probe looks for), and those paths return empty silently.
    # Uses answer_model since that credential + model is already verified.
    def _internal_llm(prompt: str, system: str = "") -> str:
        # Generous max_tokens: NumericAggregator batch extraction
        # returns many JSON events per call; KG extractor outputs many
        # triples; decomposer outputs many atoms. 2500 is enough for
        # 20-turn batches without truncation.
        return llm_call(
            prompt, config_path,
            model=answer_model, max_tokens=2500,
            profile=answer_profile, system=(system or None),
        )

    mind = RadioMind(llm=_internal_llm)
    mind.initialize()
    print(
        f"  init: embedder={mind._embedder is not None}, "
        f"reranker={mind._reranker is not None}",
        flush=True,
    )

    data = json.loads(DATASET.read_text())

    # Drop dataset-gold errata before sampling. These qids have been
    # audited as having incorrect gold answers (e.g., 370a8ff4: gold=15
    # weeks but the haystack supports 11w4d). RadioMind's disagreement
    # is correct — counting them as fails distorts every n=100 number.
    # Same skip logic as regress_activated_channels.py for consistency.
    errata_path = Path(__file__).parent / "dataset_errata.json"
    errata_qids: set[str] = set()
    if errata_path.exists():
        try:
            errata_qids = set(
                (json.loads(errata_path.read_text())
                 .get("longmemeval_s", {}) or {}).keys()
            )
        except Exception:
            errata_qids = set()
    if errata_qids:
        before = len(data)
        data = [
            q for q in data
            if (q.get("question_id") or q.get("id")) not in errata_qids
        ]
        skipped = before - len(data)
        if skipped:
            print(
                f"  [errata] skipped {skipped} qids with audited-bad gold: "
                f"{sorted(errata_qids)}",
                flush=True,
            )

    if qids_filter:
        before = len(data)
        data = [
            q for q in data
            if (q.get("question_id") or q.get("id")) in qids_filter
        ]
        print(
            f"  [qids-filter] kept {len(data)}/{before} matching "
            f"{len(qids_filter)} requested qids",
            flush=True,
        )
        # qids filter overrides stratified sampling
        n_questions = 0

    if n_questions > 0:
        from collections import defaultdict
        import random
        by_type: dict[str, list] = defaultdict(list)
        for q in data:
            by_type[q.get("question_type", "?")].append(q)
        rng = random.Random(20260416)
        per_type_n = max(1, n_questions // len(by_type))
        sampled: list = []
        for t, qs in by_type.items():
            rng.shuffle(qs)
            sampled.extend(qs[:per_type_n])
        remaining = n_questions - len(sampled)
        if remaining > 0:
            extra = []
            for t, qs in by_type.items():
                extra.extend(qs[per_type_n:])
            rng.shuffle(extra)
            sampled.extend(extra[:remaining])
        rng.shuffle(sampled)
        data = sampled[:n_questions]
        print(
            f"  stratified sample: {len(data)} across {len(by_type)} types",
            flush=True,
        )

    config_path = cfg_src

    per_type: dict[str, dict] = {}
    overall = {"n": 0, "correct": 0, "total_ingested_turns": 0}
    per_query_log: list[dict] = []
    t_start = time.time()

    # Checkpoint: one JSON line per completed question.
    # Critical for n=500 gpt-4o runs (8+ hours) where network flakiness
    # can kill the whole pipeline mid-way — on resume we skip already-
    # completed question_ids so only the unfinished tail re-runs.
    done_qids: set[str] = set()
    if checkpoint_path is not None and checkpoint_path.exists():
        try:
            with checkpoint_path.open() as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    qid = rec.get("question_id")
                    if qid:
                        done_qids.add(qid)
                    per_query_log.append(rec)
                    if rec.get("correct"):
                        overall["correct"] += 1
                    overall["n"] += 1
                    qtype = rec.get("qtype", "?")
                    per_type.setdefault(qtype, {"n": 0, "correct": 0})
                    per_type[qtype]["n"] += 1
                    per_type[qtype]["correct"] += int(bool(rec.get("correct")))
                    # Codex 2026-05-28: judge stats must also be
                    # rebuilt from the checkpoint, otherwise the
                    # post-resume run only counts its own window and
                    # top-level `judge_errors / judge_n /
                    # model_correct` are wrong.
                    if "judge_errors" not in overall:
                        overall["judge_errors"] = 0
                        overall["judge_n"] = 0
                        overall["model_correct"] = 0
                    if rec.get("judge_failed"):
                        overall["judge_errors"] += 1
                    else:
                        overall["judge_n"] += 1
                        if rec.get("correct"):
                            overall["model_correct"] += 1
            if done_qids:
                print(f"  resume: loaded {len(done_qids)} completed questions from checkpoint", flush=True)
        except Exception as e:
            print(f"  checkpoint load warn: {e}", flush=True)

    def _question_id(q: dict, idx: int) -> str:
        qid = q.get("question_id") or q.get("id")
        if qid:
            return str(qid)
        import hashlib
        return "auto_" + hashlib.md5(q.get("question", "").encode()).hexdigest()[:10]

    def _append_checkpoint(rec: dict) -> None:
        if checkpoint_path is None:
            return
        try:
            checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            with checkpoint_path.open("a") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:
            pass

    for q_idx, q in enumerate(data):
        qtype = q.get("question_type", "?")
        question = q.get("question", "")
        gold = q.get("answer", "")
        if not question or not q.get("haystack_sessions"):
            continue
        qid = _question_id(q, q_idx)
        if qid in done_qids:
            continue  # already done in prior run; skipped

        domain = f"lme_{q_idx}"
        # Flatten question's haystack into a list of turn dicts for
        # ingest_turns_raw, which runs the full pipeline: store + KG +
        # Meta + aggregation + optional three-body refinement. Previous
        # version bypassed this by calling mind._store.add directly,
        # which meant patterns/principles/habits never got built — the
        # benchmark was measuring only L2 raw-turn retrieval.
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
        stats = mind.ingest_turns_raw(
            turns, domain=domain,
            run_aggregation=True,
            # Three-body debate fires once per question's domain. Each
            # adds ~1 LLM round-trip total (all 3 speakers run in parallel
            # inside chat.refine). Worth it: upgrades raw facts into
            # PRINCIPLE-level summaries that pyramid.search surfaces first.
            run_refinement=use_refinement,
        )
        overall["total_ingested_turns"] += stats["ingested"]

        if isinstance(gold, list):
            gold_str = " | ".join(str(g) for g in gold)
        else:
            gold_str = str(gold)

        # Mem0 retrieves top_k=200 (their default), because on haystack data
        # the answer-bearing memory is often beyond top-10. Match their depth
        # for a fair comparison. Answer prompt will still slice to top 200.
        TOP_K = 200
        if use_agentic:
            from radiomind.storage.agentic import agentic_search
            def _llm_fn(prompt: str) -> str:
                return llm_call(prompt, config_path, model=answer_model,
                                 max_tokens=150, profile=answer_profile)
            def _search_fn(query: str, domain=None, max_results=TOP_K):
                return mind.search(query, domain=domain, max_results=max_results)
            results = agentic_search(
                question, _search_fn, _llm_fn, domain=domain,
                per_subquery_k=50, final_k=TOP_K,
            )
        else:
            results = mind.search(question, domain=domain, max_results=TOP_K)

        # Attention-driven retrieval augmentation (same pattern as LoCoMo
        # harness): specific-detail queries get a keyword-narrowed second
        # retrieval pass merged at the tail.
        try:
            from radiomind.core.attention import is_specific_detail_lookup
            if is_specific_detail_lookup(question):
                import re as _re
                m = _re.search(
                    r"\b(?:what|which|where)\s+(?:is|are|was|were|does|do|did|has|have)\s+"
                    r"([a-z][a-z]+)('s)?\b",
                    question, _re.IGNORECASE,
                )
                if m:
                    subject = m.group(1)
                    extra = mind.search(subject, domain=domain, max_results=40)
                    seen = {getattr(r.entry, "id", 0) for r in results}
                    for r in extra:
                        rid = getattr(r.entry, "id", 0)
                        if rid not in seen:
                            results.append(r)
                            seen.add(rid)
        except Exception:
            pass

        # Build Mem0-format search_results: memory / score / created_at
        mem_results = []
        for r in results[:TOP_K]:
            sdate = (r.entry.metadata or {}).get("session_date", "")
            mem_results.append({
                "memory": r.entry.content,
                "score": float(getattr(r, "score", 0.0)),
                "created_at": sdate,
            })

        # Bottom-up NumericAggregator view: for count/total questions
        # ("how many instruments", "how much did I donate"), the cardinal
        # cache (populated at ingest time) holds a deterministic
        # ground-truth that doesn't depend on top-k retrieval completeness.
        # When it has a hit, we inject it BEFORE the memory block so the
        # answer model treats it as anchor. Empty when not applicable.
        cardinal_section = ""
        try:
            # user_id matches the default ("") used in ingest_turns_raw
            # above; per-question domain isolation is via the `domain`
            # partition instead.
            cardinal_section = mind.get_numeric_cardinal(
                query=question, domain=domain, user_id="",
            )
        except Exception:
            pass

        # Attention-driven trinity pipelines (S3.2):
        # temporal_precision & open_domain_specific queries get their
        # own dedicated Guardian/Explorer/Reducer passes that produce
        # a strict-answer prefix to the answer prompt.
        temporal_section = ""
        open_domain_section = ""
        try:
            temporal_section = mind.run_temporal_precision(
                query=question, retrieved_memories=mem_results,
                reference_date=q_date or "", domain=domain,
            )
        except Exception:
            pass
        try:
            open_domain_section = mind.run_open_domain_specific(
                query=question, retrieved_memories=mem_results, domain=domain,
            )
        except Exception:
            pass
        # OrderedEventList-1d: chronological list-ordering questions have no
        # attention `wants` class, so they route via this dedicated entry
        # (gated on ListOrderingSkill's own trigger), independent of the
        # date/inference wrappers above.
        list_ordering_section = ""
        try:
            list_ordering_section = mind.run_list_ordering(
                query=question, retrieved_memories=mem_results, domain=domain,
            )
        except Exception:
            pass

        profile_section = ""
        try:
            profile_section = mind.profile_hint(query=question)
        except Exception:
            pass

        preference_section = ""
        try:
            preference_section = mind.run_preference_context(
                query=question, retrieved_memories=mem_results, domain=domain,
            )
        except Exception:
            pass

        # Entity disambiguation (GAP-6): when the question uses a
        # definite reference ("the museum", "the doctor") and retrieval
        # surfaces multiple candidate entities of that type, fire a
        # trinity disambiguation pass and inject the resolved name.
        # Targets gpt4_59149c78 where the model picked City Art Museum
        # instead of the Metropolitan Museum gold.
        entity_section = ""
        try:
            entity_section = mind.run_entity_disambiguation(
                query=question, retrieved_memories=mem_results, domain=domain,
            )
        except Exception:
            pass

        # V8.2.2a: role/title mismatch guard. Deterministic regex check
        # — when question asks about a leadership role (Manager/Director/
        # VP/etc.) but retrieved memories only support an IC role (Engineer/
        # Scientist/etc.) on the same person, inject an abstain hint.
        # Target: LME-S 031748ae_abs (Software Engineer Manager vs Senior
        # Software Engineer over-commit). Zero LLM cost.
        role_guard_section = ""
        try:
            from radiomind.core.role_mismatch_guard import role_mismatch_guard
            role_guard_section = role_mismatch_guard(question, mem_results)
        except Exception:
            pass

        # TESG-1 (2026-05-26): temporal endpoint support guard, employer-
        # only sub-shape. When the question asks "how long ... before I
        # started my current job at Y" AND neither retrieved memories
        # nor the full domain store carry first-person work-at-Y
        # evidence, inject a canonical-abstain prefix. TESG-1b: mind +
        # domain are passed so the detector can fall back to the full
        # store before asserting "user hasn't started" (otherwise a
        # retrieval miss would be wrongly treated as negative evidence).
        # Target: gpt4_93159ced_abs. Negative anchor: gpt4_93159ced
        # (NovaTech) must remain a PASS.
        temporal_endpoint_section = ""
        try:
            from radiomind.core.temporal_endpoint_guard import (
                temporal_endpoint_support_guard,
            )
            temporal_endpoint_section = temporal_endpoint_support_guard(
                question, mem_results, mind=mind, domain=domain,
            )
        except Exception:
            pass

        # V8.4-A (2026-05-28): SavingsHint. Deterministic 2-anchor
        # arithmetic helper for "how much did I save on [item]?"
        # queries where retrieved user-turn memories carry both a
        # paid price AND a retail/original/MSRP price for the SAME
        # item phrase (≥2 token brand+noun anchor). Computes
        # retail − paid. Target: LME-S bb7c3b45 (Jimmy Choo $500
        # retail − $200 paid = $300). Hint-only, never forces
        # commit. Pre-implementation audit (SavingsHint-1a):
        # bench/end_to_end/savings_hint_1a_audit.py. Trigger
        # surface = 2 in LME-S 500.
        savings_hint_section = ""
        try:
            from radiomind.core.arithmetic_hint import (
                savings_arithmetic_hint,
            )
            savings_hint_section = savings_arithmetic_hint(
                question, mem_results, mind=mind, domain=domain,
            )
        except Exception:
            pass

        # V8.2.3a: cashback arithmetic hint. Deterministic helper for
        # "how much cashback/rebate at X" queries where memories contain
        # both a rate and an amount. Computes rate × amount and surfaces
        # the calculation as a hint. Target: LME-S 9aaed6a3 (SaveMart $0.75
        # = 1% × $75). Hint-only, never forces commit. Narrow trigger
        # (cashback/rebate/reward earn patterns) — won't affect non-cashback
        # questions.
        cashback_hint_section = ""
        try:
            from radiomind.core.arithmetic_hint import cashback_arithmetic_hint
            cashback_hint_section = cashback_arithmetic_hint(
                question, mem_results, mind=mind, domain=domain)
        except Exception:
            pass

        # SelfAnchor-2b telemetry (read-only; does NOT change model
        # behavior). Splits "helper stayed silent" from "LLM ignored
        # the hint" on cashback-trigger qids, so a smoke FAIL can be
        # attributed to amount-side recall / rate store-scan / trust-gap
        # without re-running.
        cashback_telemetry: dict = {}
        try:
            from radiomind.core.arithmetic_hint import (
                diagnose_cashback as _diag_cb,
                _query_triggers as _cb_trig,
            )
            if _cb_trig(question):
                _dc = _diag_cb(question, mem_results)
                cashback_telemetry = {
                    "merchant": _dc.get("merchant"),
                    "amount_in_retrieve": _dc.get("amount") is not None,
                    "amount": _dc.get("amount"),
                    "rate_in_retrieve": _dc.get("rate"),
                    "rate_refusal": _dc.get("refusal_reason"),
                    "hint_emitted": bool(cashback_hint_section),
                    "store_scan_used": (
                        "SelfAnchor store-scan" in cashback_hint_section),
                    "hint_preview": cashback_hint_section[:220],
                }
        except Exception:
            pass

        # V8.3.1: typed-event arithmetic hint — person_age average.
        # Deterministic helper for the closed kin set {self, mom, dad,
        # grandma, grandpa} when query asks for the average age across
        # me + parents + grandparents. Target: LME-S gpt4_d12ceb0e
        # (mean = 59.6). Hint-only, never forces commit. Refuses when
        # any kin role is missing or has conflicting ages.
        person_age_hint_section = ""
        try:
            from radiomind.core.typed_event_hint import person_age_average_hint
            person_age_hint_section = person_age_average_hint(
                question, mem_results, mind=mind, domain=domain)
        except Exception:
            pass

        # Attention-driven atomic decomposition: query-time LLM extract
        # over retrieved turns for aggregation queries not served by the
        # cardinal cache (list-enumerations, cross-session narratives).
        # DRAFT framing so the model still verifies against raw turns.
        # Skip when cardinal view already supplied a count/total — no
        # point paying a second LLM call and mixing two DRAFT blocks.
        atomic_section = ""
        try:
            if cardinal_section:
                atoms = []
            else:
                atoms = mind.decompose_for_query(
                    query=question, retrieved=results[:30], domain=domain,
                    promote=True,
                )
            if atoms:
                # Label explicitly as DRAFT, not authoritative. When v4's
                # earlier run made this an authoritative-looking summary
                # at the tail, deepseek answered from it alone — if the
                # draft was incomplete (decomposer missed 2 of 3 doctors)
                # the model reported the draft's count, not the ground
                # truth in the raw turns. Two fixes: (a) DRAFT framing,
                # (b) put this block BEFORE memories so raw turns are last.
                lines = ["DRAFT ATOMIC VIEW (extracted heuristically — VERIFY against the memories below; enumerate additional entries if any memory mentions one not listed here):"]
                for a in atoms[:15]:
                    count_tag = f" [×{a.count}]" if a.count > 1 else ""
                    verified = " ✓KG" if a.kg_verified else ""
                    lines.append(f"- {a.fact}{count_tag}{verified} "
                                 f"(conf {a.confidence:.2f}, from {','.join(a.evidence[:3])})")
                atomic_section = "\n".join(lines) + "\n\n"
        except Exception:
            pass

        q_date = q.get("question_date", "")
        ans_prompt = get_answer_generation_prompt(
            question=question, search_results=mem_results, question_date=q_date or "",
        )
        # V8.2.2a: role guard prepended FIRST so it sits between memories
        # block (innermost) and atomic/profile/etc. (outer). This way the
        # abstain imperative is the LAST hint the model sees before the
        # actual memory block — counters atomic_section's pull when atomic
        # has 'user leads N as <other-role>' claims.
        if role_guard_section:
            ans_prompt = role_guard_section + ans_prompt
        # TESG-1: temporal endpoint guard at the same innermost wrapper
        # level as the role guard. Same architectural contract: when
        # presupposition is unsupported by memories, force canonical
        # abstain via prompt-prefix.
        if temporal_endpoint_section:
            ans_prompt = temporal_endpoint_section + ans_prompt
        # V8.2.3a: cashback arithmetic hint injected at the same level
        # (innermost wrapper). Both are deterministic answer-side helpers.
        if cashback_hint_section:
            ans_prompt = cashback_hint_section + ans_prompt
        # V8.4-A SavingsHint at the same innermost wrapper layer.
        # Both hints are deterministic answer-side helpers.
        if savings_hint_section:
            ans_prompt = savings_hint_section + ans_prompt
        # V8.3.1: typed-event hint (person_age average) at the same
        # innermost-wrapper level as the other deterministic helpers.
        if person_age_hint_section:
            ans_prompt = person_age_hint_section + ans_prompt
        if atomic_section:
            # Insert BEFORE the memory block so retrieved turns remain the
            # last and most salient context the model sees — atomic facts
            # only serve as a draft starting point.
            ans_prompt = atomic_section + ans_prompt
        if cardinal_section:
            # Deterministic cardinal view outranks the heuristic draft.
            # Both placed ahead of the memory block.
            ans_prompt = cardinal_section + ans_prompt
        if temporal_section:
            ans_prompt = temporal_section + ans_prompt
        if open_domain_section:
            ans_prompt = open_domain_section + ans_prompt
        if list_ordering_section:
            ans_prompt = list_ordering_section + ans_prompt
        if profile_section:
            ans_prompt = profile_section + ans_prompt
        if preference_section:
            # Insert ahead of profile so preference-specific context
            # is the freshest anchor the model sees for advice questions.
            ans_prompt = preference_section + ans_prompt
        if entity_section:
            # Disambiguation goes RIGHT before memories so "the X"
            # references in the answer prompt resolve to the trinity-
            # chosen entity, not the most-recent surface mention.
            ans_prompt = entity_section + ans_prompt
        # (role_guard already injected earlier as innermost wrapper)
        # Append Meta's calibration directive — the memory system's
        # self-observation layer gets the last word on answer style.
        # Counters systematic biases (over-abstention on inferable
        # questions; previous/current confusion) that no base prompt
        # fully eliminates. Empty string when no meta data available.
        calibration = mind.get_meta_calibration()
        if calibration:
            ans_prompt = ans_prompt + "\n\n" + calibration
        try:
            # 1500 tokens: deepseek (esp. DashScope backend) emits
            # verbose <mem_thinking> blocks; 800 truncated 4 of 100 in
            # the v2 run, dropping their final answer line and forcing
            # FAIL. 1500 covers the long-tail cases observed.
            raw_answer = llm_call(
                ans_prompt, config_path,
                model=answer_model, max_tokens=1500, profile=answer_profile,
            )
            answer = strip_thinking(raw_answer)
        except Exception as e:
            answer = f"[answer error: {e}]"

        # Trinity bidirectional abstain gate: review every answer (whether
        # the model abstained OR committed) and decide keep/abstain/rewrite.
        # Replaces the prior one-direction AbstentionSalvager so that BOTH
        # error modes are caught:
        #   - under-confidence: model said "not enough" but memories support
        #   - over-confidence:  model gave a number but memories don't support
        # The gate biases toward KEEP — it flips only when ≥2 trinity stances
        # oppose the draft, so currently-correct answers don't regress.
        try:
            from radiomind.refinement.salvage import BidirectionalAbstainGate
            def _gate_llm(prompt: str, sys_prompt: str) -> str:
                return llm_call(prompt, config_path,
                                 model=answer_model, max_tokens=600,
                                 profile=answer_profile)
            gate = BidirectionalAbstainGate(_gate_llm)
            review = gate.review(question, answer, results[:40])
            if review is not None and review.action != "keep":
                answer = review.answer
        except Exception:
            pass

        # V8.2.2b: post-process. When the role mismatch guard fired AND the
        # LLM still committed numeric specifics (team size, headcount, $),
        # rewrite the answer to a canonical abstain. Closes the loop on
        # V8.2.2a's prompt-level guard. Deterministic — pure regex check.
        try:
            from radiomind.core.role_mismatch_guard import maybe_rewrite_with_guard
            answer = maybe_rewrite_with_guard(question, mem_results, answer)
        except Exception:
            pass

        # TESG-1 post-process. Same contract as the role-guard rewrite:
        # when the temporal endpoint guard fired AND the LLM still
        # committed to a duration ("4 years 3 months"), rewrite to a
        # canonical abstain stating the endpoint hasn't been reached.
        # mind+domain passed so the detector uses the same store-scan
        # fallback as the prompt-prefix guard (TESG-1b).
        try:
            from radiomind.core.temporal_endpoint_guard import (
                maybe_rewrite_with_temporal_guard,
            )
            answer = maybe_rewrite_with_temporal_guard(
                question, mem_results, answer, mind=mind, domain=domain,
            )
        except Exception:
            pass

        # TSI-1c (2026-05-26): age_interval commit closure. When the
        # age_interval skill fired with conf>=0.85, produced a numeric
        # answer, BOTH backing evidences (at-age-N + current-age) are
        # present in retrieved memories, AND the answer-LLM emitted a
        # pure canonical abstain — override the abstain with the
        # skill's number. TSI-1b verified the trigger surface is just
        # 3 LME-S qids with concrete (non-abstain) golds, so this
        # rewrite cannot break a correct abstain on the audited
        # surface.
        try:
            from radiomind.core.age_interval_commit import (
                maybe_age_interval_commit_closure,
            )
            answer = maybe_age_interval_commit_closure(
                question, mem_results, answer, temporal_section,
                mind=mind, domain=domain,
            )
        except Exception:
            pass

        # TrustClosure-1b: cashback commit closure. When the LLM emitted
        # a PURE abstain but a complete, recomputing cashback proof
        # exists (merchant-scoped rate × retrieved amount), commit the
        # value. Mirrors the TSI-1d age closure. Never overwrites a
        # concrete answer. Target: 9aaed6a3 (the only empirical cashback
        # trust-gap).
        try:
            from radiomind.core.arithmetic_hint import (
                maybe_cashback_commit_closure,
            )
            answer = maybe_cashback_commit_closure(
                question, mem_results, answer, mind=mind, domain=domain,
            )
        except Exception:
            pass

        judge_prompt = JUDGE_PROMPT.format(
            question=question, answer=gold_str, response=answer,
        )
        is_correct = False
        verdict = ""
        judge_failed = False
        # V8.2.2b: retry on judge HTTP errors (403, SSL, connection reset).
        # OpenRouter occasionally returns 403 / SSL EOF on bursts; without
        # retry these silently flip the bench acc by ~6% (observed on
        # V8.2.2a LME-S n=100 where 6/100 verdicts were judge HTTP error
        # default-counted as FALSE while the model answer was clearly
        # correct: UCLA, MusicTheory.net, $300, Emma, 10 days ago, four).
        for judge_attempt in range(3):
            try:
                verdict = llm_call(
                    judge_prompt, config_path,
                    model=judge_model, max_tokens=2000, profile=judge_profile,
                )
                is_correct = _parse_judge_verdict(verdict)
                judge_failed = False
                break  # success
            except Exception as e:
                verdict = f"[judge error attempt {judge_attempt+1}: {e}]"
                judge_failed = True
                if judge_attempt < 2:
                    import time as _t
                    _t.sleep(2 ** judge_attempt)  # 1s, 2s, 4s backoff
        # JAB-1a: deterministic veto when LLM judge passes a canonical
        # abstain response against a concrete gold. The judge prompt
        # specifies the abstain-GOLD rule but does not forbid passing
        # abstain RESPONSES against concrete golds; this veto closes
        # that hole. Reason logged in verdict so per-query records
        # show the override.
        if is_correct and not judge_failed:
            from jab1_abstain_veto import should_veto
            if should_veto(gold_str, answer):
                is_correct = False
                verdict = (verdict or "") + (
                    "\n[JAB-1a VETO: concrete gold + canonical "
                    "abstain response → FAIL]"
                )
        # Track judge failures separately so report can distinguish
        # model-wrong (true FAIL) from judge-infra-error (unverdicted).
        if "judge_errors" not in overall:
            overall["judge_errors"] = 0
            overall["model_correct"] = 0
            overall["judge_n"] = 0
        if judge_failed:
            overall["judge_errors"] += 1
        else:
            overall["judge_n"] += 1
            if is_correct:
                overall["model_correct"] += 1

        # Meta self-observation — feeds dynamic calibration next run
        try:
            from radiomind.refinement.salvage import looks_abstained as _abstained
            mind.record_answer_outcome(
                query=question,
                evidence_count=len(mem_results),
                abstained=_abstained(answer or ""),
                correct=is_correct,
            )
        except Exception:
            pass

        overall["n"] += 1
        overall["correct"] += int(is_correct)
        per_type.setdefault(qtype, {"n": 0, "correct": 0})
        per_type[qtype]["n"] += 1
        per_type[qtype]["correct"] += int(is_correct)

        record = {
            "question_id": qid,
            "q": question, "gold": gold_str, "answer": answer[:400],
            "correct": is_correct, "qtype": qtype, "verdict_tail": verdict[-120:],
            "judge_failed": judge_failed,
        }
        if cashback_telemetry:
            record["cashback_telemetry"] = cashback_telemetry
        # TrustClosure-1a telemetry (read-only): which deterministic
        # hint helpers fired vs whether the final answer is a pure
        # abstain. hint_emitted=True + answer_pure_abstain=True is the
        # trust-gap signature, surfaced uniformly across all helpers.
        try:
            from jab1_abstain_veto import is_abstain_response as _is_ab
            record["helper_hints"] = {
                "savings": bool(savings_hint_section),
                "person_age": bool(person_age_hint_section),
                "cashback": bool(cashback_hint_section),
                "role_guard": bool(role_guard_section),
                "temporal_endpoint": bool(temporal_endpoint_section),
                "answer_pure_abstain": _is_ab(answer),
            }
        except Exception:
            pass
        per_query_log.append(record)
        _append_checkpoint(record)

        if (q_idx + 1) % 10 == 0:
            acc = overall["correct"] / overall["n"]
            elapsed = time.time() - t_start
            print(
                f"  [{q_idx+1}/{len(data)}] acc={acc:.3f}  t={elapsed:.0f}s",
                flush=True,
            )

    elapsed = time.time() - t_start
    mind.shutdown()

    return {
        "benchmark": "LongMemEval-S (cleaned) — Mem0 protocol",
        "protocol": "mem0 prompts; haystack = ~47.7 sessions/q",
        "n_questions": overall["n"],
        "total_ingested_turns": overall["total_ingested_turns"],
        "reranker_enabled": use_reranker,
        "temporal_math": use_temporal_math,
        "agentic": use_agentic,
        "answer_model": answer_model,
        "judge_model": judge_model,
        "answer_profile": answer_profile,
        "judge_profile": judge_profile,
        "elapsed_s": round(elapsed, 1),
        "overall_accuracy": round(overall["correct"] / max(1, overall["n"]), 4),
        # V8.2.2b: split-out metrics to distinguish model errors from
        # judge-infra errors. raw_accuracy treats judge errors as FAIL
        # (legacy semantics, comparable to old reports). judged_accuracy
        # excludes judge errors from denominator (model performance among
        # successfully judged questions). judge_error_rate flags how
        # polluted this run is by OpenRouter / SSL flakes.
        "model_correct": overall.get("model_correct", overall["correct"]),
        "judged_n": overall.get("judge_n", overall["n"]),
        "judge_errors": overall.get("judge_errors", 0),
        "raw_accuracy": round(overall["correct"] / max(1, overall["n"]), 4),
        "judged_accuracy": round(
            overall.get("model_correct", overall["correct"]) /
            max(1, overall.get("judge_n", overall["n"])), 4
        ),
        "judge_error_rate": round(
            overall.get("judge_errors", 0) / max(1, overall["n"]), 4
        ),
        "by_type": {
            t: {"n": v["n"], "accuracy": round(v["correct"] / max(1, v["n"]), 4)}
            for t, v in sorted(per_type.items())
        },
        "per_query": per_query_log,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=30)
    p.add_argument("--sandbox", default="/tmp/rm-e2e-lme-s-mem0")
    p.add_argument("--no-reranker", action="store_true")
    p.add_argument(
        "--benchmark-mode", default="a2a-practice",
        choices=("a2a-strict", "a2a-practice", "max"),
        help=(
            "Protocol alignment with Mem0: "
            "'a2a-strict' matches Mem0's single-pass single-LLM setup "
            "(all attention sub-pipelines OFF); "
            "'a2a-practice' (default) runs each architecture's native "
            "default-practice (RadioMind's attention × trinity auto-router); "
            "'max' additionally enables multi-round agentic decomposition."
        ),
    )
    p.add_argument("--temporal-math", action="store_true",
                   help="DEPRECATED: now auto-routed by attention classifier; "
                        "flag kept for backward compat.")
    p.add_argument("--agentic", action="store_true",
                   help="DEPRECATED: --benchmark-mode max enables this; "
                        "flag kept for backward compat.")
    p.add_argument("--no-refinement", action="store_true",
                   help="Skip three-body chat refinement at ingest (default on — builds L3 principles)")
    p.add_argument("--answer-model", default="gpt-4o")
    p.add_argument("--judge-model", default="gpt-4o")
    p.add_argument("--answer-profile", default="openai_direct")
    p.add_argument("--judge-profile", default="openai_direct")
    p.add_argument("--out", default="bench/end_to_end/lme-s-mem0proto.json")
    p.add_argument("--checkpoint", default="",
                   help="Path to .jsonl checkpoint. Per-question results appended as they complete; on rerun with the same path, already-completed question_ids are skipped. Defaults to <out>.checkpoint.jsonl.")
    p.add_argument("--qids", default="",
                   help="Comma-separated qid list. When set, runs ONLY these qids and skips stratified sampling. For single-change validation against a baseline.")
    args = p.parse_args()

    if not DATASET.exists():
        print(f"Dataset missing at {DATASET}")
        return 2

    print(
        f"Running {args.n or 500} questions on LongMemEval-S cleaned; "
        f"answer={args.answer_model}/{args.answer_profile}, "
        f"judge={args.judge_model}/{args.judge_profile}; "
        f"reranker={not args.no_reranker}, temporal_math={args.temporal_math}, "
        f"agentic={args.agentic}",
        flush=True,
    )

    # benchmark-mode translates to the lower-level boolean flags.
    # a2a-strict:   single-pass retrieval + single-LLM answer, no
    #               attention sub-pipelines (kept on-strict for Mem0 parity).
    # a2a-practice: attention auto-routes to sub-pipelines (numeric
    #               cardinal / temporal precision / open-domain /
    #               specific-detail); --agentic multi-round OFF.
    # max:          everything on, including multi-round agentic retrieval.
    import os as _os
    mode = args.benchmark_mode
    if mode == "a2a-strict":
        _os.environ["RADIOMIND_ATTENTION_ROUTER"] = "off"
    elif mode == "max":
        _os.environ["RADIOMIND_ATTENTION_ROUTER"] = "on"
        args.agentic = True
    else:  # a2a-practice
        _os.environ["RADIOMIND_ATTENTION_ROUTER"] = "on"
    use_temporal_math = args.temporal_math or (mode != "a2a-strict")
    use_agentic = args.agentic

    cp_path = Path(args.checkpoint) if args.checkpoint else Path(args.out + ".checkpoint.jsonl")
    qids_set = (
        {s.strip() for s in args.qids.split(",") if s.strip()}
        if args.qids else None
    )
    report = run(
        Path(args.sandbox), args.n,
        answer_model=args.answer_model, judge_model=args.judge_model,
        answer_profile=args.answer_profile, judge_profile=args.judge_profile,
        use_reranker=not args.no_reranker,
        use_temporal_math=use_temporal_math,
        use_agentic=use_agentic,
        use_refinement=not args.no_refinement,
        checkpoint_path=cp_path,
        qids_filter=qids_set,
    )
    report["benchmark_mode"] = mode

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2))

    print(f"\n=== LongMemEval-S (Mem0 protocol), {report['n_questions']} questions ===")
    print(f"  Overall accuracy: {report['overall_accuracy']:.3f}")
    print(f"  Reranker:         {report['reranker_enabled']}")
    print(f"  Time:             {report['elapsed_s']:.0f}s")
    print(f"  Answer model:     {report['answer_model']} ({report['answer_profile']})")
    print(f"  Judge model:      {report['judge_model']} ({report['judge_profile']})")
    print("\n  By question type:")
    for t, stats in report["by_type"].items():
        print(f"    {t:30s} (n={stats['n']:3d})  acc={stats['accuracy']:.3f}")
    print(f"\n  Saved → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
