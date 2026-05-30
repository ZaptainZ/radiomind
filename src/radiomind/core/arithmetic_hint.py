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
    """Return the first detected cashback rate as a fraction (e.g. 0.01 for 1%).

    DEPRECATED (Phase 1.5a 2026-05-28): unscoped — returns the first
    rate in ANY memory, which produced a false-positive on 9aaed6a3
    (grabbed Walmart+ 2% and applied it to a SaveMart question).
    Kept only for backward-compat callers; new code must use
    `_find_cashback_rate_scoped`.
    """
    for t in mem_texts:
        m = _RATE_RE.search(t)
        if m:
            try:
                return float(m.group(1)) / 100.0
            except ValueError:
                continue
    return None


# Generic "applies to everything" scope — a rate stated as applying
# to all purchases is usable even without a merchant mention.
_GENERIC_SCOPE_RE = re.compile(
    r"\b(?:all|every|each)\s+(?:purchase|transaction|order|buy|"
    r"grocery\s+purchase)s?\b|\bon\s+everything\b|\bany\s+purchase\b",
    re.IGNORECASE,
)

# Ownership / first-person language that marks a rate as the USER's
# actual card rate (vs a hypothetical assistant recommendation).
_OWNERSHIP_RE = re.compile(
    r"\b(?:your|you'?ll\s+earn|you\s+earn|you\s+get|i\s+have|"
    r"my\s+|i\s+earn|i\s+get|i'?ve\s+got)\b",
    re.IGNORECASE,
)

# Competing-merchant signal: a brand token with "+" (Walmart+) or a
# capitalized brand followed by membership/card/rewards/program/
# cashback. Used to distinguish `rate_merchant_mismatch` from
# `rate_anchor_unscoped` (both refuse; label is for diagnosis).
_OTHER_BRAND_RE = re.compile(
    r"\b([A-Z][A-Za-z]{2,})\+"
    r"|\b([A-Z][A-Za-z]{2,})\s+(?:membership|card|rewards?|program|plus)\b",
)


def _has_competing_merchant(text: str, target_lower: str) -> bool:
    """True if the text names a brand distinct from the target."""
    for m in _OTHER_BRAND_RE.finditer(text):
        brand = (m.group(1) or m.group(2) or "").lower().rstrip("+")
        if brand and brand != target_lower:
            return True
    return False


def _find_cashback_rate_scoped(
    mem_texts: list[str], merchant: str | None,
) -> tuple[float | None, str | None]:
    """Return (rate_fraction, refusal_reason).

    A rate is only returned when it can be attributed to the SAME
    context the question asks about:
      1. merchant-scoped: rate appears in a memory that also mentions
         the target merchant (strongest).
      2. generic: rate stated as applying to "all/every purchase"
         AND with first-person ownership language (the user's own
         card), not a hypothetical recommendation.

    Refusal reasons (Phase 1.5a):
      - `no_cashback_rate_in_memories`
      - `multiple_conflicting_rates`        (≥2 distinct rates in scope)
      - `rate_merchant_mismatch`            (only rates belong to a
                                             different named merchant)
      - `rate_anchor_unscoped`              (rate floats with no merchant
                                             / generic context)
      - `rate_not_supporting_target_merchant` (other rates exist, can't
                                             cleanly classify)
    """
    target = (merchant or "").lower().strip()
    target_rates: set[float] = set()
    generic_rates: set[float] = set()
    other_rates: set[float] = set()
    other_named_merchant = False
    other_no_context = False

    for t in mem_texts:
        low = t.lower()
        for m in _RATE_RE.finditer(t):
            try:
                rate = round(float(m.group(1)) / 100.0, 4)
            except ValueError:
                continue
            if target and target in low:
                target_rates.add(rate)
            elif _GENERIC_SCOPE_RE.search(t) and _OWNERSHIP_RE.search(t):
                generic_rates.add(rate)
            else:
                other_rates.add(rate)
                if _has_competing_merchant(t, target):
                    other_named_merchant = True
                else:
                    other_no_context = True

    if target_rates:
        if len(target_rates) == 1:
            return next(iter(target_rates)), None
        return None, "multiple_conflicting_rates"
    if generic_rates:
        if len(generic_rates) == 1:
            return next(iter(generic_rates)), None
        return None, "multiple_conflicting_rates"
    if other_rates:
        if other_named_merchant:
            # A competing named merchant owns the rate(s) — never
            # safe to attribute to the target. (9aaed6a3 root case:
            # Walmart+ 2% must not apply to a SaveMart question.)
            return None, "rate_merchant_mismatch"
        if not target and len(other_rates) == 1:
            # No merchant in the question + a single unambiguous
            # rate with no competing brand → safe to compute.
            return next(iter(other_rates)), None
        if target:
            # Question names a merchant but the rate floats free of
            # it — don't attribute.
            return None, "rate_not_supporting_target_merchant"
        # No target, multiple unscoped rates → can't disambiguate.
        return None, "rate_anchor_unscoped"
    return None, "no_cashback_rate_in_memories"


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
# Rate-missing refusal reasons that SelfAnchor-2b may supplement
# via a merchant-scoped store scan (the rate exists in the store
# but ranked out of retrieve). Excludes amount-side refusals.
_RATE_MISSING_REFUSALS = frozenset({
    "no_cashback_rate_in_memories",
    "rate_merchant_mismatch",
    "rate_anchor_unscoped",
    "rate_not_supporting_target_merchant",
})


