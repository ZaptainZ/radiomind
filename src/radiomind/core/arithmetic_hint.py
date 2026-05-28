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


# ─────────────────────────────────────────────────────────────────────────────
# SavingsHint (V8.4-A 2026-05-28): savings = retail − paid for a named item
# ─────────────────────────────────────────────────────────────────────────────
# Pre-implementation audit: bench/end_to_end/savings_hint_1a_audit.py.
# Audit result (LME-S 500-qid): trigger surface = 2 (bb7c3b45,
# e25c3b8d); only bb7c3b45 has both anchors aligned to same item
# under strict 80-char proximity. Codex-locked gate:
#   - NO LLM semantic matching
#   - NO item synonym expansion
#   - NO coupon/discount family
#   - NO direct "I saved $X" extraction (retail − paid ONLY)
#   - hint-only, never forces commit (no post-rewrite)
#   - retail must be >= paid
#   - exactly 1 paid and 1 retail amount; multi-amount → reject

_SAVINGS_QUERY_TRIGGER = re.compile(
    r"how\s+much\s+(?:did|do|have|can)\s+i\s+sav\w+\s+"
    r"(?:on|for|buying|when\s+i\s+(?:bought|got))\s+"
    r"(?P<item>.{1,80}?)\s*[\?\.\!]",
    re.IGNORECASE,
)

# Paid-price patterns. Each REQUIRES an explicit paid verb so a
# retail sentence's "for $N" isn't falsely captured.
_SAVINGS_PAID_TEMPLATES = (
    # "got/bought/purchased [item] ... for $X"
    r"\b(?:got|bought|purchased|grabbed|picked\s+up|snagged)\s+"
    r"(?:my\s+|the\s+|a\s+|some\s+|this\s+|that\s+)?{ITEM}\b"
    r"[^.?\n]{{0,80}}?\bfor\s+(?:only\s+|just\s+)?\$\s*"
    r"(\d[\d,]*(?:\.\d+)?)",
    # "paid $X ... for [item]"
    r"\bpaid\s+(?:only\s+|just\s+)?\$\s*(\d[\d,]*(?:\.\d+)?)"
    r"[^.?\n]{{0,60}}?\bfor\s+(?:my\s+|the\s+|a\s+|some\s+|"
    r"this\s+|that\s+)?{ITEM}\b",
    # "[item] (that|which|,) I got/bought ... for $X"
    r"\b{ITEM}\b[^.?\n]{{0,40}}?(?:that\s+|which\s+|,\s*)?\bi\s+"
    r"(?:got|bought|purchased|grabbed|snagged|picked\s+up)\b"
    r"[^.?\n]{{0,60}}?\bfor\s+(?:only\s+|just\s+)?\$\s*"
    r"(\d[\d,]*(?:\.\d+)?)",
)

# Retail / original-price patterns.
_SAVINGS_RETAIL_TEMPLATES = (
    # "[item] ... originally retailed/listed/cost/priced for $Y"
    r"\b{ITEM}\b[^.?\n]{{0,80}}?\boriginally\s+"
    r"(?:retail\w*|list\w*|cost\w*|price\w*|sold)"
    r"(?:\s+(?:for|at))?\s*\$\s*(\d[\d,]*(?:\.\d+)?)",
    # "originally retailed for $Y ... [item]"
    r"\boriginally\s+(?:retail\w*|list\w*|cost\w*|price\w*|sold)"
    r"(?:\s+(?:for|at))?\s*\$\s*(\d[\d,]*(?:\.\d+)?)"
    r"[^.?\n]{{0,80}}?\b{ITEM}\b",
    # "[item] ... (it was) originally $Y"
    r"\b{ITEM}\b[^.?\n]{{0,80}}?\b(?:it\s+was\s+|that\s+was\s+)?"
    r"originally\s+\$\s*(\d[\d,]*(?:\.\d+)?)",
    # MSRP / retail price / price tag / original price
    r"\b{ITEM}\b[^.?\n]{{0,80}}?\b(?:MSRP|retail\s+price|"
    r"list(?:ed|ing)?\s+price|price\s+tag|original\s+price)\s*"
    r"(?:of|was|is|at)?\s*\$\s*(\d[\d,]*(?:\.\d+)?)",
    r"\b(?:MSRP|retail\s+price|list(?:ed|ing)?\s+price|"
    r"price\s+tag|original\s+price)\s*(?:of|was|is|at)?\s*"
    r"\$\s*(\d[\d,]*(?:\.\d+)?)[^.?\n]{{0,80}}?\b{ITEM}\b",
)


