"""TSI-1c unit tests — age_interval commit closure.

Six gates must all hold for rewrite:
  1. STRUCTURED SKILL block names age_interval
  2. confidence >= 0.85
  3. computed answer is numeric
  4. age-at-event backing evidence present
  5. current-age backing evidence present
  6. LLM final answer is pure canonical-abstain

Any gate failure → llm_answer unchanged.
"""
from __future__ import annotations

from radiomind.core.age_interval_commit import (
    _has_age_at_event_evidence,
    _has_current_age_evidence,
    _is_pure_abstain,
    maybe_age_interval_commit_closure,
    parse_temporal_section,
)


# Real LongMemEval c18a7dc8 backing evidence (verified by AAS-2 probe)
GOOD_MEMORIES = [
    {"memory": "[user] I have a Bachelor's degree in Business "
               "Administration with a concentration in Marketing "
               "from the University of California, Berkeley, which "
               "I completed at the age of 25."},
    {"memory": "[user] As a 32-year-old Digital Marketing Specialist, "
               "I'm always looking for new learning resources."},
]

TEMPORAL_SECTION_GOOD = (
    "STRUCTURED SKILL (age_interval, conf=0.90): trust this unless "
    "retrieval explicitly contradicts.\n"
    "- graduated from college → 2023-05-26\n"
    "- current age (store self-ID) → 32\n"
    "Computed answer: 7\n\n"
)

ABSTAIN_ANSWER = "The information provided is not enough."

C18_QUESTION = "How many years older am I than when I graduated from college?"


# ---------- parser ----------

class TestParseTemporalSection:
    def test_parse_good(self):
        name, conf, ans = parse_temporal_section(TEMPORAL_SECTION_GOOD)
        assert name == "age_interval"
        assert conf == 0.9
        assert ans == "7"

    def test_parse_empty(self):
        assert parse_temporal_section("") == (None, None, None)

    def test_parse_no_structured_skill(self):
        assert parse_temporal_section("ATTENTION-ROUTED TRINITY ...") == (
            None, None, None,
        )

    def test_parse_other_skill(self):
        section = (
            "STRUCTURED SKILL (temporal, conf=0.70): ...\n"
            "Computed answer: 2023-05-26\n"
        )
        name, conf, ans = parse_temporal_section(section)
        assert name == "temporal"
        assert conf == 0.7


# ---------- backing evidence detectors ----------

class TestBackingEvidence:
    def test_age_at_event_present(self):
        assert _has_age_at_event_evidence(GOOD_MEMORIES)

    def test_age_at_event_absent(self):
        assert not _has_age_at_event_evidence([
            {"memory": "[user] I love hiking on weekends."},
        ])

    def test_when_i_was_form(self):
        assert _has_age_at_event_evidence([
            {"memory": "[user] When I was 22 I moved to Berlin."},
        ])

    def test_aged_form(self):
        assert _has_age_at_event_evidence([
            {"memory": "[user] I joined the army aged 18."},
        ])

    def test_current_age_self_id(self):
        assert _has_current_age_evidence(GOOD_MEMORIES)

    def test_current_age_im_form(self):
        assert _has_current_age_evidence([
            {"memory": "[user] I'm 32 years old."},
        ])

    def test_current_age_absent(self):
        assert not _has_current_age_evidence([
            {"memory": "[user] I love hiking."},
        ])


# ---------- pure-abstain detector ----------

class TestPureAbstain:
    def test_canonical_abstain(self):
        assert _is_pure_abstain("The information provided is not enough.")

    def test_idont_have_info(self):
        assert _is_pure_abstain("I don't have enough information.")

    def test_concrete_committed_not_abstain(self):
        assert not _is_pure_abstain("7 years")

    def test_hybrid_not_abstain(self):
        # Concrete commitment present → NOT pure abstain
        assert not _is_pure_abstain(
            "$0.75. Not enough info to determine why."
        )

    def test_empty(self):
        assert not _is_pure_abstain("")


# ---------- rewrite FIRES (all gates) ----------

