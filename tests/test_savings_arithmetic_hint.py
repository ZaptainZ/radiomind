"""Unit tests for SavingsHint-1b (savings_arithmetic_hint).

Strict gate (Codex 2026-05-28):
  - trigger: `how much (did|do|have|can) I sav[e/ed] on/for [item]?`
  - exactly 1 paid + 1 retail amount with same-item anchor
  - retail ≥ paid (no impossible savings)
  - hint-only, never forces commit
  - NO synonym, NO LLM, NO coupon/discount, NO direct "saved $X"
"""
from __future__ import annotations

from radiomind.core.arithmetic_hint import savings_arithmetic_hint


# Real LongMemEval bb7c3b45 evidence pulled from haystack.
BB7C3B45_Q = "How much did I save on the Jimmy Choo heels?"
BB7C3B45_MEMS = [
    {"memory": "[user] I'm planning a night out with friends this "
               "weekend and I need some fashion advice. I was thinking "
               "of wearing my new Jimmy Choo heels that I got at the "
               "outlet mall for $200 - do you have any outfit "
               "suggestions that would complement them well?"},
    {"memory": "[user] I'm looking for some advice on affordable "
               "fashion brands that offer high-quality clothing. "
               "By the way, I've noticed that some designer brands "
               "can be really pricey, like Jimmy Choo heels, which "
               "I know originally retailed for $500."},
]


# ---------- target FIRES ----------

class TestHintFires:
    def test_bb7c3b45_target(self):
        hint = savings_arithmetic_hint(BB7C3B45_Q, BB7C3B45_MEMS)
        assert hint != ""
        # Arithmetic check
        assert "$200" in hint
        assert "$500" in hint
        assert "$300" in hint
        assert "jimmy choo heels" in hint.lower()

    def test_msrp_form_fires(self):
        # Variant retail anchor: "MSRP $500"
        mems = [
            {"memory": "[user] I got the Acme Pro guitar for $350."},
            {"memory": "[user] The Acme Pro guitar has an MSRP of $500."},
        ]
        hint = savings_arithmetic_hint(
            "How much did I save on the Acme Pro guitar?", mems,
        )
        assert hint != ""
        assert "$150" in hint

    def test_paid_before_for_phrasing(self):
        # "paid $200 for X"
        mems = [
            {"memory": "[user] I paid $200 for the leather jacket "
                       "last week."},
            {"memory": "[user] The leather jacket originally retailed "
                       "for $400 at the boutique."},
        ]
        hint = savings_arithmetic_hint(
            "How much did I save on the leather jacket?", mems,
        )
        assert hint != ""
        assert "$200" in hint


# ---------- audit-conservative SKIPS ----------

