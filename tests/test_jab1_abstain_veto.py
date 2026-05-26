"""Unit tests for JAB-1a/b LongMemEval abstain-veto detector.

The veto runs inside the bench runner's judge path and
deterministically flips correct=True → False when the LLM judge
passes an abstain response against a concrete gold. False positives
(wrong veto on a real PASS) are the worst outcome; tests below pin
the canonical shapes both ways.
"""
from __future__ import annotations

import sys
from pathlib import Path

# bench/end_to_end is a sibling of src/; add it for direct import.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bench" / "end_to_end"))

from jab1_abstain_veto import (  # noqa: E402
    has_concrete_commitment,
    is_abstain_gold,
    is_abstain_response,
    should_veto,
)


# ---------- veto FIRES: pure abstain against concrete gold ----------

class TestVetoFires:
    def test_concrete_numeric_gold_pure_abstain(self):
        # c18a7dc8 reproduction (2026-05-26 e2e)
        assert should_veto("7", "The information provided is not enough.")

    def test_concrete_numeric_gold_elaborate_abstain(self):
        # v7d cashback reproduction
        assert should_veto(
            "$0.75",
            "The information provided is not enough to determine "
            "how much cashback you earned",
        )

    def test_concrete_count_gold_pure_abstain(self):
        # b46e15ed reproduction (v82-1 baseline)
        assert should_veto("2", "The information provided is not enough.")

    def test_concrete_decimal_gold_pure_abstain(self):
        # d12ceb0e reproduction (v6.1.1 baseline)
        assert should_veto("59.6", "The information provided is not enough.")

    def test_concrete_currency_gold_pure_abstain(self):
        assert should_veto("$300", "The information provided is not enough.")

    def test_concrete_entity_gold_pure_abstain(self):
        # v3 baseline: 86f00804
        assert should_veto(
            "The Seven Husbands of Evelyn Hugo",
            "The information provided is not enough.",
        )

    def test_text_gold_pure_abstain(self):
        # v6 cousin's wedding reproduction
        assert should_veto(
            "my cousin's wedding",
            "The information provided is not enough.",
        )

    def test_idont_have_information_form(self):
        # v7d reproduction (different canonical phrase)
        assert should_veto(
            "The Seven Husbands of Evelyn Hugo",
            "I don't have information on what book you're currently reading.",
        )


# ---------- veto SKIPS: abstain gold ----------

class TestAbstainGoldSkipsVeto:
    def test_you_did_not_mention_gold(self):
        # 29f2956b_abs reproduction
        assert not should_veto(
            "You did not mention this information. You mentioned practing",
            "The information provided is not enough.",
        )

    def test_you_havent_started_gold(self):
        # gpt4_93159ced_abs gold
        assert not should_veto(
            "You haven't started working at Google yet.",
            "The information provided is not enough.",
        )

    def test_canonical_not_enough_gold(self):
        assert not should_veto(
            "The information provided is not enough",
            "The information provided is not enough.",
        )

    def test_cannot_be_determined_gold(self):
        assert not should_veto(
            "Cannot be determined from the conversation.",
            "I don't have enough information to answer.",
        )


# ---------- veto SKIPS: concrete commitment present ----------

class TestConcreteCommitmentSkipsVeto:
    def test_committed_currency_with_hedge(self):
        # Codex P1 example: real answer followed by uncertainty caveat
        # gold=$0.75, response commits to $0.75 then hedges
        assert not should_veto(
            "$0.75",
            "$0.75. Not enough info to determine why this was applied.",
        )

    def test_committed_number_with_meta_quote(self):
        # Codex P2 example: response contains "not enough information"
        # as a quote/reference but commits to a real answer
        assert not should_veto(
            "7",
            'Although the phrase "not enough information" might '
            "apply in some readings, the answer is 7.",
        )

    def test_committed_year_with_abstain_phrase(self):
        # Year mention counts as concrete; response is mixed
        assert not should_veto(
            "2023",
            "I think 2023, although I don't have information on the "
            "exact date.",
        )

    def test_committed_count_with_unit(self):
        # "4 instruments" is a clear count commitment even when
        # surrounded by abstain language
        assert not should_veto(
            "4",
            "Cannot be determined exactly, but I count 4 instruments "
            "in the records.",
        )

    def test_committed_duration_with_unit(self):
        assert not should_veto(
            "4 years and 9 months",
            "4 years and 9 months. The information provided is not "
            "enough to give a more precise figure.",
        )

    def test_committed_dollar_amount_no_decimal(self):
        assert not should_veto(
            "$300",
            "$300. Not enough information to break it down further.",
        )


# ---------- veto SKIPS: regular correct answers ----------

class TestRegularPassesSkipsVeto:
    def test_exact_match(self):
        assert not should_veto("7", "7")

    def test_concrete_prose(self):
        assert not should_veto(
            "7",
            "The user is 7 years older than when they graduated.",
        )

    def test_currency_pass(self):
        assert not should_veto("$0.75", "You earned $0.75 cashback.")

    def test_duration_pass(self):
        assert not should_veto(
            "4 years and 9 months",
            "You have been working for 4 years and 9 months.",
        )

    def test_empty_answer(self):
        # Empty answer is not a canonical abstain (and shouldn't reach
        # the judge in practice anyway).
        assert not should_veto("7", "")


# ---------- detector primitives ----------

class TestDetectorPrimitives:
    def test_is_abstain_gold_canonical(self):
        assert is_abstain_gold("The information provided is not enough.")
        assert is_abstain_gold(
            "You did not mention this information. You mentioned ..."
        )
        assert is_abstain_gold("You haven't started working at Google yet.")
        assert is_abstain_gold("No record of that in the conversation.")

    def test_is_abstain_gold_concrete(self):
        assert not is_abstain_gold("7")
        assert not is_abstain_gold("$0.75")
        assert not is_abstain_gold("4 years and 9 months")

    def test_has_concrete_commitment_positive(self):
        assert has_concrete_commitment("$0.75")
        assert has_concrete_commitment("the answer is 4 instruments")
        assert has_concrete_commitment("2023")
        assert has_concrete_commitment("7 years")
        assert has_concrete_commitment("50%")

    def test_has_concrete_commitment_negative(self):
        assert not has_concrete_commitment(
            "The information provided is not enough."
        )
        assert not has_concrete_commitment(
            "I don't know the answer to that question."
        )

    def test_is_abstain_response_pure(self):
        assert is_abstain_response("The information provided is not enough.")
        assert is_abstain_response("I don't have enough information.")
        assert is_abstain_response("Cannot be determined.")

    def test_is_abstain_response_mixed(self):
        # Hybrid responses must NOT be classified as pure abstain.
        assert not is_abstain_response(
            "$0.75. Not enough info to determine why."
        )
        assert not is_abstain_response(
            "7 years; the information provided is not enough to add "
            "more precision."
        )
