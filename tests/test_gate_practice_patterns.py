"""SmallUserReadiness-1e: high-precision 'practice' patterns rescue
present-tense habit statements whose verb is outside the routine whitelist
('I add / I validate …') ONLY when anchored on a generalization qualifier
(for any / at every / whenever …). Deterministic, no LLM.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from radiomind.core.gate import EXTRACTION_PATTERNS, extract_from_message
from radiomind.core.types import Message


def _kept(role: str, text: str) -> bool:
    return bool(extract_from_message(Message(role=role, content=text)))


# the two new patterns, isolated (must not over-broaden on their own)
_PRACTICE = [re.compile(p, re.I) for p, c in EXTRACTION_PATTERNS if c == "practice"]


def _practice_only(text: str) -> bool:
    return any(p.search(text) for p in _PRACTICE)


# ---------------- positives: rescued ----------------

def test_for_any_then_verb_rescued():
    assert _kept("user", "For any AI feature I add layered fallbacks: deterministic first")


def test_verb_then_at_every_rescued():
    assert _kept("user", "I validate inputs defensively at every boundary, even internal calls")


def test_whenever_rescued():
    assert _kept("user", "Whenever I deploy I run the regression pack first")


# ---------------- negatives: practice patterns must NOT match ----------------

def test_practice_patterns_skip_generic_statements():
    for neg in [
        "I add salt to taste",
        "I validate the form once",
        "I add two numbers together",
        "I think it's raining",          # caught by opinion (not practice)
    ]:
        assert not _practice_only(neg), neg


def test_add_salt_dropped_by_full_gate():
    # no generalization qualifier, no whitelisted verb → fully dropped
    assert not _kept("user", "I add salt to taste")
    assert not _kept("user", "I validate the form once")


# ---------------- assistant turns still hard-filtered ----------------

def test_assistant_same_text_dropped():
    assert not _kept("assistant", "For any AI feature I add layered fallbacks")
    assert not _kept("assistant", "I validate inputs at every boundary")


# ---------------- 8-sample keep rate improved ----------------

def test_eight_sample_keep_rate_at_least_5():
    samples = [
        ("user", "I always write parsers by hand instead of using a library"),
        ("assistant", "Hand-rolled parsers do give you full control"),
        ("user", "When I build network services I always add retry with backoff"),
        ("assistant", "Resilience patterns prevent cascading failures"),
        ("user", "I prefer adapter layers over rewriting a system"),
        ("user", "For any AI feature I add layered fallbacks: deterministic first"),
        ("user", "I validate inputs defensively at every boundary"),
        ("assistant", "Defense in depth at trust boundaries is a solid habit"),
    ]
    kept = sum(1 for role, text in samples if _kept(role, text))
    assert kept >= 5, f"expected >=5 kept, got {kept}"
    # all 3 assistant turns still dropped
    assert all(not _kept("assistant", t) for r, t in samples if r == "assistant")