class TestHintSkips:
    def test_e25c3b8d_proximity_rejection(self):
        # e25c3b8d: paid found, retail in same gold session BUT
        # separated by 200+ chars + multiple sentences from the
        # item mention. Strict 80-char window rejects.
        mems = [
            {"memory": "[user] I'm looking for some fashion advice. "
                       "I recently got a designer handbag and I want "
                       "to style it with some new outfits. Do you "
                       "have any tips on what kind of clothes would "
                       "complement it well? By the way, I got a "
                       "fantastic deal on the bag - it was "
                       "originally $500!"},
            {"memory": "[user] I've had luck finding great deals at "
                       "TK Maxx before, like that designer handbag "
                       "I got for $200. I might have to check out "
                       "their formal dress section."},
        ]
        # The strict gate rejects: retail anchor doesn't have
        # "designer handbag" within 80 chars of "originally $500"
        hint = savings_arithmetic_hint(
            "How much did I save on the designer handbag at TK Maxx?",
            mems,
        )
        assert hint == ""

    def test_no_retail_anchor_no_hint(self):
        # Paid present, retail absent
        mems = [
            {"memory": "[user] I got the leather jacket for $200."},
        ]
        hint = savings_arithmetic_hint(
            "How much did I save on the leather jacket?", mems,
        )
        assert hint == ""

    def test_no_paid_anchor_no_hint(self):
        mems = [
            {"memory": "[user] The leather jacket originally cost $400."},
        ]
        hint = savings_arithmetic_hint(
            "How much did I save on the leather jacket?", mems,
        )
        assert hint == ""

    def test_two_paid_amounts_rejected(self):
        # Two paid amounts for same item → reject. Both turns use
        # phrasings the regex catches: "bought the X for $N" and
        # "got the X for $M".
        mems = [
            {"memory": "[user] I bought the leather jacket for $200."},
            {"memory": "[user] I got the leather jacket for $250 "
                       "from another store later."},
            {"memory": "[user] The leather jacket originally cost $400."},
        ]
        hint = savings_arithmetic_hint(
            "How much did I save on the leather jacket?", mems,
        )
        assert hint == ""

    def test_two_retail_amounts_rejected(self):
        mems = [
            {"memory": "[user] I got the leather jacket for $200."},
            {"memory": "[user] The leather jacket originally retailed "
                       "for $400."},
            {"memory": "[user] The leather jacket original price was "
                       "$450."},
        ]
        hint = savings_arithmetic_hint(
            "How much did I save on the leather jacket?", mems,
        )
        assert hint == ""

    def test_retail_less_than_paid_rejected(self):
        # Impossible savings: retail < paid
        mems = [
            {"memory": "[user] I got the leather jacket for $500."},
            {"memory": "[user] The leather jacket originally retailed "
                       "for $300."},
        ]
        hint = savings_arithmetic_hint(
            "How much did I save on the leather jacket?", mems,
        )
        assert hint == ""

    def test_single_token_item_rejected(self):
        # Item phrase only one token → no anchor emitted
        mems = [
            {"memory": "[user] I got it for $100."},
            {"memory": "[user] It originally retailed for $200."},
        ]
        hint = savings_arithmetic_hint(
            "How much did I save on it?", mems,
        )
        assert hint == ""


# ---------- trigger NEGATIVES ----------

class TestTriggerNegatives:
    def test_save_for_trip_no_trigger(self):
        # "save for trip" — no item, no $ anchors expected
        mems = [{"memory": "[user] I'm planning a trip to Paris."}]
        hint = savings_arithmetic_hint(
            "How much did I save for my Paris trip?", mems,
        )
        assert hint == ""

    def test_save_money_general_no_trigger(self):
        # "how to save money" — generic, no item
        mems = [{"memory": "[user] I want to save money."}]
        hint = savings_arithmetic_hint(
            "How can I save money?", mems,
        )
        assert hint == ""

    def test_cashback_question_no_trigger(self):
        # Cashback questions should NOT trigger the savings hint
        # (covered by cashback_arithmetic_hint separately).
        mems = [
            {"memory": "[user] I have a 1% cashback card."},
            {"memory": "[user] I spent $75 at SaveMart."},
        ]
        hint = savings_arithmetic_hint(
            "How much cashback did I earn at SaveMart?", mems,
        )
        assert hint == ""

    def test_charity_donation_no_trigger(self):
        mems = [
            {"memory": "[user] I donated $100 to the charity."},
        ]
        hint = savings_arithmetic_hint(
            "How much did I donate to the charity?", mems,
        )
        assert hint == ""

    def test_empty_memories(self):
        hint = savings_arithmetic_hint(BB7C3B45_Q, [])
        assert hint == ""

    def test_empty_question(self):
        hint = savings_arithmetic_hint("", BB7C3B45_MEMS)
        assert hint == ""


# ---------- assistant turns are filtered out ----------

class TestUserTurnFilter:
    def test_assistant_only_memories_no_hint(self):
        # Both anchors in assistant turns → must be skipped because
        # we only trust user-stated prices.
        mems = [
            {"memory": "[assistant] I see you got the leather jacket "
                       "for $200."},
            {"memory": "[assistant] The leather jacket originally "
                       "retailed for $400."},
        ]
        hint = savings_arithmetic_hint(
            "How much did I save on the leather jacket?", mems,
        )
        assert hint == ""


# ---------- format details ----------

class TestHintFormat:
    def test_hint_format_clean(self):
        hint = savings_arithmetic_hint(BB7C3B45_Q, BB7C3B45_MEMS)
        assert hint.startswith("ARITHMETIC HINT")
        assert "deterministic" in hint
        # Must have the explicit calculation line
        assert "−" in hint or "-" in hint  # subtraction marker
        # Final "answer is $300" guidance
        assert "answer is $300" in hint
