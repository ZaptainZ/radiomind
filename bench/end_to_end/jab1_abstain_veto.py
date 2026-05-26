"""JAB-1a abstain-veto core: shared between runner + offline scanner.

The LongMemEval judge prompt only specifies how to treat
abstention GOLDS — when a gold is "I don't know", the model's
abstain response is correct. It does NOT forbid the LLM judge
from passing an abstain response when the gold is concrete.

In practice gpt-4o sometimes accepts "The information provided
is not enough" for concrete-gold qids on a "respect the model's
caution" rule, producing false-passes. JAB-1a adds a
deterministic post-judge veto: if gold is concrete AND response
is canonical abstain → force FAIL.

The detector is intentionally high-precision:
  - GOLD-is-abstain hits skip the veto (legitimate abstain golds)
  - RESPONSE-is-abstain requires matching a canonical phrase

False negatives are acceptable (model gets credit for borderline
responses); false positives (vetoing real PASSes) are not.
"""
from __future__ import annotations

import re

# Gold strings that ARE abstain — out of veto scope (the harness
# rule legitimately accepts abstain responses for these).
_ABSTAIN_GOLD_PHRASES = (
    "the information provided is not enough",
    "not enough information",
    "i don't have enough information",
    "cannot be determined",
    "you haven't",         # "You haven't started working at Google yet"
    "you did not mention", # "You did not mention this information"
    "no record",
    "not specified",
    "did not specify",
)

# Canonical abstain RESPONSE patterns. When a response matches any
# of these, treat it as "the model declined to answer".
_ABSTAIN_RESPONSE_RE = re.compile(
    r"\b("
    r"the\s+information\s+provided\s+is\s+not\s+enough"
    r"|not\s+enough\s+information"
    r"|i\s+(?:don't|do\s+not)\s+have\s+(?:enough\s+)?information"
    r"|cannot\s+be\s+determined"
    r"|insufficient\s+information"
    r"|no\s+(?:specific\s+)?information"
    r"|(?:memories|context)\s+do\s+not\s+(?:provide|contain|specify)"
    r"|unable\s+to\s+determine"
    r")\b",
    re.IGNORECASE,
)


# Concrete-answer commitment markers. If a response carries one,
# the judge could have legitimately rewarded it; we must NOT veto.
# These are the surface forms LongMemEval golds typically take:
# currency, named durations, numeric counts, dates, explicit
# "the answer is X" framings.
_CONCRETE_COMMITMENT_RE = re.compile(
    # currency: $0.75, $300, $1,250
    r"\$\s*\d[\d,]*(?:\.\d+)?"
    # numeric quantity with unit: 7 years, 4 months, 2 days, 1%
    # trailing \b dropped — '%' is non-word so \b after % fails
    r"|\b\d+(?:\.\d+)?\s*"
    r"(?:%|dollars?|cents?|years?|months?|weeks?|days?|hours?|"
    r"minutes?|seconds?|times?|instruments?|people?|miles?|km|"
    r"kilometers?|degrees?)"
    # date / year: 2023, 2023-05-26, 05/26/2023
    r"|\b(?:19|20)\d{2}\b"
    # explicit answer-is framings
    r"|\b(?:the\s+answer\s+is|that\s+would\s+be|it(?:'s|\s+is)\s+(?:about|approximately|roughly|exactly)?)\s*\S",
    re.IGNORECASE,
)


def is_abstain_gold(gold: str) -> bool:
    """True when the gold itself is an abstention answer."""
    g = (gold or "").lower().strip()
    if not g:
        return False
    return any(p in g for p in _ABSTAIN_GOLD_PHRASES)


def has_concrete_commitment(answer: str) -> bool:
    """True when the response carries a concrete-answer commitment
    the judge could have rewarded.

    Used to avoid vetoing answers that hedge AFTER committing to a
    real value (e.g. "$0.75. Not enough info to determine why.")."""
    a = (answer or "").strip()
    if not a:
        return False
    return bool(_CONCRETE_COMMITMENT_RE.search(a))


def is_abstain_response(answer: str) -> bool:
    """True only when the response is unambiguously a refusal to
    commit — canonical abstain phrase present AND no concrete-
    answer commitment elsewhere in the response.

    False positives are not acceptable here: a wrong veto would
    flip a real PASS to FAIL in the bench harness.
    """
    a = (answer or "").strip()
    if not a:
        return False
    if not _ABSTAIN_RESPONSE_RE.search(a):
        return False
    # Canonical abstain phrase present. If the response ALSO carries
    # a concrete commitment (number, currency, date, etc.), it is
    # not a pure abstain — the judge may have rewarded the
    # commitment, so don't veto.
    if has_concrete_commitment(a):
        return False
    return True


def should_veto(gold: str, answer: str) -> bool:
    """True iff the LLM judge's correct=True must be overridden.

    Veto fires when:
      - the gold is a concrete answer (not itself an abstention), AND
      - the response is unambiguously canonical-abstain (no concrete
        commitment hidden inside).
    """
    if is_abstain_gold(gold):
        return False
    return is_abstain_response(answer)
