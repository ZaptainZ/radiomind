"""Offline validation of V7 Step 1 evidence-candidate extraction.

Strategy: V6.6.p2 LLM answer text contains the retrieved memories it saw
(listed under 'Step 1: SCAN ALL MEMORIES'). Parse those out, feed to
extract_evidence_candidates, and report what the candidate set looks
like vs the gold answer.

This validates Step 1 extraction quality WITHOUT re-running the full
LoCoMo ingest pipeline (which hangs on the DashScope API).

Usage:
    python bench/end_to_end/validate_step1_offline.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from radiomind.core.evidence_candidates import (
    extract_evidence_candidates,
    render_evidence_candidates,
)


def parse_memories_from_answer(answer: str) -> list[dict]:
    """Extract memory list from a V6.6 LLM answer text.

    Accepts these formats:
      - (Friday, October 21, 2022) Joanna: "..."           (dashed list)
      - (Friday, October 21, 2022): Joanna says: "..."     (colon after paren)
      1. (Sunday, June 05, 2022): "..."                    (numbered list)
      2. (Tuesday, October 25, 2022): "..." and "..."
    """
    memories = []
    # Pattern: leading dash OR number, then (date), optional colon, then content
    pat = re.compile(
        r"^\s*(?:-|\d+\.)\s+\(([^)]{6,40})\)\s*:?\s*([^\n]+)$",
        re.MULTILINE,
    )
    for m in pat.finditer(answer):
        date = m.group(1).strip()
        content = m.group(2).strip()
        if len(content) < 5:  # skip empty stubs
            continue
        memories.append({
            "memory": f"({date}) {content}",
            "date": date,
        })
    return memories


def validate_qid(version_label: str, qid: str, q: str, gold: str, answer: str) -> None:
    """Validate a single qid: parse memories, extract candidates, report."""
    mems = parse_memories_from_answer(answer)
    candidates = extract_evidence_candidates(q, mems, top_k=8)

    print()
    print("─" * 90)
    print(f"[{version_label}] {qid}")
    print("─" * 90)
    print(f"Q:    {q}")
    print(f"GOLD: {gold}")
    print(f"  Parsed {len(mems)} memories from answer")
    print(f"  V7 Step 1 candidates ({len(candidates)}):")
    for i, c in enumerate(candidates, 1):
        tr = f" [{c.temporal_role}]" if c.temporal_role else ""
        sc = f" ×{c.source_count}" if c.source_count > 1 else ""
        print(f"    {i}. {c.candidate!r:35s} ({c.relation:25s}, conf={c.confidence:.2f}){tr}{sc}")

    # Check: does any candidate match the gold key token?
    gold_low = gold.lower()
    gold_tokens = set()
    # For relative-temporal gold ("A few years ago"), match the full phrase
    if re.search(r"a few years (ago|before|earlier)", gold_low):
        gold_tokens.add("few years")
    for w in re.findall(r"\b[a-zA-Z]{3,}\b", gold_low):
        if w not in {"the", "and", "with", "have", "from", "that", "this",
                     "for", "any", "his", "her", "be"}:
            gold_tokens.add(w)
    # Also include date tokens
    gold_tokens.update(re.findall(r"\d{4}", gold_low))

    cand_text = " ".join(c.candidate.lower() for c in candidates)
    hit = any(t in cand_text for t in gold_tokens)
    print(f"  Gold tokens: {sorted(gold_tokens)[:6]}")
    print(f"  Gold token in candidates: {'✓ YES' if hit else '✗ NO'}")


def main():
    # Load V6.6.p2 result and validate Step 1 on its 10 flip qids
    path = Path(__file__).parent / "validation" / "v6.6-path2-flip10-smoke.json"
    if not path.exists():
        print(f"missing: {path}", file=sys.stderr)
        sys.exit(1)
    data = json.loads(path.read_text())

    flip_qids = {
        "c1_69a7c9bffe", "c2_29183ecb5e", "c2_b4b43181aa",
        "c3_2656e2c771", "c3_94f06e1a00", "c3_a9fddfe69b",
        "c4_5cfba98ae8", "c5_dac00a436e", "c6_9da9f73c2a",
        "c9_5ab522b5c7",
    }

    n_total = 0
    n_hit = 0
    print("=" * 90)
    print("V7 STEP 1 OFFLINE VALIDATION (replaying V6.6.p2 retrieved memories)")
    print("=" * 90)
    for rec in data["per_query"]:
        if rec["question_id"] not in flip_qids:
            continue
        n_total += 1
        validate_qid("V6.6.p2-replay", rec["question_id"], rec["q"],
                     rec["gold"], rec["answer"])
        # Track hit
        mems = parse_memories_from_answer(rec["answer"])
        candidates = extract_evidence_candidates(rec["q"], mems, top_k=8)
        gold_low = rec["gold"].lower()
        gold_tokens = set()
        if re.search(r"a few years (ago|before|earlier)", gold_low):
            gold_tokens.add("few years")
        gold_tokens.update(set(re.findall(r"\b[a-zA-Z]{3,}\b", gold_low)) - {
            "the", "and", "with", "have", "from", "that", "this", "for",
            "any", "his", "her", "be",
        })
        gold_tokens.update(re.findall(r"\d{4}", gold_low))
        cand_text = " ".join(c.candidate.lower() for c in candidates)
        if any(t in cand_text for t in gold_tokens):
            n_hit += 1

    print()
    print("=" * 90)
    print("AGGREGATE")
    print("=" * 90)
    print(f"  Gold-token hit in candidate set: {n_hit}/{n_total}")
    print()
    print(
        "Interpretation: this measures whether Step 1's deterministic\n"
        "extraction surfaces the gold answer's key token AT ALL in the\n"
        "candidate list. It does NOT measure whether the answerer LLM\n"
        "picks the right candidate — that requires live LLM eval."
    )


if __name__ == "__main__":
    main()