def cashback_arithmetic_hint(
    question: str,
    retrieved_memories: list[Any],
    mind: Any | None = None, domain: str | None = None,
) -> str:
    """Return a calculation hint prefix, or "" if conditions don't fire.

    Fires only when ALL three hold:
      1. Query is a cashback/rebate earning question
      2. Retrieved memories contain a cashback rate (X%) ATTRIBUTABLE
         to the target merchant or a generic all-purchases scope
         (Phase 1.5a — no longer the first rate in any memory)
      3. Retrieved memories contain a spend amount (preferably at the
         merchant named in the question)

    SelfAnchor-2b: when the spend amount IS present and the merchant
    IS known but the merchant-scoped RATE is missing from retrieve
    (a rate-missing refusal), AND mind+domain are supplied, a
    targeted store scan recovers the rate from the domain's user-turn
    layer (the merchant-scoped rate often ranks out of retrieve
    top-200; SelfAnchor-2a confirmed). The scan reuses the same
    merchant scoping, so a competing-merchant rate is still rejected.
    Store scan supplements ONLY the rate, never the amount.

    Format:
      "ARITHMETIC HINT: memories show <rate>% cashback and $<amount> spent
       at <merchant>; product = <rate> × $<amount> = $<result>."
    """
    if not _query_triggers(question):
        return ""
    mems = _iter_memory_text(retrieved_memories)
    if not mems:
        return ""

    merchant = _extract_merchant_from_query(question)
    # Phase 1.5a: merchant-scoped rate (refuse when the only rate
    # belongs to a different merchant / can't be attributed).
    rate, rate_refusal = _find_cashback_rate_scoped(mems, merchant)

    rate_source = None  # (turn_id, scan_scope)
    if rate is None:
        # SelfAnchor-2b: only supplement a rate-missing refusal, only
        # when merchant is known AND the spend amount is already
        # present in retrieve (store scan补 rate, 不补 amount).
        if (rate_refusal in _RATE_MISSING_REFUSALS
                and merchant and mind is not None and domain):
            amount_probe = _find_merchant_amount(mems, merchant)
            if amount_probe is not None:
                from radiomind.core.self_anchor import (
                    scan_cashback_rate_user_turns,
                )
                proof = scan_cashback_rate_user_turns(mind, domain, merchant)
                if proof is not None:
                    rate = proof.value
                    rate_source = (proof.source_turn_id, proof.scan_scope)
        if rate is None:
            return ""

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
    rate_clause = ""
    if rate_source:
        rate_clause = (f"  (rate via SelfAnchor store-scan from turn "
                       f"{rate_source[0]}, scope={rate_source[1]})\n")
    return (
        "ARITHMETIC HINT (deterministic, from retrieved memories):\n"
        f"  Memories show {rate_str}% cashback rate and {amount_str} spent{merchant_clause}.\n"
        f"{rate_clause}"
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
    mind: Any | None = None, domain: str | None = None,
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

    SelfAnchor-1b: when the retail anchor is satisfied but the paid
    anchor is missing from retrieved user turns AND `mind`+`domain`
    are supplied, a targeted store scan recovers the paid price from
    the domain's user-turn layer (the paid anchor often ranks out of
    retrieve top-200). The scan is item-scoped, user-turns only, and
    its source turn_id + quote are surfaced in the hint.

    Returns "" otherwise. Hint-only — never forces commit.
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
        if len(retail_amounts) != 1:
            continue
        retail = retail_amounts[0]

        # SelfAnchor-1b: retail present, paid missing → store-scan.
        paid_source = None  # (turn_id, quote, scan_scope)
        if len(paid_amounts) == 0 and mind is not None and domain:
            from radiomind.core.self_anchor import (
                scan_paid_price_user_turns,
            )
            proof = scan_paid_price_user_turns(mind, domain, anchor)
            if proof is not None:
                paid_amounts = [proof.value]
                paid_source = (proof.source_turn_id, proof.quote,
                               proof.scan_scope)

        if len(paid_amounts) != 1:
            continue
        paid = paid_amounts[0]
        if retail < paid:
            continue  # impossible "savings" → refuse
        saving = retail - paid
        # Render dollar amounts cleanly
        def _fmt(v: float) -> str:
            return f"${v:.2f}" if v % 1 else f"${v:.0f}"
        paid_line = f"  Paid: {_fmt(paid)} (user-stated purchase price"
        if paid_source:
            paid_line += (f"; SelfAnchor store-scan from turn "
                          f"{paid_source[0]}, scope={paid_source[2]}, "
                          f"quote={paid_source[1]!r}")
        paid_line += ")\n"
        return (
            "ARITHMETIC HINT (deterministic, from retrieved memories):\n"
            f"  Item: {anchor}\n"
            f"{paid_line}"
            f"  Retail: {_fmt(retail)} (user-stated original / "
            f"retail / MSRP price)\n"
            f"  Saving: {_fmt(retail)} − {_fmt(paid)} = "
            f"{_fmt(saving)}.\n"
            f"  If the question asks how much was saved on "
            f"{anchor}, the answer is {_fmt(saving)}.\n\n"
        )
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1.5 Diagnostic / Refusal-Reason Hooks (read-only)
# ─────────────────────────────────────────────────────────────────────────────
# These functions mirror the corresponding helpers but return
# structured `{fired, refusal_reason, proof}` records instead of
# the prompt-prefix string. They do NOT mutate helper behavior —
# only expose WHY a helper stayed silent (or which proof inputs
# it used when it fired). Consumed by diagnose_qid.py.

