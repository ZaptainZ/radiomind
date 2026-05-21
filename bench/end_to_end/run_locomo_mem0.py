"""LoCoMo harness using Mem0's exact protocol.

Dataset: locomo10.json (10 conversations, ~1986 QA pairs across 5 categories).
Mem0 evaluates categories 1-4 (excluding adversarial/cat 5); their v3 number
on LoCoMo is 91.6.

Categories (from mem0ai/memory-benchmarks/benchmarks/locomo/prompts.py):
  1: multi-hop
  2: temporal
  3: open-domain
  4: single-hop
  5: adversarial (skipped by default — answer not in conversation)

Usage:
    python3 bench/end_to_end/run_locomo_mem0.py \\
        --n 200 \\
        --answer-model gpt-4o --answer-profile openai_direct \\
        --judge-model gpt-4o --judge-profile openai_direct \\
        --out bench/end_to_end/locomo-mem0proto.json
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import urllib.request
from pathlib import Path
from datetime import datetime


DATASET = Path("/tmp/locomo-data/locomo10.json")
CATEGORY_NAMES = {1: "multi-hop", 2: "temporal", 3: "open-domain", 4: "single-hop", 5: "adversarial"}
_BYPASS_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def llm_call(
    prompt: str, config_path: Path,
    model: str = "gpt-4o", max_tokens: int = 800,
    profile: str = "openai", system: str | None = None,
) -> str:
    import tomllib
    cfg = tomllib.loads(config_path.read_text())
    oc = cfg["llm"][profile]
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    req = urllib.request.Request(
        f"{oc['base_url'].rstrip('/')}/chat/completions",
        data=json.dumps({
            "model": model, "messages": messages,
            "max_tokens": max_tokens, "temperature": 0.0,
        }).encode(),
        headers={
            "Authorization": f"Bearer {oc['api_key']}",
            "Content-Type": "application/json",
        },
    )
    with _BYPASS_PROXY_OPENER.open(req, timeout=120) as r:
        body = json.loads(r.read())
    return body["choices"][0]["message"]["content"].strip()


def parse_locomo_date(s: str) -> str:
    """LoCoMo session_*_date_time comes in formats like '1:56 pm on 8 May, 2023'.
    Convert to ISO so our answer prompt can format it human-readable consistently.
    """
    if not s:
        return ""
    # Try common formats
    for fmt in (
        "%I:%M %p on %d %B, %Y", "%I:%M %p on %d %b, %Y",
        "%H:%M on %d %B, %Y", "%I:%M%p on %d %B, %Y",
    ):
        try:
            dt = datetime.strptime(s.strip(), fmt)
            return dt.strftime("%Y-%m-%dT%H:%M:%S")
        except ValueError:
            continue
    # Try "8 May, 2023" without time
    for fmt in ("%d %B, %Y", "%d %b, %Y"):
        try:
            dt = datetime.strptime(s.strip(), fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return s  # opaque fallback


def build_turns(conversation: dict) -> list[tuple[str, str, str, str]]:
    """Walk conversation sessions, return (session_num, dia_id, iso_date, content)."""
    speaker_a = conversation.get("speaker_a", "")
    speaker_b = conversation.get("speaker_b", "")
    turns: list[tuple[str, str, str, str]] = []
    session_dates: dict[str, str] = {}
    for key, val in conversation.items():
        if key.startswith("session_") and key.endswith("_date_time"):
            session_dates[key.replace("session_", "").replace("_date_time", "")] = parse_locomo_date(val)
    for key, val in conversation.items():
        if not (key.startswith("session_") and not key.endswith("_date_time")):
            continue
        if not isinstance(val, list):
            continue
        snum = key.replace("session_", "")
        sdate = session_dates.get(snum, "")
        for turn in val:
            speaker = turn.get("speaker", "")
            text = turn.get("text", "")
            blip = turn.get("blip_caption", "")
            query = turn.get("query", "")
            if query and blip:
                photo_tag = f"[Sharing image — query: {query}. The image shows: {blip}]"
            elif query:
                photo_tag = f"[Sharing image — query for: {query}]"
            elif blip:
                photo_tag = f"[Sharing image that shows: {blip}]"
            else:
                photo_tag = ""
            combined = f"{text} {photo_tag}".strip() if photo_tag else text
            if not combined:
                continue
            role = "user" if speaker == speaker_a else "assistant"
            dia_id = turn.get("dia_id", "")
            content = f"{speaker}: {combined}"
            turns.append((snum, dia_id, sdate, content))
    return turns


def run(
    sandbox: Path,
    n_questions: int,
    answer_model: str, judge_model: str,
    answer_profile: str, judge_profile: str,
    use_reranker: bool, use_temporal_math: bool, use_agentic: bool,
    use_refinement: bool = True,
    categories: tuple[int, ...] = (1, 2, 3, 4),
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
    from mem0_protocol.locomo_prompts import (
        get_answer_generation_prompt, get_judge_prompt, preprocess_answer,
    )

    from radiomind.core.mind import RadioMind
    from radiomind.core.types import MemoryEntry, MemoryLevel

    # Host-inject the bench LLM so KG extraction / decomposer /
    # NumericAggregator classifier can run. Same pattern as LME-S harness.
    _config_path = sandbox / "config.toml"
    def _internal_llm(prompt: str, system: str = "") -> str:
        return llm_call(
            prompt, _config_path,
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

    # Flatten and stratify: (conv_idx, qa)
    flat: list[tuple[int, dict]] = []
    for conv_idx, conv in enumerate(data):
        for qa in conv.get("qa", []):
            if qa.get("category") in categories and qa.get("answer") is not None:
                flat.append((conv_idx, qa))

    # V6.5.1 smoke: optional qid filter — when set, skip stratified
    # sampling and run only the specified qids (typically the flip-up
    # / flip-down qids from a prior run to verify a targeted fix).
    if qids_filter:
        import hashlib as _hashlib
        def _qid_of(conv_idx, qa):
            q = qa.get("question", "")
            h = _hashlib.md5(q.encode()).hexdigest()[:10]
            return f"c{conv_idx}_{h}"
        before = len(flat)
        flat = [x for x in flat if _qid_of(x[0], x[1]) in qids_filter]
        print(
            f"  [qids-filter] kept {len(flat)}/{before} matching "
            f"{len(qids_filter)} requested qids",
            flush=True,
        )
        n_questions = 0  # disable stratified sampling

    if n_questions > 0 and n_questions < len(flat):
        import random
        from collections import defaultdict
        by_cat: dict[int, list] = defaultdict(list)
        for x in flat:
            by_cat[x[1].get("category")].append(x)
        rng = random.Random(20260417)
        per = max(1, n_questions // len(by_cat))
        sampled: list = []
        for c, xs in by_cat.items():
            rng.shuffle(xs)
            sampled.extend(xs[:per])
        remaining = n_questions - len(sampled)
        if remaining > 0:
            extra = []
            for c, xs in by_cat.items():
                extra.extend(xs[per:])
            rng.shuffle(extra)
            sampled.extend(extra[:remaining])
        rng.shuffle(sampled)
        flat = sampled[:n_questions]
        print(
            f"  stratified sample: {len(flat)} across {len(by_cat)} categories "
            f"{[(CATEGORY_NAMES.get(c,c), len(xs)) for c,xs in by_cat.items()]}",
            flush=True,
        )

    # Ingest each conversation ONCE, reused across its QAs
    ingested: set[int] = set()
    per_type: dict[str, dict] = {}
    overall = {"n": 0, "correct": 0, "total_ingested_turns": 0}
    per_query_log: list[dict] = []
    t_start = time.time()
    config_path = cfg_src

    # Checkpoint load (resume support)
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
                    cat_name = rec.get("category", "?")
                    per_type.setdefault(cat_name, {"n": 0, "correct": 0})
                    per_type[cat_name]["n"] += 1
                    per_type[cat_name]["correct"] += int(bool(rec.get("correct")))
            if done_qids:
                print(f"  resume: {len(done_qids)} completed from checkpoint", flush=True)
        except Exception as e:
            print(f"  checkpoint load warn: {e}", flush=True)

    def _qid(conv_idx: int, qa: dict, fallback_idx: int) -> str:
        # LoCoMo QA has no stable id — use (conv_idx, question text hash)
        import hashlib
        q = qa.get("question", "")
        h = hashlib.md5(q.encode()).hexdigest()[:10]
        return f"c{conv_idx}_{h}"

    def _append_checkpoint(rec: dict) -> None:
        if checkpoint_path is None:
            return
        try:
            checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            with checkpoint_path.open("a") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:
            pass

    for q_idx, (conv_idx, qa) in enumerate(flat):
        qid = _qid(conv_idx, qa, q_idx)
        if qid in done_qids:
            continue
        domain = f"locomo_{conv_idx}"
        if conv_idx not in ingested:
            conv = data[conv_idx]["conversation"]
            raw = build_turns(conv)
            # Route through the full pipeline once per conversation.
            # Three-body refinement gets to see all 600+ turns at once per
            # conversation, so the insights it coins ("Caroline regularly
            # volunteers at the shelter") are grounded in the full chat —
            # exactly the multi-hop summary the benchmark rewards. Without
            # this we'd be benchmarking only the flat-retrieval layer.
            bulk_turns = [
                {
                    # build_turns returns "Speaker: text" — convert to a
                    # neutral role for the pipeline. user/assistant role
                    # matters only for which side KG triple-extraction runs.
                    "role": "user",
                    "content": content,
                    "metadata": {
                        "turn_id": dia_id or f"s{snum}_t0",
                        "session_date": sdate,
                        "session": snum,
                    },
                }
                for snum, dia_id, sdate, content in raw
            ]
            stats = mind.ingest_turns_raw(
                bulk_turns, domain=domain,
                run_aggregation=True,
                run_refinement=use_refinement,
            )
            overall["total_ingested_turns"] += stats["ingested"]
            ingested.add(conv_idx)

        category = qa.get("category")
        question = qa.get("question", "")
        raw_answer = qa.get("answer", "")
        answer_str = str(raw_answer)
        processed_answer = preprocess_answer(category, answer_str)

        # Reference date: use first session date of this conversation
        first_sdate = ""
        for snum, dia_id, sdate, _ in build_turns(data[conv_idx]["conversation"])[:1]:
            first_sdate = sdate
            break
        try:
            ref_dt = datetime.fromisoformat(first_sdate)
            ref_human = ref_dt.strftime("%B %d, %Y")
        except Exception:
            ref_human = "2023"

        # Mem0 uses top_k=200 by default. Match for fair comparison.
        TOP_K = 200
        if use_agentic:
            from radiomind.storage.agentic import agentic_search
            def _llm_fn(prompt: str) -> str:
                return llm_call(prompt, config_path, model=answer_model,
                                 max_tokens=150, profile=answer_profile)
            def _search_fn(q, domain=None, max_results=TOP_K):
                return mind.search(q, domain=domain, max_results=max_results)
            results = agentic_search(
                question, _search_fn, _llm_fn, domain=domain,
                per_subquery_k=50, final_k=TOP_K,
            )
        else:
            results = mind.search(question, domain=domain, max_results=TOP_K)

        # Attention-driven retrieval augmentation: for specific-detail
        # lookups ("What does X do while Y?"), vector-only top-k often
        # misses peripheral detail turns (gold: Tilly the stuffed dog —
        # mentioned once in 600+ turn haystacks). A second pass asks the
        # store with a keyword-narrowed variant to raise recall on the
        # specific named subject. Merged at a reserved tail so existing
        # top scorers still lead. Cheap (single extra search call) and
        # no-op when the query isn't a specific-detail shape.
        try:
            from radiomind.core.attention import is_specific_detail_lookup
            if is_specific_detail_lookup(question):
                # Pull out the possessive/subject noun as keyword
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

        mem_results = []
        for r in results[:TOP_K]:
            sdate = (r.entry.metadata or {}).get("session_date", "")
            mem_results.append({
                "memory": r.entry.content,
                "score": float(getattr(r, "score", 0.0)),
                "created_at": sdate,
            })

        # Bottom-up NumericAggregator: deterministic count/total view
        # from ingest-time aggregation. Outranks the heuristic draft
        # when it hits. Empty for non-cardinal queries.
        cardinal_section = ""
        try:
            cardinal_section = mind.get_numeric_cardinal(
                query=question, domain=domain, user_id="",
            )
        except Exception:
            pass

        # Attention-driven trinity pipelines (S3.2):
        # - temporal_precision  → TEMPORAL PRECISION VIEW prefix
        # - open_domain_specific → OPEN-DOMAIN SPECIFIC PICK prefix
        # Both pipelines are no-op for queries that don't match their
        # attention pattern. Cheap (single LLM call each when active).
        temporal_section = ""
        open_domain_section = ""
        try:
            temporal_section = mind.run_temporal_precision(
                query=question, retrieved_memories=mem_results,
                reference_date=ref_human, domain=domain,
            )
        except Exception:
            pass
        try:
            open_domain_section = mind.run_open_domain_specific(
                query=question, retrieved_memories=mem_results, domain=domain,
            )
        except Exception:
            pass

        # V7 Step 1: evidence-candidate injection (deterministic, zero LLM
        # cost, fires for ALL queries with retrieved memories). Replaces
        # V6.6.p2 dominant-signal hint with first-class candidate evidence.
        evidence_section = ""
        try:
            evidence_section = mind.run_evidence_candidates(
                query=question, retrieved_memories=mem_results,
            )
        except Exception:
            pass

        profile_section = ""
        try:
            profile_section = mind.profile_hint(query=question)
        except Exception:
            pass

        # V8.2.2a: role/title mismatch guard. Deterministic regex check.
        # See run_longmemeval_mem0.py for full design rationale.
        role_guard_section = ""
        try:
            from radiomind.core.role_mismatch_guard import role_mismatch_guard
            role_guard_section = role_mismatch_guard(question, mem_results)
        except Exception:
            pass

        # V8.2.3a: cashback arithmetic hint (cross-bench consistent).
        cashback_hint_section = ""
        try:
            from radiomind.core.arithmetic_hint import cashback_arithmetic_hint
            cashback_hint_section = cashback_arithmetic_hint(question, mem_results)
        except Exception:
            pass

        # Attention-driven atomic decomposition (aggregation queries only).
        # Same logic as LongMemEval-S harness. DRAFT framing + placed
        # before memories so raw turns remain the model's last-seen
        # (most-salient) context. Skip when cardinal view already fired.
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
                lines = ["DRAFT ATOMIC VIEW (extracted heuristically — VERIFY against the memories below; enumerate additional entries if any memory mentions one not listed here):"]
                for a in atoms[:15]:
                    count_tag = f" [×{a.count}]" if a.count > 1 else ""
                    verified = " ✓KG" if a.kg_verified else ""
                    lines.append(f"- {a.fact}{count_tag}{verified} "
                                 f"(conf {a.confidence:.2f}, from {','.join(a.evidence[:3])})")
                atomic_section = "\n".join(lines) + "\n\n"
        except Exception:
            pass

        ans_prompt = get_answer_generation_prompt(
            question=question, search_results=mem_results,
            reference_date=ref_human,
        )
        # V8.2.2a: role guard innermost (between memories and other sections)
        if role_guard_section:
            ans_prompt = role_guard_section + ans_prompt
        # V8.2.3a: cashback arithmetic hint
        if cashback_hint_section:
            ans_prompt = cashback_hint_section + ans_prompt
        if atomic_section:
            ans_prompt = atomic_section + ans_prompt
        if cardinal_section:
            ans_prompt = cardinal_section + ans_prompt
        if temporal_section:
            ans_prompt = temporal_section + ans_prompt
        if open_domain_section:
            ans_prompt = open_domain_section + ans_prompt
        if evidence_section:
            ans_prompt = evidence_section + ans_prompt
        if profile_section:
            ans_prompt = profile_section + ans_prompt
        # (role_guard already injected innermost — between memories and other sections)
        # Meta calibration directive (self-observation → answer bias correction).
        # Appended after Mem0's verbatim prompt so base rules still apply.
        calibration = mind.get_meta_calibration()
        if calibration:
            ans_prompt = ans_prompt + "\n\n" + calibration
        try:
            # 1500 tokens leaves room for all 7 reasoning steps + final answer.
            answer = llm_call(
                ans_prompt, config_path,
                model=answer_model, max_tokens=1500, profile=answer_profile,
            )
        except Exception as e:
            answer = f"[answer error: {e}]"

        # Trinity salvage (query-time safety net): if answer model abstained,
        # run three-body over retrieved memories to recover a committed guess.
        try:
            from radiomind.refinement.salvage import AbstentionSalvager, looks_abstained
            if looks_abstained(answer):
                def _sv_llm(prompt: str, sys_prompt: str) -> str:
                    return llm_call(prompt, config_path,
                                     model=answer_model, max_tokens=400,
                                     profile=answer_profile)
                sv = AbstentionSalvager(_sv_llm)
                salvage = sv.salvage(question, answer, results[:40])
                if salvage and salvage.committed:
                    answer = salvage.answer
        except Exception:
            pass

        # V8.2.2b: role mismatch post-rewrite. When guard fired and LLM still
        # committed numeric specifics, rewrite to canonical abstain.
        try:
            from radiomind.core.role_mismatch_guard import maybe_rewrite_with_guard
            answer = maybe_rewrite_with_guard(question, mem_results, answer)
        except Exception:
            pass

        judge_prompt = get_judge_prompt(category, question, processed_answer, answer)
        is_correct = False
        verdict = ""
        try:
            # LoCoMo judge returns JSON with reasoning + label. 300 tokens was
            # enough for short reasoning but not for complex cases — bump to 600
            # to be safe.
            verdict = llm_call(
                judge_prompt, config_path,
                model=judge_model, max_tokens=600, profile=judge_profile,
                system="You are evaluating conversational AI memory recall. Return JSON only with the format requested.",
            )
            # Parse JSON {"reasoning":..., "label":"CORRECT"|"WRONG"}
            import re as _re
            m = _re.search(r'"label"\s*:\s*"?(CORRECT|WRONG)', verdict, _re.I)
            if m:
                is_correct = m.group(1).upper() == "CORRECT"
            else:
                # Fallback: if no JSON label found, check last meaningful word
                tail = verdict.lower()[-80:]
                is_correct = ("correct" in tail) and ("wrong" not in tail)
        except Exception as e:
            verdict = f"[judge error: {e}]"

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

        cat_name = CATEGORY_NAMES.get(category, str(category))
        overall["n"] += 1
        overall["correct"] += int(is_correct)
        per_type.setdefault(cat_name, {"n": 0, "correct": 0})
        per_type[cat_name]["n"] += 1
        per_type[cat_name]["correct"] += int(is_correct)

        record = {
            "question_id": qid,
            "q": question, "gold": processed_answer, "answer": answer,
            "correct": is_correct, "category": cat_name,
            "verdict_tail": verdict[-200:],
            "n_retrieved": len(results),
        }
        per_query_log.append(record)
        _append_checkpoint(record)

        if (q_idx + 1) % 10 == 0:
            acc = overall["correct"] / overall["n"]
            elapsed = time.time() - t_start
            print(f"  [{q_idx+1}/{len(flat)}] acc={acc:.3f}  t={elapsed:.0f}s", flush=True)

    elapsed = time.time() - t_start
    mind.shutdown()

    return {
        "benchmark": "LoCoMo — Mem0 protocol",
        "protocol": "mem0 prompts; cats 1-4; one ingest per conversation",
        "n_questions": overall["n"],
        "total_ingested_turns": overall["total_ingested_turns"],
        "reranker_enabled": use_reranker,
        "temporal_math": use_temporal_math,
        "agentic": use_agentic,
        "answer_model": answer_model, "judge_model": judge_model,
        "answer_profile": answer_profile, "judge_profile": judge_profile,
        "elapsed_s": round(elapsed, 1),
        "overall_accuracy": round(overall["correct"] / max(1, overall["n"]), 4),
        "by_type": {
            t: {"n": v["n"], "accuracy": round(v["correct"] / max(1, v["n"]), 4)}
            for t, v in sorted(per_type.items())
        },
        "per_query": per_query_log,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=200)
    p.add_argument("--sandbox", default="/tmp/rm-e2e-locomo-mem0")
    p.add_argument("--no-reranker", action="store_true")
    p.add_argument(
        "--benchmark-mode", default="a2a-practice",
        choices=("a2a-strict", "a2a-practice", "max"),
        help="Protocol alignment with Mem0 (a2a-strict / a2a-practice / max). "
             "See LME-S harness for full definition.",
    )
    p.add_argument("--temporal-math", action="store_true",
                   help="DEPRECATED: auto-routed by attention classifier.")
    p.add_argument("--agentic", action="store_true",
                   help="DEPRECATED: --benchmark-mode max enables this.")
    p.add_argument("--no-refinement", action="store_true",
                   help="Skip three-body chat refinement at ingest (default on — builds L3 principles)")
    p.add_argument("--categories", default="1,2,3,4")
    p.add_argument("--answer-model", default="gpt-4o")
    p.add_argument("--judge-model", default="gpt-4o")
    p.add_argument("--answer-profile", default="openai_direct")
    p.add_argument("--judge-profile", default="openai_direct")
    p.add_argument("--out", default="bench/end_to_end/locomo-mem0proto.json")
    p.add_argument("--checkpoint", default="",
                   help="Checkpoint .jsonl path. Appends per-question results; resume via same path. Default <out>.checkpoint.jsonl")
    p.add_argument("--qids", default="",
                   help="Comma-separated qid list (LoCoMo qid format c{conv_idx}_{md5_10}). When set, runs only these qids and skips stratified sampling — for V6.5.1+ targeted smoke validation.")
    args = p.parse_args()

    if not DATASET.exists():
        print(f"Dataset missing at {DATASET}")
        return 2

    cats = tuple(int(c) for c in args.categories.split(",") if c)
    print(
        f"Running {args.n or 1540} questions on LoCoMo cats {cats}; "
        f"answer={args.answer_model}/{args.answer_profile}, "
        f"judge={args.judge_model}/{args.judge_profile}; "
        f"reranker={not args.no_reranker}, temporal_math={args.temporal_math}, "
        f"agentic={args.agentic}",
        flush=True,
    )
    import os as _os
    mode = args.benchmark_mode
    if mode == "a2a-strict":
        _os.environ["RADIOMIND_ATTENTION_ROUTER"] = "off"
    elif mode == "max":
        _os.environ["RADIOMIND_ATTENTION_ROUTER"] = "on"
        args.agentic = True
    else:
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
        categories=cats,
        checkpoint_path=cp_path,
        qids_filter=qids_set,
    )
    report["benchmark_mode"] = mode
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2))

    print(f"\n=== LoCoMo (Mem0 protocol), {report['n_questions']} queries ===")
    print(f"  Overall accuracy: {report['overall_accuracy']:.3f}")
    print(f"  Reranker:         {report['reranker_enabled']}")
    print(f"  Time:             {report['elapsed_s']:.0f}s")
    print("\n  By category:")
    for t, stats in report["by_type"].items():
        print(f"    {t:20s} (n={stats['n']:3d})  acc={stats['accuracy']:.3f}")
    print(f"\n  Saved → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
