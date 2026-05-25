"""CQ-1: candidate-quality audit across flip10 qids.

For each flip10 qid (replayed on the sc3 sandbox), dumps:

  - top-15 EvidenceCandidate composition (candidate, relation,
    source_count, confidence, rank).
  - Noise counts per qid: candidates flagged as
      * conversational-opener proper nouns ("Sharing", "Yeah",
        "Wow", "Hey", "Yep", "Sounds", "And", "Not", "Playing",
        ...)
      * other-speaker name (per-conversation speaker_a / b)
  - Simulated re-rank result under a hypothesis: sort by
    `(confidence, source_count)` instead of
    `(source_count, confidence)`, AND drop noise candidates.
  - For both default and simulated rankings, check whether each
    qid's "answer-token" appears in top-5.

Read-only. No code change. Output JSON for machine readability +
console summary table.

Usage:
    python bench/end_to_end/cq1_candidate_quality_audit.py \\
        --sandbox /tmp/rm-sc3-locomo-flip10 \\
        --out bench/end_to_end/cq1-candidate-quality.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path


# flip10 qids + the answer-token we'd want to see in top-5 (LLM
# pre-commit hint). For some qids the gold is multi-word, in which
# case we list a representative content word.
FLIP10 = [
    ("c1_69a7c9bffe", ["years"]),                        # Gina tattoo: "A few years ago"
    ("c2_29183ecb5e", ["wealthy", "middle-class"]),     # financial
    ("c2_b4b43181aa", ["august"]),                       # Maria date
    ("c3_2656e2c771", ["two", "three"]),                 # Joanna count
    ("c3_94f06e1a00", ["tilly", "dog"]),                 # Tilly stuffed
    ("c3_a9fddfe69b", ["dragon", "dragons"]),            # Nate dragons
    ("c4_5cfba98ae8", ["seattle"]),                      # Seattle decisive
    ("c5_dac00a436e", ["voyageurs"]),                    # voyageurs (not in text)
    ("c6_9da9f73c2a", ["september", "2022"]),            # date
    ("c9_5ab522b5c7", ["hard", "determination"]),        # Calvin goals
]


# Noise stopword candidates we'd add to extend
# _PROPER_NOUN_STOPWORDS in the hypothesized fix
_NOISE_OPENERS = {
    "sharing",   # image-share metadata prefix
    "yeah", "yep", "wow", "hey", "sounds", "and", "not",
    "playing", "speaking", "definitely", "absolutely",
    "thanks", "thank", "sure", "oh", "great", "nice", "good",
    "yes", "no", "well",
}


def _is_noise(candidate: str, conv_speakers: set[str]) -> str | None:
    c = candidate.strip().lower()
    first_word = c.split()[0] if c else c
    if first_word in _NOISE_OPENERS:
        return "opener"
    # "Hey Joanna" → opener token followed by speaker; flag.
    parts = c.split()
    if parts and parts[0] in _NOISE_OPENERS and len(parts) >= 2:
        return "opener"
    if c in {s.lower() for s in conv_speakers}:
        return "speaker"
    # "Hey <speaker>" already caught by opener; check raw speaker prefix
    if len(parts) >= 2 and parts[1] in {s.lower() for s in conv_speakers}:
        return "speaker_compound"
    return None


def _resolve_qid(dataset: Path, qid: str) -> tuple[int, dict]:
    data = json.loads(dataset.read_text())
    for conv_idx, conv in enumerate(data):
        for qa in conv.get("qa", []):
            q = qa.get("question", "")
            h = hashlib.md5(q.encode()).hexdigest()[:10]
            if f"c{conv_idx}_{h}" == qid:
                return conv_idx, qa
    raise SystemExit(f"qid not found: {qid}")


def _speakers(conv: dict) -> set[str]:
    out: set[str] = set()
    for k in ("speaker_a", "speaker_b"):
        v = conv.get("conversation", {}).get(k)
        if isinstance(v, str):
            out.add(v)
    return out


def _candidate_record(rank: int, c) -> dict:
    return {
        "rank": rank,
        "candidate": c.candidate,
        "relation": c.relation,
        "source_count": c.source_count,
        "confidence": c.confidence,
    }


def _has_answer_token_in_topk(
    candidates: list, answer_tokens: list[str], k: int
) -> bool:
    """Word-boundary match — candidate token must contain the answer
    token as a whole word. Prevents false hits like "Do" matching
    "dog" (the bug user flagged in CQ-1 first run). Allows
    plurals via stem prefix (dragon ↔ dragons) only when the
    matched span is the entire candidate token (not "fragon").
    """
    import re as _re
    out_tokens = [t.lower() for t in answer_tokens]
    for c in candidates[:k]:
        cand_low = c.candidate.lower()
        for t in out_tokens:
            # Exact match
            if cand_low == t:
                return True
            # Plural / singular variant: candidate is t + s/es or t is
            # candidate + s/es; both must be whole tokens.
            if cand_low == t + "s" or cand_low == t + "es":
                return True
            if t == cand_low + "s" or t == cand_low + "es":
                return True
            # Multi-word candidates: t must appear as a whole word inside
            # candidate (\b boundary)
            if " " in cand_low and _re.search(rf"\b{_re.escape(t)}\b", cand_low):
                return True
    return False


def _count_generic_top5(candidates: list, k: int = 5) -> int:
    """Count slots in top-k that look like low-information generic
    framing tokens — conversational verbs/connectives that aren't
    in the noise stopword set but still don't carry answer
    semantics. Heuristic: proper_noun_in_context / activity_target /
    series_or_entity_name with confidence ≤ 0.6 AND single-word AND
    the word looks like a sentence opener / connective (verbs,
    indefinite words, etc.). This is a secondary metric for
    diagnostic display, not the gold-hit decision rule.
    """
    _GENERIC_FRAMING = {
        "do", "how", "last", "creating", "writing",
        "there", "everyone", "trying", "plus", "congrats",
        "next", "first", "before", "after", "during",
        "looking", "going", "coming", "talking", "thinking",
    }
    n = 0
    for c in candidates[:k]:
        if c.relation in ("proper_noun_in_context", "activity_target",
                          "series_or_entity_name"):
            if c.confidence <= 0.6:
                low = c.candidate.lower()
                if " " not in low and low in _GENERIC_FRAMING:
                    n += 1
    return n


def _count_known_junk_removed(default_cands: list, fixed_cands: list,
                              conv_speakers: set[str], k: int = 5) -> int:
    """How many of default top-k slots were filled by stopword/speaker
    noise that the simulated fix removed. Measures the direct effect
    of the stopword expansion + sort key change."""
    n = 0
    for c in default_cands[:k]:
        if _is_noise(c.candidate, conv_speakers) is not None:
            n += 1
    return n


def _simulate_fix(candidates: list, conv_speakers: set[str]) -> list:
    """Hypothesis: drop noise candidates + sort by (confidence, source_count)."""
    cleaned = [c for c in candidates if _is_noise(c.candidate, conv_speakers) is None]
    cleaned.sort(key=lambda c: (c.confidence, c.source_count), reverse=True)
    return cleaned


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--sandbox", type=Path,
                   default=Path("/tmp/rm-sc3-locomo-flip10"))
    p.add_argument("--dataset", type=Path,
                   default=Path.home() / "Library/Caches/radiomind-data/locomo10.json")
    p.add_argument("--top-k-retrieve", type=int, default=30)
    p.add_argument("--top-k-candidate-dump", type=int, default=15)
    p.add_argument("--injected-top", type=int, default=5)
    p.add_argument("--out", type=Path,
                   default=Path("bench/end_to_end/cq1-candidate-quality.json"))
    args = p.parse_args()

    if not (args.sandbox / "data").exists():
        print(f"sandbox missing: {args.sandbox}", file=sys.stderr)
        return 2

    os.environ["RADIOMIND_HOME"] = str(args.sandbox)
    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
    from radiomind.core.mind import RadioMind  # noqa: WPS433
    from radiomind.core.evidence_candidates import (  # noqa: WPS433
        extract_evidence_candidates, classify_query,
    )

    mind = RadioMind(llm=lambda p, s="": "")
    mind.initialize()

    data = json.loads(args.dataset.read_text())

    per_qid: list[dict] = []
    for qid, answer_tokens in FLIP10:
        conv_idx, qa = _resolve_qid(args.dataset, qid)
        question = qa["question"]
        domain = f"locomo_{conv_idx}"
        speakers = _speakers(data[conv_idx])
        qtype = classify_query(question)

        retrieved = mind.search(question, domain=domain, max_results=args.top_k_retrieve)
        cands_default = extract_evidence_candidates(
            question, retrieved, top_k=200,  # dump full ranking for analysis
        )
        cands_fixed = _simulate_fix(cands_default, speakers)

        # Noise composition of default top-N
        top_default = cands_default[:args.top_k_candidate_dump]
        noise_in_injected = sum(
            1 for c in cands_default[:args.injected_top]
            if _is_noise(c.candidate, speakers) is not None
        )

        rec = {
            "qid": qid,
            "question": question,
            "qtype": qtype,
            "domain": domain,
            "speakers": sorted(speakers),
            "answer_tokens": answer_tokens,
            "default": {
                "top_dump": [_candidate_record(i + 1, c) for i, c in enumerate(top_default)],
                "known_noise_in_injected_top": noise_in_injected,
                "generic_framing_in_injected_top": _count_generic_top5(
                    cands_default, args.injected_top,
                ),
                "injected_top": args.injected_top,
                "answer_token_in_injected_top": _has_answer_token_in_topk(
                    cands_default, answer_tokens, args.injected_top,
                ),
            },
            "simulated_fix": {
                "top_dump": [_candidate_record(i + 1, c)
                              for i, c in enumerate(cands_fixed[:args.top_k_candidate_dump])],
                "known_noise_removed_top": _count_known_junk_removed(
                    cands_default, cands_fixed, speakers, args.injected_top,
                ),
                "generic_framing_in_injected_top": _count_generic_top5(
                    cands_fixed, args.injected_top,
                ),
                "answer_token_in_injected_top": _has_answer_token_in_topk(
                    cands_fixed, answer_tokens, args.injected_top,
                ),
            },
        }
        per_qid.append(rec)

    # Aggregate
    n_total = len(per_qid)
    default_pass = sum(1 for r in per_qid if r["default"]["answer_token_in_injected_top"])
    fixed_pass = sum(1 for r in per_qid if r["simulated_fix"]["answer_token_in_injected_top"])
    known_noise_total = sum(r["default"]["known_noise_in_injected_top"] for r in per_qid)
    generic_default_total = sum(
        r["default"]["generic_framing_in_injected_top"] for r in per_qid)
    generic_fixed_total = sum(
        r["simulated_fix"]["generic_framing_in_injected_top"] for r in per_qid)
    summary = {
        "n_qids": n_total,
        "injected_top": args.injected_top,
        # M1: did the gold answer-token enter the injected top-K?
        "M1_gold_in_top_default": f"{default_pass}/{n_total}",
        "M1_gold_in_top_simulated": f"{fixed_pass}/{n_total}",
        # M2: how many KNOWN junk slots (stopwords/speakers) appear in
        # the default top-K? simulated fix removes all of these by
        # construction.
        "M2_known_junk_default_slots": (
            f"{known_noise_total}/{n_total * args.injected_top}"
        ),
        # M3: how many GENERIC framing tokens (verbs/connectives like
        # "Do/How/Last/Trying/Plus") remain in top-K. These are NOT
        # in the noise stopword set; they reflect the next layer of
        # candidate quality that the v1 fix does NOT touch.
        "M3_generic_framing_default": (
            f"{generic_default_total}/{n_total * args.injected_top}"
        ),
        "M3_generic_framing_simulated": (
            f"{generic_fixed_total}/{n_total * args.injected_top}"
        ),
    }

    out_payload = {"summary": summary, "per_qid": per_qid}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out_payload, indent=2, ensure_ascii=False))

    # Console summary
    print("=" * 78)
    print(f"CQ-1 CANDIDATE QUALITY AUDIT (top-{args.injected_top} injected)")
    print("=" * 78)
    print(f"{'qid':<22}{'M1_def':<8}{'M1_sim':<8}{'M2_junk':<10}"
          f"{'M3_gen_def':<12}{'M3_gen_sim':<12}")
    for r in per_qid:
        d = "Y" if r["default"]["answer_token_in_injected_top"] else "."
        s = "Y" if r["simulated_fix"]["answer_token_in_injected_top"] else "."
        j = r["default"]["known_noise_in_injected_top"]
        g_d = r["default"]["generic_framing_in_injected_top"]
        g_s = r["simulated_fix"]["generic_framing_in_injected_top"]
        print(f"{r['qid']:<22}{d:<8}{s:<8}{j}/{args.injected_top}      "
              f"{g_d}/{args.injected_top}        {g_s}/{args.injected_top}")
    print()
    for k, v in summary.items():
        print(f"  {k}: {v}")
    print(f"saved → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