# Wider age-phrase regex used ONLY for diagnostics: identifies
# memories carrying age info in normalized variants
# (e.g. "at age 25") that the strict _age_at_event regex misses.
_DIAG_AGE_VARIANT_RE = re.compile(
    r"\b(?:at\s+age|aged|at\s+the\s+age\s+of|when\s+i\s+was|"
    r"i\s+(?:was|am)|when\s+i\s+turned|turned)\s+(\d{1,3})\b",
    re.IGNORECASE,
)


def diagnose_savings(
    question: str, retrieved_memories: list[Any],
) -> dict:
    """Parallel diagnostic for `savings_arithmetic_hint`.

    Returns:
      {
        "fired": bool,
        "refusal_reason": str | None,
        "anchor": str | None,
        "paid_amounts": list[float],
        "retail_amounts": list[float],
        "computed_saving": float | None,
      }

    Refusal-reason codes:
      - `no_trigger_match`
      - `item_anchor_too_short`
      - `no_user_turns_in_memories`
      - `paid_anchor_not_found_in_user_turns`
      - `multi_paid_amounts`
      - `retail_anchor_not_found_in_user_turns`
      - `multi_retail_amounts`
      - `retail_less_than_paid`
    """
    out: dict = {
        "fired": False, "refusal_reason": None, "anchor": None,
        "paid_amounts": [], "retail_amounts": [],
        "computed_saving": None,
    }
    if not question:
        out["refusal_reason"] = "empty_question"
        return out
    if not retrieved_memories:
        out["refusal_reason"] = "no_retrieved_memories"
        return out
    m = _SAVINGS_QUERY_TRIGGER.search(question)
    if not m:
        out["refusal_reason"] = "no_trigger_match"
        return out
    item_phrase = m.group("item").strip()
    anchors = _savings_item_anchors(item_phrase)
    if not anchors:
        out["refusal_reason"] = "item_anchor_too_short"
        return out
    user_texts: list[str] = []
    for txt in _iter_memory_text(retrieved_memories):
        if "[assistant]" in txt.lower():
            continue
        user_texts.append(txt)
    if not user_texts:
        out["refusal_reason"] = "no_user_turns_in_memories"
        return out
    blob = "\n".join(user_texts)

    last_reason: str = "no_anchor_fully_matched"
    for anchor in anchors:
        paid_amounts = _savings_scan_amounts(
            blob, anchor, _SAVINGS_PAID_TEMPLATES,
        )
        retail_amounts = _savings_scan_amounts(
            blob, anchor, _SAVINGS_RETAIL_TEMPLATES,
        )
        if len(paid_amounts) == 0:
            last_reason = "paid_anchor_not_found_in_user_turns"
            continue
        if len(paid_amounts) > 1:
            last_reason = "multi_paid_amounts"
            continue
        if len(retail_amounts) == 0:
            last_reason = "retail_anchor_not_found_in_user_turns"
            continue
        if len(retail_amounts) > 1:
            last_reason = "multi_retail_amounts"
            continue
        if retail_amounts[0] < paid_amounts[0]:
            last_reason = "retail_less_than_paid"
            continue
        out.update({
            "fired": True, "refusal_reason": None,
            "anchor": anchor,
            "paid_amounts": paid_amounts,
            "retail_amounts": retail_amounts,
            "computed_saving": retail_amounts[0] - paid_amounts[0],
        })
        return out
    out["refusal_reason"] = last_reason
    # Record the first anchor's amounts for visibility
    if anchors:
        out["anchor"] = anchors[0]
        out["paid_amounts"] = _savings_scan_amounts(
            blob, anchors[0], _SAVINGS_PAID_TEMPLATES,
        )
        out["retail_amounts"] = _savings_scan_amounts(
            blob, anchors[0], _SAVINGS_RETAIL_TEMPLATES,
        )
    return out


