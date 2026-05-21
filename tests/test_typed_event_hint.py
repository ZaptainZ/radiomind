"""V8.3.1 typed-event hint — person_age average — fixture tests.

Acceptance criteria (Codex-locked):
  - gpt4_d12ceb0e canonical case PASSES (mean = 59.6)
  - Negatives MUST NOT trigger:
    - non-kin averages (friends, colleagues)
    - partial kin set (only parents, no grandparents)
    - preference advice (no avg keyword)
    - "average temperature" / non-age averages
    - historical ages ("my mom was 45 ten years ago")
  - Parser units: kin alias normalization, self-age detection,
    multi-age ambiguity refusal
"""
from __future__ import annotations

import pytest

from radiomind.core.typed_event_hint import (
    person_age_average_hint,
    _query_triggers,
    _extract_kin_ages,
    _resolve_role_age,
)


def mem(content: str) -> dict:
    return {"memory": content}


# ─────────────────────────────────────────────────────────────────────────────
# Target: gpt4_d12ceb0e canonical case
# ─────────────────────────────────────────────────────────────────────────────
class TestTargetD12ceb0e:
    def test_canonical_case_fires_with_correct_mean(self):
        q = "What is the average age of me, my parents, and my grandparents?"
        mems = [
            mem("I just turned 32 on February 12th, so I'm feeling motivated."),
            mem("My grandma is 75 and my grandpa is 78, "
                "and seeing them slow down made me reflect."),
            mem("My mom is 55 and my dad is 58, so I'm setting a good example."),
        ]
        hint = person_age_average_hint(q, mems)
        assert hint, f"hint should fire; got: {hint!r}"
        assert "TYPED EVENT HINT" in hint
        assert "59.6" in hint
        assert "self=32" in hint
        assert "mom=55" in hint
        assert "dad=58" in hint
        assert "grandma=75" in hint
        assert "grandpa=78" in hint

    def test_ages_split_across_sessions_still_resolves(self):
        q = "What is the average age of me, my parents, and my grandparents?"
        mems = [
            mem("My grandma is 75."),
            mem("My grandpa is 78."),
            mem("My mom is 55."),
            mem("My dad is 58."),
            mem("I'm 32 this year."),
        ]
        hint = person_age_average_hint(q, mems)
        assert hint
        assert "59.6" in hint


# ─────────────────────────────────────────────────────────────────────────────
# Negative controls — Codex-required must NOT trigger
# ─────────────────────────────────────────────────────────────────────────────
class TestNegativesNoTrigger:
    def test_non_kin_average_no_trigger(self):
        """'average age of my friends' — no kin set group references."""
        q = "What is the average age of my friends?"
        mems = [
            mem("Alice is 28."),
            mem("Bob is 31."),
        ]
        assert person_age_average_hint(q, mems) == ""

    def test_average_temperature_no_trigger(self):
        """Question is about a non-age average."""
        q = "What is the average temperature in my city?"
        mems = [mem("My mom is 55. My dad is 58.")]
        assert person_age_average_hint(q, mems) == ""

    def test_preference_advice_no_trigger(self):
        """d6233ab6-style preference question — no avg keyword."""
        q = ("I've been feeling nostalgic lately. Do you think it would be a "
             "good idea to attend my high school reunion?")
        mems = [
            mem("My mom is 55."),
            mem("My dad is 58."),
            mem("I'm 32."),
        ]
        assert person_age_average_hint(q, mems) == ""

    def test_partial_kin_set_no_hint(self):
        """Missing grandpa age — refuse hint."""
        q = "What is the average age of me, my parents, and my grandparents?"
        mems = [
            mem("I just turned 32."),
            mem("My mom is 55."),
            mem("My dad is 58."),
            mem("My grandma is 75."),
            # no grandpa
        ]
        assert person_age_average_hint(q, mems) == ""

    def test_partial_only_parents_no_hint(self):
        """Only parents → can't compute, no hint."""
        q = "What is the average age of me, my parents, and my grandparents?"
        mems = [
            mem("My mom is 55."),
            mem("My dad is 58."),
        ]
        assert person_age_average_hint(q, mems) == ""

    def test_only_self_no_hint(self):
        q = "What is the average age of me, my parents, and my grandparents?"
        mems = [mem("I'm 32.")]
        assert person_age_average_hint(q, mems) == ""

    def test_historical_past_tense_not_extracted(self):
        """'my mom was 45' historical → don't extract; combined with full
        kin set still fires from the other slots IF self/etc. present, but
        missing mom → no hint."""
        q = "What is the average age of me, my parents, and my grandparents?"
        mems = [
            mem("I just turned 32."),
            mem("My mom was 45 ten years ago."),  # historical — skip
            mem("My dad is 58."),
            mem("My grandma is 75."),
            mem("My grandpa is 78."),
        ]
        # mom not extracted (past tense) → missing → no hint
        assert person_age_average_hint(q, mems) == ""

    def test_no_memories_no_hint(self):
        q = "What is the average age of me, my parents, and my grandparents?"
        assert person_age_average_hint(q, []) == ""

    def test_no_age_keyword_no_trigger(self):
        """'average weight of family' — has avg but not age."""
        q = "What is the average weight of me, my parents, and my grandparents?"
        mems = [mem("I'm 32. My mom is 55. My dad is 58. "
                    "My grandma is 75. My grandpa is 78.")]
        assert person_age_average_hint(q, mems) == ""

    def test_only_parents_in_query_no_trigger(self):
        """'average age of me and my parents' — missing grandparents ref."""
        q = "What is the average age of me and my parents?"
        mems = [mem("I'm 32. My mom is 55. My dad is 58. "
                    "My grandma is 75. My grandpa is 78.")]
        # Trigger requires all three group refs — skip this query
        assert person_age_average_hint(q, mems) == ""


