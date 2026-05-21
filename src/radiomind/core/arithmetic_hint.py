"""V8.2.3a: Cashback arithmetic helper.

Codex audit insight: target `9aaed6a3` (SaveMart $0.75) is NOT a retrieve
miss — gold-bearing memories ("$75 at SaveMart last Thursday", "1%
cashback on all purchases") are at retrieve rank 1-3. The failure is
answer-side: LLM didn't compute 1% × $75 = $0.75.

This module emits a deterministic arithmetic hint when:
  1. Question matches a cashback-earning pattern
  2. Retrieved memories contain both a cashback rate (X%) and a dollar
     amount at the same merchant
  3. The product is well-defined

The hint is prepended to the answer prompt as a CALCULATION HINT — not
a commit override. LLM still decides; we just surface the math it
otherwise misses.

Scope (Codex-locked):
  - cashback / rebate / "earned at" patterns ONLY
  - NOT a generic percentage helper
  - NOT a temporal helper
  - NOT a sum/count/ordering helper
  - hint-only, never forces commit
"""
from __future__ import annotations

import re
from typing import Any


# ─────────────────────────────────────────────────────────────────────────────
# Query trigger patterns
# ─────────────────────────────────────────────────────────────────────────────
# Strict cashback-earning question patterns. Each must include:
#   1. "how much" / "what was" / etc. question stem
#   2. "cashback" or "rebate" or "earn at X" type predicate
_QUERY_TRIGGERS = [
    # "How much cashback did I earn at SaveMart?"
    re.compile(
        r"\bhow\s+much\s+(?:cash\s*back|cashback|rebate|reward)s?"
        r"(?:\s+did\s+i)?\s+(?:earn|get|receive|accumulate)",
        re.IGNORECASE,
    ),
    # "What was my cashback at SaveMart?"
    re.compile(
        r"\bwhat\s+(?:was|is)\s+(?:my|the)\s+(?:cash\s*back|cashback|rebate|reward)",
        re.IGNORECASE,
    ),
    # "How much did I earn in cashback at X?"
    re.compile(
        r"\bhow\s+much\s+did\s+i\s+earn\s+in\s+(?:cash\s*back|cashback|rebate|reward)",
        re.IGNORECASE,
    ),
]


def _query_triggers(question: str) -> bool:
    """Return True if question is a cashback/rebate earning question."""
    if not question:
        return False
    return any(p.search(question) for p in _QUERY_TRIGGERS)


# ─────────────────────────────────────────────────────────────────────────────
# Extraction
# ─────────────────────────────────────────────────────────────────────────────
# Rate patterns: "1% cashback", "1 percent cashback", "2.5% rewards"
_RATE_RE = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*(?:%|percent)\s+(?:cash\s*back|cashback|rebate|reward|back)",
    re.IGNORECASE,
)

# Amount patterns: "$75", "$3.99", "$100 at SaveMart"
_AMOUNT_RE = re.compile(r"\$\s*(\d+(?:,\d{3})*(?:\.\d+)?)")

# Merchant proper noun candidates from query (e.g. "SaveMart", "Target")
_MERCHANT_RE = re.compile(
    r"\b(?:at|from|in)\s+([A-Z][A-Za-z]+(?:[A-Z][a-z]*)?(?:\s+[A-Z][a-z]+)?)\b"
)


def _extract_merchant_from_query(question: str) -> str | None:
    """Extract merchant proper noun from question (after 'at'/'from'/'in')."""
    m = _MERCHANT_RE.search(question)
    if m:
        return m.group(1)
    return None


def _iter_memory_text(retrieved_memories: list[Any]) -> list[str]:
    out: list[str] = []
    for r in retrieved_memories or []:
        if isinstance(r, dict):
            content = r.get("memory") or r.get("content") or ""
        elif hasattr(r, "entry"):
            content = getattr(r.entry, "content", "") or ""
        elif hasattr(r, "content"):
            content = getattr(r, "content", "") or ""
        else:
            content = ""
        if content:
            out.append(content)
    return out


def _parse_amount(s: str) -> float:
    return float(s.replace(",", ""))


def _find_cashback_rate(mem_texts: list[str]) -> float | None:
    """Return the first detected cashback rate as a fraction (e.g. 0.01 for 1%)."""
    for t in mem_texts:
        m = _RATE_RE.search(t)
        if m:
            try:
                return float(m.group(1)) / 100.0
            except ValueError:
                continue
    return None