def diagnose_cashback(
    question: str, retrieved_memories: list[Any],
) -> dict:
    """Parallel diagnostic for `cashback_arithmetic_hint`.

    Refusal-reason codes:
      - `no_trigger_match`
      - `no_user_memories`
      - `no_cashback_rate_in_memories`
      - `no_merchant_amount`
    """
    out: dict = {
        "fired": False, "refusal_reason": None,
        "rate": None, "merchant": None, "amount": None,
        "computed_cashback": None,
    }
    if not _query_triggers(question):
        out["refusal_reason"] = "no_trigger_match"
        return out
    mems = _iter_memory_text(retrieved_memories)
    if not mems:
        out["refusal_reason"] = "no_user_memories"
        return out
    merchant = _extract_merchant_from_query(question)
    out["merchant"] = merchant
    # Always record amount (for diagnosis) — even on a rate-missing
    # refusal — so callers can tell whether the amount side is also
    # missing (SelfAnchor-2b only supplements the rate, not amount).
    amount = _find_merchant_amount(mems, merchant)
    out["amount"] = amount
    # Phase 1.5a: merchant-scoped rate finder returns a specific
    # refusal reason when the rate can't be attributed to the
    # target merchant / a generic scope.
    rate, rate_refusal = _find_cashback_rate_scoped(mems, merchant)
    if rate is None:
        out["refusal_reason"] = rate_refusal
        return out
    out["rate"] = rate
    if amount is None:
        out["refusal_reason"] = "no_merchant_amount"
        return out
    out["fired"] = True
    out["computed_cashback"] = rate * amount
    return out


