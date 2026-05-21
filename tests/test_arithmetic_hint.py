"""V8.2.3a cashback arithmetic helper — fixture tests.

Codex acceptance criteria:
  - 9aaed6a3 targeted PASS
  - negatives must NOT trigger:
    - has $75 but no cashback rate
    - has cashback rate but no matching merchant amount
    - "how much did I spend" (not cashback)
    - "$300 saved" / charity sum patterns
  - parser unit coverage
"""
from __future__ import annotations

import pytest

from radiomind.core.arithmetic_hint import (
    cashback_arithmetic_hint,
    _query_triggers,
    _extract_merchant_from_query,
    _find_cashback_rate,
    _find_merchant_amount,
)


def mem(content: str) -> dict:
    return {"memory": content}


# ─────────────────────────────────────────────────────────────────────────────
# Target: 9aaed6a3 SaveMart $0.75
# ─────────────────────────────────────────────────────────────────────────────
class TestTargetSaveMart:
    def test_savemart_cashback_hint_fires(self):
        q = "How much cashback did I earn at SaveMart last Thursday?"
        mems = [
            mem("I'm trying to plan my grocery shopping trip at SaveMart. "
                "I have a membership there and can earn 1% cashback on all purchases."),
            mem("I spent $75 on groceries at SaveMart last Thursday."),
            mem("Let's start with the $75 you spent at SaveMart last Thursday."),
        ]
        hint = cashback_arithmetic_hint(q, mems)
        assert hint, f"hint should fire; got: {hint!r}"
        assert "ARITHMETIC HINT" in hint
        assert "$0.75" in hint
        assert "1%" in hint or "1 percent" in hint.lower()
        assert "$75" in hint
        assert "SaveMart" in hint


# ─────────────────────────────────────────────────────────────────────────────
# Negative controls — Codex's explicit list
# ─────────────────────────────────────────────────────────────────────────────
class TestNegativesNoTrigger:
    """Codex required negatives that must NOT trigger."""

    def test_has_amount_but_no_rate(self):
        """Has $75 but no cashback rate → don't hint (we can't compute)."""
        q = "How much cashback did I earn at SaveMart last Thursday?"
        mems = [
            mem("I spent $75 on groceries at SaveMart last Thursday."),
            # No cashback rate mentioned anywhere
        ]
        assert cashback_arithmetic_hint(q, mems) == ""

    def test_has_rate_but_no_amount(self):
        """Has cashback rate but no spend amount → don't hint."""
        q = "How much cashback did I earn at SaveMart last Thursday?"
        mems = [
            mem("I have a SaveMart membership with 1% cashback on all purchases."),
            # No $ amount
        ]
        assert cashback_arithmetic_hint(q, mems) == ""

    def test_how_much_spent_not_cashback(self):
        """'How much did I spend' is NOT a cashback question → don't trigger."""
        q = "How much did I spend at SaveMart last Thursday?"
        mems = [
            mem("I spent $75 at SaveMart with 1% cashback."),
        ]
        assert cashback_arithmetic_hint(q, mems) == ""

    def test_dollar_saved_charity_sum(self):
        """'How much did I raise for charity' has $ saved but no cashback semantic."""
        q = "How much money did I raise for charity in total?"
        mems = [
            mem("Donated $300 to local charity."),
            mem("Raised $500 at charity gala."),
            mem("$1000 from corporate match (10% cashback program donation)."),
        ]
        # Even though memories contain a cashback word, query isn't cashback-earning
        assert cashback_arithmetic_hint(q, mems) == ""


# ─────────────────────────────────────────────────────────────────────────────
# Parser unit tests
# ─────────────────────────────────────────────────────────────────────────────
class TestQueryTriggers:
    @pytest.mark.parametrize("q", [
        "How much cashback did I earn at SaveMart last Thursday?",
        "How much cash back did I earn at Target?",
        "What was my cashback at the grocery store?",
        "How much did I earn in cashback at SaveMart?",
        "How much rebate did I earn at the store?",
        "How much rewards did I get at Amazon?",
    ])
    def test_positive_triggers(self, q):
        assert _query_triggers(q), f"should trigger: {q}"

    @pytest.mark.parametrize("q", [
        "How much did I spend at SaveMart?",
        "How much did I save in total?",
        "What is my favorite store?",
        "When did I shop at SaveMart?",
        "How much money did I raise for charity?",
    ])
    def test_negative_triggers(self, q):
        assert not _query_triggers(q), f"should NOT trigger: {q}"


class TestExtractMerchant:
    def test_extracts_simple_proper_noun(self):
        assert _extract_merchant_from_query(
            "How much cashback at SaveMart last Thursday?"
        ) == "SaveMart"

    def test_extracts_multi_word(self):
        merchant = _extract_merchant_from_query(
            "How much cashback at Whole Foods last week?"
        )
        assert merchant and ("Whole Foods" in merchant or merchant == "Whole Foods")

    def test_no_merchant_returns_none(self):
        assert _extract_merchant_from_query(
            "How much cashback did I earn?"
        ) is None


class TestFindCashbackRate:
    def test_percent_sign(self):
        assert _find_cashback_rate(["I have 1% cashback on all purchases."]) == 0.01

    def test_percent_word(self):
        assert _find_cashback_rate(["I get 2 percent cashback at Target."]) == 0.02

    def test_decimal_rate(self):
        assert _find_cashback_rate(["1.5% cashback membership"]) == 0.015

    def test_no_rate(self):
        assert _find_cashback_rate(["I went to SaveMart."]) is None


class TestFindMerchantAmount:
    def test_finds_spend_amount(self):
        mems = ["I spent $75 at SaveMart last Thursday."]
        assert _find_merchant_amount(mems, "SaveMart") == 75.0

    def test_filters_by_merchant(self):
        mems = [
            "Spent $10 at Starbucks.",
            "I spent $75 at SaveMart.",
        ]
        # Should prefer the SaveMart amount
        assert _find_merchant_amount(mems, "SaveMart") == 75.0

    def test_no_amount(self):
        assert _find_merchant_amount(["I went shopping."], "SaveMart") is None

    def test_decimal_amount(self):
        mems = ["Spent $3.99 on bread at SaveMart."]
        # Amounts < $5 are likely unit prices, but spend keyword in context
        # — current heuristic returns it via spend-context branch
        result = _find_merchant_amount(mems, "SaveMart")
        assert result == 3.99


# ─────────────────────────────────────────────────────────────────────────────
# Edge cases
# ─────────────────────────────────────────────────────────────────────────────
class TestEdgeCases:
    def test_empty_question(self):
        assert cashback_arithmetic_hint("", [mem("1% cashback")]) == ""

    def test_empty_memories(self):
        assert cashback_arithmetic_hint("How much cashback at X?", []) == ""

    def test_decimal_result(self):
        """1.5% × $200 = $3.00 → should format clean."""
        q = "How much cashback did I earn at TargetStore?"
        mems = [
            mem("I have 1.5% cashback at TargetStore."),
            mem("Spent $200 on electronics at TargetStore."),
        ]
        hint = cashback_arithmetic_hint(q, mems)
        assert hint
        assert "$3" in hint  # 1.5% × 200 = 3

    def test_uses_dot_in_dollar(self):
        """5% × $123.45 = $6.17."""
        q = "How much cashback did I earn at Acme?"
        mems = [
            mem("Acme has 5% cashback."),
            mem("Spent $123.45 at Acme."),
        ]
        hint = cashback_arithmetic_hint(q, mems)
        assert hint
        # 5% × 123.45 = 6.1725 → rounds to $6.17
        assert "$6.17" in hint