def _find_merchant_amount(
    mem_texts: list[str], merchant: str | None,
) -> float | None:
    """Return amount spent at the merchant (or first plausible spend amount).

    Looks for patterns like "$75 at SaveMart" or "spent $75 ... SaveMart".
    If merchant given, prefer memories mentioning that merchant.

    Safety guard (Codex follow-up): when merchant is None AND the unscoped
    memories contain multiple distinct $ amounts, return None — we cannot
    safely pick one without merchant anchoring, so refuse to hint rather
    than risk a wrong product.
    """
    if merchant:
        # Filter memories containing merchant
        cand = [t for t in mem_texts if merchant.lower() in t.lower()]
        if not cand:
            cand = mem_texts
    else:
        cand = mem_texts
        # Codex guard: refuse to pick when merchant is None and memories
        # have multiple distinct amounts ≥ $5 (likely unrelated spends).
        all_amts: set[float] = set()
        for t in cand:
            for m in _AMOUNT_RE.finditer(t):
                try:
                    v = _parse_amount(m.group(1))
                except ValueError:
                    continue
                if v >= 5:
                    all_amts.add(round(v, 2))
        if len(all_amts) >= 2:
            return None  # ambiguous — refuse hint

    # Look for the user's spend amount — prefer "$N" near "spent" / "groceries"
    spend_kw = re.compile(
        r"(?:spent|spend|paid|bought|purchase[ds]?\s+for|total\s*(?:was|of|=)?)\s*(?:[^\n]{0,30})?\$",
        re.IGNORECASE,
    )
    for t in cand:
        # Try spend-context first
        for m_spend in spend_kw.finditer(t):
            # Find next $amount after the spend keyword
            tail = t[m_spend.start():m_spend.start() + 80]
            m_amt = _AMOUNT_RE.search(tail)
            if m_amt:
                try:
                    return _parse_amount(m_amt.group(1))
                except ValueError:
                    continue

    # Fallback: first $amount in the merchant-filtered candidates
    for t in cand:
        m_amt = _AMOUNT_RE.search(t)
        if m_amt:
            try:
                amt = _parse_amount(m_amt.group(1))
                # Skip tiny amounts that are likely unit prices not totals
                if amt >= 5:
                    return amt
            except ValueError:
                continue
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Main entry
# ─────────────────────────────────────────────────────────────────────────────
def cashback_arithmetic_hint(
    question: str,
    retrieved_memories: list[Any],
) -> str:
    """Return a calculation hint prefix, or "" if conditions don't fire.

    Fires only when ALL three hold:
      1. Query is a cashback/rebate earning question
      2. Retrieved memories contain a cashback rate (X%)
      3. Retrieved memories contain a spend amount (preferably at the
         merchant named in the question)

    Format:
      "ARITHMETIC HINT: memories show <rate>% cashback and $<amount> spent
       at <merchant>; product = <rate> × $<amount> = $<result>."
    """
    if not _query_triggers(question):
        return ""
    mems = _iter_memory_text(retrieved_memories)
    if not mems:
        return ""

    rate = _find_cashback_rate(mems)
    if rate is None:
        return ""

    merchant = _extract_merchant_from_query(question)
    amount = _find_merchant_amount(mems, merchant)
    if amount is None:
        return ""

    product = rate * amount
    # Format result: show 2 decimal places if not whole
    if abs(product - round(product)) < 1e-9:
        product_str = f"${product:.0f}"
    else:
        product_str = f"${product:.2f}"

    rate_pct = rate * 100
    rate_str = f"{rate_pct:g}"  # strip trailing zeros (1.0 → "1", 2.5 → "2.5")
    amount_str = f"${amount:.2f}" if amount % 1 else f"${amount:.0f}"

    merchant_clause = f" at {merchant}" if merchant else ""
    return (
        "ARITHMETIC HINT (deterministic, from retrieved memories):\n"
        f"  Memories show {rate_str}% cashback rate and {amount_str} spent{merchant_clause}.\n"
        f"  Calculation: {rate_str}% × {amount_str} = {product_str}.\n"
        f"  If the question asks for cashback earned, the answer is {product_str}.\n\n"
    )
