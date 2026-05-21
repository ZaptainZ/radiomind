"""Fixture tests for V8.2.2a role/title mismatch guard.

Per-case validation that:
  1. The guard fires when question role is leadership and memories only support IC roles
     (or vice-versa) — primary target case `031748ae_abs`
  2. The guard does NOT fire when question role matches memory role exactly or
     via normalization (Senior X / X / Principal X all match same role)
  3. The guard does NOT fire when the question has no role phrase
  4. The guard does NOT fire when no memories provided
"""
from __future__ import annotations

import pytest

from radiomind.core.role_mismatch_guard import (
    role_mismatch_guard,
    extract_role_phrases,
    _classify_track,
    _normalize_role,
    detect_role_mismatch,
    maybe_rewrite_with_guard,
)


def mem(content: str) -> dict:
    return {"memory": content}


# ─────────────────────────────────────────────────────────────────────────────
# Primary target: 031748ae_abs case
# ─────────────────────────────────────────────────────────────────────────────
class TestSoftwareEngineerManagerVsSenior:
    """Question role 'Software Engineer Manager' vs memory 'Senior Software Engineer'."""

    def test_guard_fires_on_role_mismatch(self):
        q = "How many engineers do I lead when I just started my new role as Software Engineer Manager?"
        mems = [
            mem("I'm starting as a Senior Software Engineer at the new company next month."),
            mem("My new team will have 5 engineers reporting to me."),
            mem("Just got the offer from Acme Corp — Senior Software Engineer position!"),
        ]
        guard = role_mismatch_guard(q, mems)
        assert guard, "guard should fire — Senior Engineer ≠ Engineer Manager"
        assert "ROLE" in guard.upper()
        assert "Software Engineer Manager" in guard
        assert "abstain" in guard.lower() or "not enough" in guard.lower()


# ─────────────────────────────────────────────────────────────────────────────
# Negative controls — guard must NOT fire
# ─────────────────────────────────────────────────────────────────────────────
class TestNoMismatchNoGuard:
    def test_question_role_matches_memory_role(self):
        q = "How many engineers report to me as Senior Software Engineer?"
        mems = [
            mem("I'm a Senior Software Engineer at Acme. Lead a team of 3."),
        ]
        guard = role_mismatch_guard(q, mems)
        assert not guard, f"guard should NOT fire on match; got: {guard[:200]}"

    def test_question_role_matches_via_normalization(self):
        q = "What is my Software Engineer team size?"
        mems = [
            mem("As a Senior Software Engineer, I lead 5 people."),
        ]
        # Normalize "Software Engineer" == "Senior Software Engineer" → ok, same role
        guard = role_mismatch_guard(q, mems)
        assert not guard, f"normalization should match; got: {guard[:200]}"

    def test_no_role_in_question(self):
        q = "What did I eat for breakfast yesterday?"
        mems = [mem("Yesterday I had pancakes.")]
        assert role_mismatch_guard(q, mems) == ""

    def test_no_memories(self):
        q = "What is my Software Engineer Manager team size?"
        assert role_mismatch_guard(q, []) == ""

    def test_no_role_in_memories(self):
        q = "What is my Software Engineer Manager team size?"
        mems = [mem("I bought groceries last weekend.")]
        # No role in memories — can't make a strong mismatch claim
        assert role_mismatch_guard(q, mems) == ""


# ─────────────────────────────────────────────────────────────────────────────
# Same-track distinctions: don't over-fire
# ─────────────────────────────────────────────────────────────────────────────
class TestSameTrackNoFalsePositive:
    def test_data_engineer_vs_data_scientist(self):
        """Both IC track — even though different roles, V8.2.2a doesn't fire
        (same-track conflict is less reliable; not part of this version's scope)."""
        q = "Who is my Data Engineer colleague?"
        mems = [mem("Alice is our Data Scientist on the analytics team.")]
        guard = role_mismatch_guard(q, mems)
        # V8.2.2a only catches cross-track (IC vs leadership), not within-track
        assert guard == "", f"within-track should not trigger; got: {guard[:200]}"


# ─────────────────────────────────────────────────────────────────────────────
# Reverse direction: IC question, leadership memory
# ─────────────────────────────────────────────────────────────────────────────
class TestReverseDirection:
    def test_ic_question_leadership_memory(self):
        q = "What is my workload as Software Engineer?"
        mems = [mem("As Engineering Manager, I oversee 12 engineers across 3 teams.")]
        guard = role_mismatch_guard(q, mems)
        assert guard, "reverse direction should also fire"
        assert "Engineering Manager" in guard or "engineering manager" in guard.lower()


