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
    tokens_low = {t.lower() for t in answer_tokens}
    for c in candidates[:k]:
        cand_low = c.candidate.lower()
        if cand_low in tokens_low:
            return True
        # Allow substring (e.g., "dragons" matches "dragon")
        for t in tokens_low:
            if t in cand_low or cand_low in t:
                return True
    return False


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
                "noise_in_injected_top": noise_in_injected,
                "injected_top": args.injected_top,
                "answer_token_in_injected_top": _has_answer_token_in_topk(
                    cands_default, answer_tokens, args.injected_top,
                ),
            },
            "simulated_fix": {
                "top_dump": [_candidate_record(i + 1, c)
                              for i, c in enumerate(cands_fixed[:args.top_k_candidate_dump])],
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
    noise_total = sum(r["default"]["noise_in_injected_top"] for r in per_qid)
    summary = {
        "n_qids": n_total,
        "injected_top": args.injected_top,
        "default_answer_token_in_top": f"{default_pass}/{n_total}",
        "simulated_fix_answer_token_in_top": f"{fixed_pass}/{n_total}",
        "total_noise_slots_default": noise_total,
        "noise_slot_fraction_default": f"{noise_total}/{n_total * args.injected_top}",
    }

    out_payload = {"summary": summary, "per_qid": per_qid}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out_payload, indent=2, ensure_ascii=False))

    # Console summary
    print("=" * 70)
    print(f"CQ-1 CANDIDATE QUALITY AUDIT (top-{args.injected_top} injected)")
    print("=" * 70)
    print(f"{'qid':<22}{'default':<14}{'simulated':<14}{'noise/top':<10}")
    for r in per_qid:
        d = "Y" if r["default"]["answer_token_in_injected_top"] else "."
        s = "Y" if r["simulated_fix"]["answer_token_in_injected_top"] else "."
        n = r["default"]["noise_in_injected_top"]
        print(f"{r['qid']:<22}{d:<14}{s:<14}{n}/{args.injected_top}")
    print()
    print(f"summary: {summary}")
    print(f"saved → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
