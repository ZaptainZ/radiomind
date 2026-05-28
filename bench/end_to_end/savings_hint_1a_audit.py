"""SavingsHint-1a: read-only pre-implementation audit.

Answers 4 questions before any helper code is written:

  Q1. LME-S full-500 trigger surface for
      `how much did I save on/for [item]`.

  Q2. For each trigger hit, whether the haystack carries
      BOTH anchors:
        paid:    `got/bought/purchased [item] for $X`
        retail:  `originally retailed/listed/cost ... $Y`
                 `MSRP / retail price / price tag`

  Q3. Same-item alignment stability: brand+item phrase
      must match on BOTH anchors. Generic noun alone
      (`shoes`, `heels`, `item`) doesn't pass; we want
      `Jimmy Choo heels` on both sides.

  Q4. Negatives — qids that hit the trigger but lack the
      2-anchor structure (likely `save for trip`,
      `save money`, charity ambiguity, etc.). These must
      be deterministically rejectable.

Strict gate (USER 2026-05-28): trigger surface ≤ 3,
bb7c3b45 is the cleanest positive, every negative is
rejectable, NO LLM, NO synonym, NO coupon/discount, NO
direct `I saved $X` extraction.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

DATASET = Path.home() / "Library/Caches/radiomind-data/longmemeval_s_cleaned.json"


# Q1: trigger regex. Conservative — require "how much" +
# "I save(d) on/for ..." or close variant.
_TRIGGER_RE = re.compile(
    r"how\s+much\s+(?:did|do|have|can)\s+i\s+"
    r"sav\w+\s+(?:on|for|buying|when\s+i\s+(?:bought|got))\s+"
    r"(?P<item>.{1,80}?)\s*[\?\.\!]",
    re.IGNORECASE,
)


# Paid-price anchor patterns. {ITEM} interpolated with
# regex-escaped item phrase. Each template REQUIRES an explicit
# paid verb (got/bought/purchased/paid) to avoid catching retail
# sentences that also contain "for $N" but in a "originally for"
# context.
_PAID_TEMPLATES = (
    # "got/bought/purchased [item] for $X" — verb-before-item
    r"\b(?:got|bought|purchased|grabbed|picked\s+up|snagged)\s+"
    r"(?:my\s+|the\s+|a\s+|some\s+|this\s+|that\s+)?{ITEM}\b"
    r"[^.?\n]{{0,80}}?\bfor\s+(?:only\s+|just\s+)?\$\s*"
    r"(\d[\d,]*(?:\.\d+)?)",
    # "paid $X for [item]"
    r"\bpaid\s+(?:only\s+|just\s+)?\$\s*(\d[\d,]*(?:\.\d+)?)"
    r"[^.?\n]{{0,60}}?\bfor\s+(?:my\s+|the\s+|a\s+|some\s+|"
    r"this\s+|that\s+)?{ITEM}\b",
    # "[item] (that|which|,) I got/bought for $X" — verb-after-item
    r"\b{ITEM}\b[^.?\n]{{0,40}}?(?:that\s+|which\s+|,\s*)?\bi\s+"
    r"(?:got|bought|purchased|grabbed|snagged|picked\s+up)\b"
    r"[^.?\n]{{0,60}}?\bfor\s+(?:only\s+|just\s+)?\$\s*"
    r"(\d[\d,]*(?:\.\d+)?)",
)

# Retail / original-price anchor patterns. Fix from initial draft:
# add `\s*` after the optional connector so e.g.
# `originally retailed for $500` matches (the space between
# `for` and `$` was being missed).
_RETAIL_TEMPLATES = (
    # "[item] ... originally retailed/listed/cost/priced for $Y"
    r"\b{ITEM}\b[^.?\n]{{0,80}}?\boriginally\s+"
    r"(?:retail\w*|list\w*|cost\w*|price\w*|sold)"
    r"(?:\s+(?:for|at))?\s*\$\s*(\d[\d,]*(?:\.\d+)?)",
    # "originally retailed/listed/cost for $Y ... [item]"
    r"\boriginally\s+(?:retail\w*|list\w*|cost\w*|price\w*|sold)"
    r"(?:\s+(?:for|at))?\s*\$\s*(\d[\d,]*(?:\.\d+)?)"
    r"[^.?\n]{{0,80}}?\b{ITEM}\b",
    # "[item] ... it/that was originally $Y"  (bare originally $N)
    r"\b{ITEM}\b[^.?\n]{{0,80}}?\b(?:it\s+was\s+|that\s+was\s+)?"
    r"originally\s+\$\s*(\d[\d,]*(?:\.\d+)?)",
    # "MSRP / retail price / price tag / original price [is/of/was] $Y"
    r"\b{ITEM}\b[^.?\n]{{0,80}}?\b(?:MSRP|retail\s+price|"
    r"list(?:ed|ing)?\s+price|price\s+tag|original\s+price)\s*"
    r"(?:of|was|is|at)?\s*\$\s*(\d[\d,]*(?:\.\d+)?)",
    r"\b(?:MSRP|retail\s+price|list(?:ed|ing)?\s+price|"
    r"price\s+tag|original\s+price)\s*(?:of|was|is|at)?\s*"
    r"\$\s*(\d[\d,]*(?:\.\d+)?)[^.?\n]{{0,80}}?\b{ITEM}\b",
)


def _normalize_phrase(s: str) -> str:
    """Lowercase, collapse whitespace, strip leading/trailing
    articles and pronouns."""
    s = re.sub(r"\s+", " ", s.lower().strip())
    # Drop trailing "?", ".", "!", whitespace
    s = s.rstrip("?.!,; ").strip()
    # Drop leading my/the/a/some/some_new
    s = re.sub(r"^(?:my\s+|the\s+|a\s+|an\s+|some\s+)", "", s)
    return s


def _item_anchors(item_phrase: str) -> list[str]:
    """Return candidate item phrases for matching, ordered most-
    specific first:
      1. Full normalized phrase ("designer handbag at TK Maxx").
      2. Phrase truncated at locative prepositions
         (drop trailing "at|in|from ..."): "designer handbag".
      3. First-3-tokens fallback ("designer handbag").

    Generic one-word forms (`heels`, `item`) are intentionally NOT
    emitted alone — that would over-fire on unrelated mentions.
    The minimum acceptable form is 2+ tokens (brand+noun).
    """
    norm = _normalize_phrase(item_phrase)
    out = [norm]
    # Strip trailing locative phrase: "X at Y" / "X in Y" / "X from Y"
    trimmed = re.split(
        r"\s+\b(?:at|in|from|on|inside|outside)\b\s+",
        norm, maxsplit=1,
    )[0]
    if trimmed != norm and len(trimmed.split()) >= 2:
        out.append(trimmed)
    # First-3-token fallback if still longer
    tokens = norm.split()
    if len(tokens) >= 3:
        head3 = " ".join(tokens[:3])
        if head3 not in out:
            out.append(head3)
    return list(dict.fromkeys(out))


def _scan_anchor(
    text: str, item: str, templates: tuple[str, ...],
) -> list[tuple[float, str]]:
    """Return [(amount, snippet)] hits."""
    item_re = re.escape(item)
    hits: list[tuple[float, str]] = []
    for tpl in templates:
        pat_str = tpl.format(ITEM=item_re)
        try:
            pat = re.compile(pat_str, re.IGNORECASE | re.DOTALL)
        except re.error:
            continue
        for m in pat.finditer(text):
            try:
                amt = float(m.group(1).replace(",", ""))
            except (TypeError, ValueError, IndexError):
                continue
            snippet = text[max(0, m.start()-40):m.end()+40].replace("\n", " ")
            hits.append((amt, snippet))
    return hits


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path,
                   default=Path("bench/end_to_end/savings-hint-1a-audit.json"))
    args = p.parse_args()
    data = json.loads(DATASET.read_text())

    # Q1: trigger surface
    triggered: list[dict] = []
    for q in data:
        qid = q.get("question_id") or q.get("id")
        question = q.get("question", "")
        m = _TRIGGER_RE.search(question)
        if not m:
            continue
        item_phrase = m.group("item").strip()
        triggered.append({
            "qid": qid,
            "question": question,
            "extracted_item": item_phrase,
            "gold": str(q.get("answer", ""))[:120],
            "raw_target": q,  # for stage-2 scan
        })

    print(f"=== Q1: Trigger surface ===")
    print(f"  total LME-S qids: {len(data)}")
    print(f"  trigger matches: {len(triggered)}")
    for t in triggered:
        print(f"  {t['qid']:<22} item={t['extracted_item']!r}")
        print(f"  {'':>22} gold={t['gold'][:80]!r}")

    # Q2 + Q3 + Q4: scan haystack for each triggered qid
    print(f"\n=== Q2 + Q3 + Q4: per-qid anchor scan ===")
    results: list[dict] = []
    for t in triggered:
        qid = t["qid"]
        target = t["raw_target"]
        item_phrase = t["extracted_item"]
        item_anchors = _item_anchors(item_phrase)
        # Build user-turn text (LongMemEval format: assistants
        # may also mention prices, but for the savings hint we
        # care about user-stated prices)
        all_text = "\n".join(
            t2.get("content", "")
            for sess in target.get("haystack_sessions", [])
            for t2 in sess
            if t2.get("role") == "user"
        )
        # Scan with each item anchor form; take best result
        best_paid: list[tuple[float, str]] = []
        best_retail: list[tuple[float, str]] = []
        best_anchor: str = ""
        for anchor in item_anchors:
            paid = _scan_anchor(all_text, anchor, _PAID_TEMPLATES)
            retail = _scan_anchor(all_text, anchor, _RETAIL_TEMPLATES)
            if paid or retail:
                # Prefer the anchor that produces hits
                if not best_anchor:
                    best_anchor = anchor
                if paid:
                    best_paid = paid
                if retail:
                    best_retail = retail
                if paid and retail:
                    best_anchor = anchor
                    break
        # Unique amounts (in case of duplicates)
        paid_amounts = sorted({round(a, 2) for a, _ in best_paid})
        retail_amounts = sorted({round(a, 2) for a, _ in best_retail})

        rec = {
            "qid": qid,
            "question": t["question"],
            "gold": t["gold"],
            "extracted_item": item_phrase,
            "item_anchors_tried": item_anchors,
            "matched_anchor": best_anchor,
            "paid_count": len(paid_amounts),
            "paid_amounts": paid_amounts,
            "paid_snippet_sample": (best_paid[0][1][:200]
                                     if best_paid else None),
            "retail_count": len(retail_amounts),
            "retail_amounts": retail_amounts,
            "retail_snippet_sample": (best_retail[0][1][:200]
                                       if best_retail else None),
            "two_anchor_clean": bool(
                len(paid_amounts) == 1 and len(retail_amounts) == 1
                and best_anchor
            ),
            "deterministic_saving": (
                retail_amounts[0] - paid_amounts[0]
                if (len(paid_amounts) == 1 and len(retail_amounts) == 1
                    and retail_amounts[0] >= paid_amounts[0])
                else None
            ),
        }
        results.append(rec)
        print(f"\n  {qid}:")
        print(f"    item:           {item_phrase!r}")
        print(f"    matched anchor: {best_anchor!r}")
        print(f"    paid:           {paid_amounts}")
        print(f"    retail:         {retail_amounts}")
        print(f"    two_anchor_clean: {rec['two_anchor_clean']}")
        print(f"    deterministic_saving: {rec['deterministic_saving']}")
        if rec['paid_snippet_sample']:
            print(f"    paid snippet:   {rec['paid_snippet_sample']}")
        if rec['retail_snippet_sample']:
            print(f"    retail snippet: {rec['retail_snippet_sample']}")

    # Aggregate gate assessment
    clean = [r for r in results if r["two_anchor_clean"]]
    print(f"\n=== Aggregate ===")
    print(f"  triggers:                    {len(triggered)}")
    print(f"  two-anchor-clean qids:       {len(clean)} {[r['qid'] for r in clean]}")
    print(f"  trigger surface <= 3:        {'OK' if len(triggered) <= 3 else 'FAIL'}")
    print(f"  only/cleanest is bb7c3b45:   "
          f"{'OK' if len(clean) == 1 and clean[0]['qid'] == 'bb7c3b45' else 'CHECK'}")
    # Negatives = triggered but NOT two_anchor_clean
    negatives = [r for r in results if not r["two_anchor_clean"]]
    print(f"  negatives (deterministic-rejectable): {len(negatives)} qids")
    for r in negatives:
        print(f"    {r['qid']}: paid={r['paid_count']}, retail={r['retail_count']}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"\nsaved → {args.out}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