# ─────────────────────────────────────────────────────────────────────────────
# Utility function tests
# ─────────────────────────────────────────────────────────────────────────────
class TestExtractRolePhrases:
    def test_senior_software_engineer(self):
        phrases = extract_role_phrases("Hi, I'm a Senior Software Engineer at Acme.")
        assert any("Senior Software Engineer" in p for p in phrases)

    def test_software_engineer_manager(self):
        phrases = extract_role_phrases(
            "What is my role as Software Engineer Manager going to be?"
        )
        assert any("Software Engineer Manager" in p or "Engineer Manager" in p
                   for p in phrases)

    def test_vp_of_engineering(self):
        phrases = extract_role_phrases("I just got promoted to VP of Engineering.")
        # VP of Engineering or Engineering captured somewhere
        assert phrases, f"got: {phrases}"

    def test_no_role(self):
        phrases = extract_role_phrases("I had coffee this morning.")
        assert phrases == []


class TestClassifyTrack:
    def test_leadership(self):
        assert _classify_track("Engineering Manager") == "leadership"
        assert _classify_track("Software Engineer Manager") == "leadership"
        assert _classify_track("VP Engineering") == "leadership"

    def test_ic(self):
        assert _classify_track("Senior Software Engineer") == "ic"
        assert _classify_track("Data Scientist") == "ic"

    def test_unknown(self):
        assert _classify_track("CEO") in ("leadership", "unknown")  # CEO catches via _LEADERSHIP_KEYWORDS


class TestNormalizeRole:
    def test_strips_seniority(self):
        assert _normalize_role("Senior Software Engineer") == "software engineer"
        assert _normalize_role("Junior Data Scientist") == "data scientist"
        assert _normalize_role("Principal Engineer") == "engineer"

    def test_strips_of(self):
        assert _normalize_role("VP of Engineering") == "vp engineering"

    def test_case_insensitive(self):
        assert _normalize_role("SOFTWARE ENGINEER") == "software engineer"


# ─────────────────────────────────────────────────────────────────────────────
# V8.2.2b: post-rewrite tests
# ─────────────────────────────────────────────────────────────────────────────
class TestPostRewriteCanonicalAbstain:
    """Verify maybe_rewrite_with_guard converts over-committed LLM answers
    to canonical abstain when role mismatch detected."""

    def test_rewrites_when_guard_fires_and_overcommitted(self):
        q = "How many engineers do I lead when I just started my new role as Software Engineer Manager?"
        mems = [
            mem("Just got the offer — Senior Software Engineer."),
            mem("I lead a team of five engineers as Senior Software Engineer."),
        ]
        llm_answer = "Based on the evidence, you lead a team of five engineers in your role as Senior Software Engineer."
        rewritten = maybe_rewrite_with_guard(q, mems, llm_answer)
        assert "not enough" in rewritten.lower()
        assert "Software Engineer Manager" in rewritten
        assert "Senior Software Engineer" in rewritten
        # Should NOT contain the team size anymore
        assert "five" not in rewritten.lower()

    def test_keeps_when_no_overcommit(self):
        q = "How many engineers do I lead when I just started my new role as Software Engineer Manager?"
        mems = [mem("I am a Senior Software Engineer.")]
        llm_answer = "The information provided is not enough."
        rewritten = maybe_rewrite_with_guard(q, mems, llm_answer)
        # Already abstain — no change
        assert rewritten == llm_answer

    def test_keeps_when_no_mismatch(self):
        q = "How many engineers do I lead as Senior Software Engineer?"
        mems = [mem("I'm a Senior Software Engineer with 5 reports.")]
        llm_answer = "You lead a team of 5 engineers."
        rewritten = maybe_rewrite_with_guard(q, mems, llm_answer)
        # No role mismatch — keep
        assert rewritten == llm_answer

    def test_rewrites_dollar_amount_overcommit(self):
        q = "How much budget do I control as VP of Sales?"
        mems = [mem("As Senior Sales Engineer I track $500,000 quarterly.")]
        llm_answer = "Based on memories, you control $500,000."
        rewritten = maybe_rewrite_with_guard(q, mems, llm_answer)
        assert "not enough" in rewritten.lower() or rewritten != llm_answer

    def test_no_role_in_question_no_change(self):
        q = "What did I eat for breakfast?"
        mems = [mem("Senior Software Engineer made pancakes.")]
        llm_answer = "You ate 3 pancakes."
        # No role in question → no guard → no rewrite
        assert maybe_rewrite_with_guard(q, mems, llm_answer) == llm_answer


class TestDetectRoleMismatch:
    def test_returns_none_when_no_mismatch(self):
        q = "How many engineers report to me as Senior Software Engineer?"
        mems = [mem("Senior Software Engineer with team of 3.")]
        assert detect_role_mismatch(q, mems) is None

    def test_returns_dict_when_mismatch(self):
        q = "What is my Software Engineer Manager team size?"
        mems = [mem("Senior Software Engineer here.")]
        d = detect_role_mismatch(q, mems)
        assert d is not None
        assert "Software Engineer Manager" in d["q_role"]
        assert d["q_track"] == "leadership"
