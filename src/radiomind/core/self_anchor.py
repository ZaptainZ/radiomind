"""SelfAnchor-1b: helper-specific store-scan supplement.

SelfAnchor-1a confirmed that 3 helper failures share one shape:
the user's first-person self-statement anchor (paid price /
current age) IS in the domain store's user-turn layer, but ranks
outside retrieve top-200 because FACT-layer events dominate the
window (user-turn recall 3-19%).

This module supplies a TARGETED, READ-ONLY store scan that the
helper invokes ONLY when:
  - the helper has already entered its correct semantic channel
    (trigger matched), AND
  - it is missing exactly one self anchor that retrieve didn't
    surface.

Hard constraints (Codex 2026-05-29):
  - does NOT change global mind.search ordering
  - scans USER turns only (role=="user" / "[user]" prefix);
    assistant echoes are rejected
  - helper-specific anchor scope (paid → item phrase; age →
    first-person current-age pattern, never a bare
    "N-year-old" and never a kin-owned age)
  - every result carries source_turn_id + quote + scan_scope so
    the proof stays traceable (never a black-box value)
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass
class SelfAnchorProof:
    """Traceable result of a store-scan supplement.

    `value`         the recovered anchor value (float for paid /
                    cashback_rate fraction, int for age)
    `source_turn_id` turn id of the user turn it came from
    `quote`         ~chars around the match, for human audit
    `scan_scope`    what the scan was restricted to (e.g.
                    "user_turns;item=jimmy choo heels",
                    "user_turns;first_person_current_age",
                    "user_turns;merchant=SaveMart")
    """
    kind: str            # "paid_price" | "current_age" | "cashback_rate"
    value: float
    source_turn_id: str
    quote: str
    scan_scope: str


# ─────────────────────────────────────────────────────────────────────────────
# Store user-turn enumeration (read-only)
# ─────────────────────────────────────────────────────────────────────────────
def _iter_store_user_turns(mind: Any, domain: str | None) -> list[tuple[str, str]]:
    """Return [(turn_id, content)] for USER turns in the domain store.

    Assistant turns and aggregated FACT events are excluded. This is
    the only place 1b reads from — it never touches retrieve ranking.
    """
    if mind is None or not getattr(mind, "_store", None) or not domain:
        return []
    try:
        from radiomind.core.types import MemoryLevel
        entries = mind._store.list_by_domain(
            domain, level=MemoryLevel.FACT, limit=1000,
        )
    except Exception:
        return []
    out: list[tuple[str, str]] = []
    for e in entries:
        content = e.content or ""
        meta = e.metadata if isinstance(e.metadata, dict) else {}
        is_user = (meta.get("role") == "user") or content.lower().startswith("[user]")
        if not is_user:
            continue
        tid = meta.get("turn_id", "?")
        out.append((tid, content))
    return out


def _quote(text: str, start: int, end: int, pad: int = 35) -> str:
    return text[max(0, start - pad):end + pad].replace("\n", " ").strip()


# ─────────────────────────────────────────────────────────────────────────────
# Current-age (first-person) — production-grade, kin-safe
# ─────────────────────────────────────────────────────────────────────────────
# Strict first-person current-age patterns. Deliberately NOT a bare
# "(\d{2})-year-old" (Codex warning): that would catch "my dad is a
# 58-year-old engineer" or "for someone in their 30s".
_SELF_CURRENT_AGE_PATTERNS = [
    # "I'm 32" / "I am 32" / "I am now 32" / "I'm 32 years old"
    re.compile(
        r"\bi(?:'m|\s+am)\s+(?:now\s+|currently\s+|already\s+)?(\d{2})\b"
        r"(?!\s*(?:%|years?\s+ago|minutes?|hours?|days?|weeks?|months?|dollars?))",
        re.IGNORECASE,
    ),
    # "I just turned 32" / "I recently turned 32" / "I turned 32"
    re.compile(
        r"\bi\s+(?:just\s+|recently\s+)?turned\s+(\d{2})\b",
        re.IGNORECASE,
    ),
    # "as a 32-year-old <occupation/self-noun>" — occupation suffix
    # forces present-tense self-identity (excludes "as a 25-year-old
    # I graduated", which is a past event age).
    re.compile(
        r"\bas\s+a\s+(\d{2})[-\s]year[-\s]old\s+"
        r"(?:digital|marketing|software|designer|engineer|student|"
        r"consultant|professional|specialist|developer|analyst|"
        r"manager|woman|man|guy|girl|professional)",
        re.IGNORECASE,
    ),
]

# Kin-possessive guard: if a kin owner sits just before the match,
# the age is NOT the user's own. Checked against the chars preceding
# the match.
_KIN_OWNER_RE = re.compile(
    r"\b(?:my\s+)?(?:mom|mother|mum|mama|mommy|dad|father|papa|daddy|"
    r"grandma|grandmother|nana|granny|gran|grandpa|grandfather|"
    r"granddad|gramps|sister|brother|son|daughter|niece|nephew|"
    r"aunt|uncle|cousin|friend|colleague|wife|husband|partner|"
    r"boss|neighbou?r)\b",
    re.IGNORECASE,
)


def _age_is_kin_owned(text: str, match_start: int) -> bool:
    """True if a kin/third-party owner appears in the window just
    before the age match (e.g. 'my dad, as a 58-year-old')."""
    window = text[max(0, match_start - 40):match_start]
    return bool(_KIN_OWNER_RE.search(window))


def scan_current_age_user_turns(
    mind: Any, domain: str | None,
) -> SelfAnchorProof | None:
    """Scan the domain store's user turns for the user's OWN current
    age. Returns a single unambiguous proof, or None.

    Refuses (returns None) when:
      - no first-person current-age statement found
      - multiple DISTINCT self ages found (ambiguous)
      - the only match is kin-owned
    """
    found: dict[int, tuple[str, str]] = {}  # age → (turn_id, quote)
    for tid, content in _iter_store_user_turns(mind, domain):
        for pat in _SELF_CURRENT_AGE_PATTERNS:
            for m in pat.finditer(content):
                if _age_is_kin_owned(content, m.start()):
                    continue
                try:
                    age = int(m.group(1))
                except (TypeError, ValueError):
                    continue
                if not (15 <= age <= 99):
                    continue
                if age not in found:
                    found[age] = (tid, _quote(content, m.start(), m.end()))
    if len(found) != 1:
        return None  # none or ambiguous → refuse
    age = next(iter(found))
    tid, quote = found[age]
    return SelfAnchorProof(
        kind="current_age", value=float(age),
        source_turn_id=tid, quote=quote,
        scan_scope="user_turns;first_person_current_age",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Paid price (item-scoped) — reuses SavingsHint paid templates
# ─────────────────────────────────────────────────────────────────────────────
def scan_paid_price_user_turns(
    mind: Any, domain: str | None, item_phrase: str,
) -> SelfAnchorProof | None:
    """Scan the domain store's user turns for the paid price of the
    query item. item_phrase must be a ≥2-token brand+noun anchor
    (the SavingsHint item anchor). Returns a single unambiguous
    proof, or None.
    """
    from radiomind.core.arithmetic_hint import (
        _SAVINGS_PAID_TEMPLATES, _savings_item_anchors,
    )
    anchors = _savings_item_anchors(item_phrase)
    if not anchors:
        return None
    for anchor in anchors:
        item_re = re.escape(anchor)
        found: dict[float, tuple[str, str]] = {}
        for tid, content in _iter_store_user_turns(mind, domain):
            for tpl in _SAVINGS_PAID_TEMPLATES:
                try:
                    pat = re.compile(tpl.format(ITEM=item_re), re.IGNORECASE)
                except re.error:
                    continue
                for m in pat.finditer(content):
                    try:
                        amt = round(float(m.group(1).replace(",", "")), 2)
                    except (TypeError, ValueError, IndexError):
                        continue
                    if amt not in found:
                        found[amt] = (tid, _quote(content, m.start(), m.end()))
        if len(found) == 1:
            amt = next(iter(found))
            tid, quote = found[amt]
            return SelfAnchorProof(
                kind="paid_price", value=amt,
                source_turn_id=tid, quote=quote,
                scan_scope=f"user_turns;item={anchor}",
            )
        if len(found) > 1:
            return None  # ambiguous paid prices for this anchor
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Cashback rate (merchant-scoped) — SelfAnchor-2b
# ─────────────────────────────────────────────────────────────────────────────
def scan_cashback_rate_user_turns(
    mind: Any, domain: str | None, merchant: str | None,
) -> SelfAnchorProof | None:
    """Scan the domain store's user turns for the merchant-scoped
    cashback rate. Reuses `_find_cashback_rate_scoped` verbatim, so
    a competing-merchant rate (e.g. Walmart+ 2% for a SaveMart
    question) is rejected exactly as on the retrieve side.

    Returns a single proof when the scoped finder yields one rate,
    else None. User turns only; never assistant echo; merchant must
    be known (no merchant-less scan).
    """
    if not merchant:
        return None
    from radiomind.core.arithmetic_hint import (
        _find_cashback_rate_scoped, _RATE_RE,
    )
    user_turns = _iter_store_user_turns(mind, domain)
    if not user_turns:
        return None
    texts = [c for _, c in user_turns]
    rate, reason = _find_cashback_rate_scoped(texts, merchant)
    if rate is None:
        return None
    # Locate the source turn + quote for the chosen merchant-scoped
    # rate (a user turn mentioning the merchant AND a rate).
    m_low = merchant.lower()
    target_pct = round(rate * 100, 4)
    for tid, content in user_turns:
        if m_low not in content.lower():
            continue
        for m in _RATE_RE.finditer(content):
            try:
                pct = round(float(m.group(1)), 4)
            except (TypeError, ValueError):
                continue
            if pct == target_pct:
                return SelfAnchorProof(
                    kind="cashback_rate", value=rate,
                    source_turn_id=tid,
                    quote=_quote(content, m.start(), m.end()),
                    scan_scope=f"user_turns;merchant={merchant}",
                )
    # Rate resolved (e.g. via generic all-purchases scope) but no
    # merchant-co-located source turn found — return proof without a
    # specific turn rather than fabricate one.
    return SelfAnchorProof(
        kind="cashback_rate", value=rate,
        source_turn_id="?", quote="",
        scan_scope=f"user_turns;merchant={merchant}",
    )
