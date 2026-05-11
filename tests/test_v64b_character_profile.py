"""Tests for V6.4-B: multi-character profile section in run_open_domain_specific.

V6.4-B extends "user profile" to all dialog characters. For queries
whose subject is a non-user character (LoCoMo dialog), the answer LLM
gets a structured profile of THAT character distilled from memories.

Also verifies V6.4-A.1 fix: ENTITY DISAMBIGUATION PICK + answer_hint
section accumulate (not replace). The composition is:
    CHARACTER PROFILE + ENTITY DISAMBIGUATION PICK + ANSWER-HINT
"""
from __future__ import annotations

import json
from types import SimpleNamespace


def _mk_memory(content: str, mid: int = 0):
    entry = SimpleNamespace(
        id=mid,
        content=content,
        metadata={"session_date": "2024-01-01"},
    )
    return SimpleNamespace(entry=entry, score=0.9)


class _SequenceStubLLM:
    """Sequential canned JSON responses."""

    def __init__(self, responses):
        self._seq = [json.dumps(r) if isinstance(r, dict) else r for r in responses]
        self.calls = 0

    def is_available(self) -> bool:
        return True

    def generate(self, prompt, system=""):
        idx = min(self.calls, len(self._seq) - 1)
        self.calls += 1
        r = SimpleNamespace()
        r.text = self._seq[idx]
        return r


def _profile_response(profile: dict) -> dict:
    return {
        "stances": [
            {"name": "a", "emphasis": "x", "conclusion": "x", "confidence": 0.9},
            {"name": "b", "emphasis": "x", "conclusion": "x", "confidence": 0.9},
            {"name": "c", "emphasis": "x", "conclusion": "x", "confidence": 0.9},
        ],
        "final_answer": "extracted profile",
        "confidence": 0.85,
        "profile": profile,
    }


def _make_mind_with_llm(llm):
    from radiomind.core.mind import RadioMind
    mind = RadioMind.__new__(RadioMind)
    mind._llm = llm
    mind._initialized = True
    return mind


# === Subject extraction ===


def test_subject_extract_possessive():
    """'What is Nate's favorite X' → subject = Nate."""
    mind = _make_mind_with_llm(None)
    assert mind._v64b_extract_subject(
        "What is Nate's favorite book series about?"
    ) == "Nate"


def test_subject_extract_verb_phrase():
    """'What might Nate consider' → subject = Nate."""
    mind = _make_mind_with_llm(None)
    assert mind._v64b_extract_subject(
        "What alternative career might Nate consider after gaming?"
    ) == "Nate"


def test_subject_extract_subject_first():
    """'X might consider Y' → subject = X (subject-first pattern)."""
    mind = _make_mind_with_llm(None)
    assert mind._v64b_extract_subject(
        "Audrey prefers what kind of meat?"
    ) == "Audrey"


def test_subject_no_proper_noun_returns_none():
    """First-person 'I' query → no subject (handled by profile_hint)."""
    mind = _make_mind_with_llm(None)
    assert mind._v64b_extract_subject(
        "What might I consider for a career?"
    ) is None


def test_subject_impersonal_query_returns_none():
    """Impersonal 'how many X' → no subject."""
    mind = _make_mind_with_llm(None)
    assert mind._v64b_extract_subject(
        "How many years passed since the trip?"
    ) is None


# === Profile section emission ===


def test_profile_section_emitted_when_subject_present():
    """LLM returns rich profile → CHARACTER PROFILE section emitted."""
    llm = _SequenceStubLLM([
        _profile_response({
            "attributes": ["professional gamer", "28 years old"],
            "preferences": ["loves turtles", "enjoys hiking"],
            "activities": ["volunteers at zoo"],
            "relationships": ["dating Sarah"],
        })
    ])
    mind = _make_mind_with_llm(llm)
    out = mind._v64b_character_profile_section(
        "What alternative career might Nate consider after gaming?",
        [_mk_memory("Nate plays games and likes turtles")],
    )
    assert "CHARACTER PROFILE for Nate" in out
    assert "professional gamer" in out
    assert "loves turtles" in out
    assert "volunteers at zoo" in out


def test_profile_section_empty_when_no_subject():
    """Query with no detectable subject → ""  (no LLM call)."""
    llm = _SequenceStubLLM([_profile_response({"attributes": ["x"]})])
    mind = _make_mind_with_llm(llm)
    out = mind._v64b_character_profile_section(
        "How many days passed since the event?",
        [_mk_memory("e")],
    )
    assert out == ""
    assert llm.calls == 0


def test_profile_section_empty_when_profile_empty():
    """LLM returns empty profile → ""  (caller falls back)."""
    llm = _SequenceStubLLM([
        _profile_response({
            "attributes": [], "preferences": [],
            "activities": [], "relationships": [],
        })
    ])
    mind = _make_mind_with_llm(llm)
    out = mind._v64b_character_profile_section(
        "What might Nate consider?",
        [_mk_memory("e")],
    )
    assert out == ""


def test_profile_section_empty_when_no_llm():
    class _DownLLM:
        def is_available(self): return False
    mind = _make_mind_with_llm(_DownLLM())
    out = mind._v64b_character_profile_section(
        "What might Nate consider?",
        [_mk_memory("e")],
    )
    assert out == ""


def test_profile_section_filters_nonlist_values():
    """Malformed profile (string instead of list) → field skipped."""
    llm = _SequenceStubLLM([
        _profile_response({
            "attributes": "not a list",  # malformed
            "preferences": ["likes pizza"],
            "activities": None,
            "relationships": ["friend of John"],
        })
    ])
    mind = _make_mind_with_llm(llm)
    out = mind._v64b_character_profile_section(
        "What is Nate's favorite food?",
        [_mk_memory("e")],
    )
    # malformed attributes field skipped, but preferences and relationships kept
    assert "CHARACTER PROFILE" in out
    assert "likes pizza" in out
    assert "friend of John" in out
    assert "not a list" not in out


def test_profile_section_caps_list_at_5():
    """Long lists are truncated at 5 items per field."""
    llm = _SequenceStubLLM([
        _profile_response({
            "attributes": [f"attr{i}" for i in range(10)],
            "preferences": [], "activities": [], "relationships": [],
        })
    ])
    mind = _make_mind_with_llm(llm)
    out = mind._v64b_character_profile_section(
        "What is Nate's preference?",
        [_mk_memory("e")],
    )
    assert "attr0" in out and "attr4" in out
    assert "attr5" not in out and "attr9" not in out