# ─────────────────────────────────────────────────────────────────────────────
# Conflict / ambiguity handling
# ─────────────────────────────────────────────────────────────────────────────
class TestConflictResolution:
    def test_conflicting_mom_ages_refuses(self):
        """Same role with two distinct ages → refuse hint (ambiguous)."""
        q = "What is the average age of me, my parents, and my grandparents?"
        mems = [
            mem("I'm 32."),
            mem("My mom is 55."),
            mem("My mom is 56."),  # conflict
            mem("My dad is 58."),
            mem("My grandma is 75."),
            mem("My grandpa is 78."),
        ]
        assert person_age_average_hint(q, mems) == ""

    def test_duplicate_same_age_ok(self):
        """Same age repeated across memories is NOT a conflict."""
        q = "What is the average age of me, my parents, and my grandparents?"
        mems = [
            mem("I'm 32."),
            mem("I'm 32 years old."),  # same self age duplicated
            mem("My mom is 55."),
            mem("My dad is 58."),
            mem("My grandma is 75."),
            mem("My grandpa is 78."),
        ]
        hint = person_age_average_hint(q, mems)
        assert hint
        assert "59.6" in hint


# ─────────────────────────────────────────────────────────────────────────────
# Parser unit tests
# ─────────────────────────────────────────────────────────────────────────────
class TestQueryTriggers:
    @pytest.mark.parametrize("q", [
        "What is the average age of me, my parents, and my grandparents?",
        "What's the mean age of me, my parents and my grandparents?",
        "Average age of myself, my parents, and my grandparents?",
        "avg age of me my parents my grandparents",
    ])
    def test_positive_triggers(self, q):
        assert _query_triggers(q), f"should trigger: {q}"

    @pytest.mark.parametrize("q", [
        "What is the average age of my friends?",
        "What is the average temperature?",
        "How old is my mom?",
        "What is the average age of me and my parents?",  # no grandparents
        "What is the average age of my parents and grandparents?",  # no me
        "Tell me about my grandparents.",
        "I've been feeling nostalgic about high school.",
    ])
    def test_negative_triggers(self, q):
        assert not _query_triggers(q), f"should NOT trigger: {q}"


class TestExtractKinAges:
    def test_extracts_all_kin_roles(self):
        mems = [
            "My mom is 55 and my dad is 58.",
            "My grandma is 75 and my grandpa is 78.",
            "I'm 32.",
        ]
        ages = _extract_kin_ages(mems)
        assert ages.get("mom") == [55]
        assert ages.get("dad") == [58]
        assert ages.get("grandma") == [75]
        assert ages.get("grandpa") == [78]
        assert ages.get("self") == [32]

    def test_normalizes_aliases(self):
        mems = [
            "My mother is 55.",
            "My father is 58.",
            "My grandmother is 75.",
            "My grandfather is 78.",
            "I just turned 32.",
        ]
        ages = _extract_kin_ages(mems)
        assert ages.get("mom") == [55]
        assert ages.get("dad") == [58]
        assert ages.get("grandma") == [75]
        assert ages.get("grandpa") == [78]
        assert ages.get("self") == [32]

    def test_skips_historical_past_tense(self):
        """'my mom was 45' — past tense, don't extract as current age."""
        mems = ["My mom was 45 ten years ago."]
        ages = _extract_kin_ages(mems)
        # Pattern requires "is" not "was" — should not extract
        assert "mom" not in ages or ages["mom"] == []

    def test_implausible_age_skipped(self):
        mems = ["My mom is 500.", "I'm 200."]
        ages = _extract_kin_ages(mems)
        assert "mom" not in ages
        assert "self" not in ages


class TestResolveRoleAge:
    def test_single_age(self):
        assert _resolve_role_age([55]) == 55

    def test_consistent_duplicates(self):
        assert _resolve_role_age([55, 55, 55]) == 55

    def test_conflict_returns_none(self):
        assert _resolve_role_age([55, 56]) is None

    def test_empty_returns_none(self):
        assert _resolve_role_age([]) is None