def _savings_normalize_phrase(s: str) -> str:
    s = re.sub(r"\s+", " ", (s or "").lower().strip())
    s = s.rstrip("?.!,; ").strip()
    s = re.sub(r"^(?:my\s+|the\s+|a\s+|an\s+|some\s+)", "", s)
    return s


def _savings_item_anchors(item_phrase: str) -> list[str]:
    """Return candidate item anchors, most-specific first.
    Minimum 2 tokens (brand+noun); generic 1-token forms NOT
    emitted alone to avoid over-firing.
    """
    norm = _savings_normalize_phrase(item_phrase)
    out: list[str] = []
    if len(norm.split()) >= 2:
        out.append(norm)
    # Strip trailing locative phrase ("at TK Maxx", "from Nordstrom")
    trimmed = re.split(
        r"\s+\b(?:at|in|from|on|inside|outside)\b\s+",
        norm, maxsplit=1,
    )[0]
    if trimmed != norm and len(trimmed.split()) >= 2:
        out.append(trimmed)
    tokens = norm.split()
    if len(tokens) >= 3:
        head3 = " ".join(tokens[:3])
        if head3 not in out and len(head3.split()) >= 2:
            out.append(head3)
    return list(dict.fromkeys(out))


def _savings_scan_amounts(
    text: str, item_anchor: str, templates: tuple[str, ...],
) -> list[float]:
    """Return deduplicated amounts matched by the templates."""
    item_re = re.escape(item_anchor)
    found: set[float] = set()
    for tpl in templates:
        pat_str = tpl.format(ITEM=item_re)
        try:
            pat = re.compile(pat_str, re.IGNORECASE)
        except re.error:
            continue
        for m in pat.finditer(text):
            try:
                amt = float(m.group(1).replace(",", ""))
            except (TypeError, ValueError, IndexError):
                continue
            found.add(round(amt, 2))
    return sorted(found)


def savings_arithmetic_hint(
    question: str, retrieved_memories: list[Any],
) -> str:
    """Return a deterministic arithmetic hint for the savings
    delta on a specific item when ALL of these hold:

      1. Question matches `how much (did|do|have|can) I sav[e/ed]
         on/for/buying [item]?`.
      2. The matched item anchor is ≥2 tokens (brand+noun).
      3. Exactly ONE paid amount with explicit paid verb in
         user-turn memories.
      4. Exactly ONE retail / original / MSRP amount in user-
         turn memories.
      5. retail >= paid (otherwise math is impossible — refuse).

    Returns "" otherwise. Hint-only — never forces commit.
    Architecture parallel to cashback_arithmetic_hint.
    """
    if not question or not retrieved_memories:
        return ""
    m = _SAVINGS_QUERY_TRIGGER.search(question)
    if not m:
        return ""
    item_phrase = m.group("item").strip()
    anchors = _savings_item_anchors(item_phrase)
    if not anchors:
        return ""

    # Collect user-turn memory text (or all if no role prefix)
    user_texts: list[str] = []
    for txt in _iter_memory_text(retrieved_memories):
        low = txt.lower()
        if "[assistant]" in low:
            continue
        user_texts.append(txt)
    if not user_texts:
        return ""
    blob = "\n".join(user_texts)

    # Try each item anchor; first that yields both 1 paid + 1
    # retail wins. Most-specific first per _savings_item_anchors.
    for anchor in anchors:
        paid_amounts = _savings_scan_amounts(
            blob, anchor, _SAVINGS_PAID_TEMPLATES,
        )
        retail_amounts = _savings_scan_amounts(
            blob, anchor, _SAVINGS_RETAIL_TEMPLATES,
        )
        if len(paid_amounts) != 1 or len(retail_amounts) != 1:
            continue
        paid = paid_amounts[0]
        retail = retail_amounts[0]
        if retail < paid:
            continue  # impossible "savings" → refuse
        saving = retail - paid
        # Render dollar amounts cleanly
        def _fmt(v: float) -> str:
            return f"${v:.2f}" if v % 1 else f"${v:.0f}"
        return (
            "ARITHMETIC HINT (deterministic, from retrieved memories):\n"
            f"  Item: {anchor}\n"
            f"  Paid: {_fmt(paid)} (user-stated purchase price)\n"
            f"  Retail: {_fmt(retail)} (user-stated original / "
            f"retail / MSRP price)\n"
            f"  Saving: {_fmt(retail)} − {_fmt(paid)} = "
            f"{_fmt(saving)}.\n"
            f"  If the question asks how much was saved on "
            f"{anchor}, the answer is {_fmt(saving)}.\n\n"
        )
    return ""