class TestRewriteFires:
    def test_c18a7dc8_canonical_case(self):
        out = maybe_age_interval_commit_closure(
            C18_QUESTION,
            GOOD_MEMORIES,
            ABSTAIN_ANSWER,
            TEMPORAL_SECTION_GOOD,
        )
        # Rewrite expected → contains the skill number and unit
        assert out != ABSTAIN_ANSWER
        assert "7" in out
        assert "years" in out

    def test_unit_extracted_from_question(self):
        # "how many months" → unit "months"
        section = (
            "STRUCTURED SKILL (age_interval, conf=0.95): ...\n"
            "Computed answer: 6\n"
        )
        out = maybe_age_interval_commit_closure(
            "How many months since I started college?",
            [
                {"memory": "[user] I started college at the age of 19."},
                {"memory": "[user] I'm 19 now."},
            ],
            "The information provided is not enough.",
            section,
        )
        assert "6 months" in out


# ---------- rewrite SKIPS (gates fail) ----------

class TestRewriteSkips:
    def test_skip_when_other_skill(self):
        section = (
            "STRUCTURED SKILL (temporal, conf=0.90): ...\n"
            "Computed answer: 7\n"
        )
        out = maybe_age_interval_commit_closure(
            C18_QUESTION, GOOD_MEMORIES, ABSTAIN_ANSWER, section,
        )
        assert out == ABSTAIN_ANSWER

    def test_skip_when_low_confidence(self):
        section = (
            "STRUCTURED SKILL (age_interval, conf=0.50): ...\n"
            "Computed answer: 7\n"
        )
        out = maybe_age_interval_commit_closure(
            C18_QUESTION, GOOD_MEMORIES, ABSTAIN_ANSWER, section,
        )
        assert out == ABSTAIN_ANSWER

    def test_skip_when_non_numeric_answer(self):
        section = (
            "STRUCTURED SKILL (age_interval, conf=0.90): ...\n"
            "Computed answer: abstain\n"
        )
        out = maybe_age_interval_commit_closure(
            C18_QUESTION, GOOD_MEMORIES, ABSTAIN_ANSWER, section,
        )
        assert out == ABSTAIN_ANSWER

    def test_skip_when_no_age_at_event(self):
        # Has current-age but no "at the age of N"
        memories_no_age_at = [
            {"memory": "[user] As a 32-year-old marketer ..."},
            {"memory": "[user] I graduated from Berkeley."},
        ]
        out = maybe_age_interval_commit_closure(
            C18_QUESTION,
            memories_no_age_at,
            ABSTAIN_ANSWER,
            TEMPORAL_SECTION_GOOD,
        )
        assert out == ABSTAIN_ANSWER

    def test_skip_when_no_current_age(self):
        # Has age-at-event but no current-age self-id
        memories_no_current = [
            {"memory": "[user] I completed my Bachelor's at the age "
                       "of 25."},
            {"memory": "[user] Random unrelated turn."},
        ]
        out = maybe_age_interval_commit_closure(
            C18_QUESTION,
            memories_no_current,
            ABSTAIN_ANSWER,
            TEMPORAL_SECTION_GOOD,
        )
        assert out == ABSTAIN_ANSWER

    def test_skip_when_llm_already_committed(self):
        # LLM gave a concrete answer; no rewrite
        out = maybe_age_interval_commit_closure(
            C18_QUESTION,
            GOOD_MEMORIES,
            "7 years older.",
            TEMPORAL_SECTION_GOOD,
        )
        assert out == "7 years older."

    def test_skip_when_llm_hybrid(self):
        # LLM committed something concrete + hedged with abstain phrase
        # → pure-abstain detector rejects → no rewrite
        out = maybe_age_interval_commit_closure(
            C18_QUESTION,
            GOOD_MEMORIES,
            "$0.75. Not enough info to break it down further.",
            TEMPORAL_SECTION_GOOD,
        )
        assert "$0.75" in out  # unchanged

    def test_skip_when_no_temporal_section(self):
        out = maybe_age_interval_commit_closure(
            C18_QUESTION, GOOD_MEMORIES, ABSTAIN_ANSWER, "",
        )
        assert out == ABSTAIN_ANSWER

    def test_skip_when_empty_memories(self):
        out = maybe_age_interval_commit_closure(
            C18_QUESTION, [], ABSTAIN_ANSWER, TEMPORAL_SECTION_GOOD,
        )
        assert out == ABSTAIN_ANSWER