# ─────────────────────────────────────────────────────────────────────────────
# TrustClosure-1b: cashback commit closure (cashback-specific pilot)
# ─────────────────────────────────────────────────────────────────────────────
# Generalizes the TSI-1d age_interval post-rewrite to cashback — the only
# helper with an empirical, unhandled trust-gap (TrustClosure-1a: 9aaed6a3
# abstains ~1/4-1/3 even when the hint carries 1% x $75 = $0.75). NOT a
# global registry — a single cashback closure. Hard gate (Codex-locked):
#   - only cashback; only when llm_answer is a PURE canonical abstain
#   - complete proof: merchant + amount (retrieved) + rate (retrieve-scoped
#     OR SelfAnchor-2b store-scan, with source)
#   - merchant-scoped / generic-all-purposes scope only (reuse
#     _find_cashback_rate_scoped — competing/conflicting → no rate → bypass)
#   - recompute: rate x amount == committed value
#   - amount missing / concrete answer / any mismatch → bypass

def resolve_cashback_proof(
    question: str, retrieved_memories, mind=None, domain=None,
) -> dict | None:
    """Return a complete cashback proof dict, or None when any anchor is
    missing/ambiguous. Mirrors cashback_arithmetic_hint's resolution
    (same scoped finders) so hint and closure never disagree.

    dict: {merchant, amount, rate, product,
           rate_source_turn_id, rate_scan_scope}
    """
    if not _query_triggers(question):
        return None
    mems = _iter_memory_text(retrieved_memories)
    if not mems:
        return None
    merchant = _extract_merchant_from_query(question)
    if not merchant:
        return None
    # amount MUST be in retrieve — store scan supplements rate only
    amount = _find_merchant_amount(mems, merchant)
    if amount is None:
        return None
    rate, refusal = _find_cashback_rate_scoped(mems, merchant)
    rate_src_tid = None
    rate_scope = None
    if rate is None:
        if (refusal in _RATE_MISSING_REFUSALS
                and mind is not None and domain):
            from radiomind.core.self_anchor import (
                scan_cashback_rate_user_turns,
            )
            proof = scan_cashback_rate_user_turns(mind, domain, merchant)
            if proof is not None:
                rate = proof.value
                rate_src_tid = proof.source_turn_id
                rate_scope = proof.scan_scope
    if rate is None:
        return None
    return {
        "merchant": merchant,
        "amount": amount,
        "rate": rate,
        "product": round(rate * amount, 2),
        "rate_source_turn_id": rate_src_tid,
        "rate_scan_scope": rate_scope,
    }


def maybe_cashback_commit_closure(
    question: str, retrieved_memories, llm_answer: str,
    mind=None, domain=None,
) -> str:
    """If the LLM emitted a PURE abstain but the cashback proof is
    complete and recomputes, commit the computed value. Otherwise return
    llm_answer unchanged. Mirrors maybe_age_interval_commit_closure.
    """
    from radiomind.core.age_interval_commit import _is_pure_abstain
    if not _is_pure_abstain(llm_answer):
        return llm_answer
    proof = resolve_cashback_proof(
        question, retrieved_memories, mind=mind, domain=domain,
    )
    if proof is None:
        return llm_answer
    if round(proof["rate"] * proof["amount"], 2) != proof["product"]:
        return llm_answer

    def _fmt(v: float) -> str:
        return f"${v:.2f}" if v % 1 else f"${v:.0f}"

    return (f"You earned {_fmt(proof['product'])} in cashback "
            f"at {proof['merchant']}.")
