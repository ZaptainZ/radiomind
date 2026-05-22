"""NAR-4: tests for the deterministic charity-context recognizer.

API under test (introduced by NAR-5 in numeric_aggregator.py):

    detect_charity_amounts(content: str) -> list[dict]

  Each dict: {"amount": float, "phrase": str, "trigger": str}.
  Empty list when no charity-context amount is present.

Triggers (per NAR-3 design):
  T1 — receiver names a charity-context entity (food bank / animal
       shelter / children's hospital / named foundation / hospital /
       society / nonprofit / etc.)
  T2 — sentence contains literal 'charity' near a raise/donate verb
  T3 — sentence contains a known charity organization (Red Cross,
       UNICEF, American Cancer Society, etc.)

Family-transfer guard: receiver mentions niece/nephew/sister/...
→ recognizer stays silent even if other surface looks charity.

Tests are spec-first: they capture the contract that NAR-5 must
implement.
"""
from __future__ import annotations

import pytest

# Import will fail until NAR-5 lands the symbol — that's intentional.
from radiomind.refinement.numeric_aggregator import detect_charity_amounts


# ─────────────────────────────────────────────────────────────────────────────
# Target: d851d5ba's four gold events
# ─────────────────────────────────────────────────────────────────────────────
class TestD851D5BAGoldEvents:
    """Four canonical sentences from the LME-S d851d5ba haystack.
    All MUST fire and yield charity_donations cls_hint."""

    def test_e1_bake_sale_children_hospital(self):
        s = ("I helped raise over $1,000 for the local children's "
             "hospital at a charity bake sale.")
        out = detect_charity_amounts(s)
        assert len(out) == 1
        assert out[0]["amount"] == 1000.0
        # Could match either T1 (children's hospital) or T2 (literal
        # 'charity bake sale'); either is acceptable.
        assert out[0]["trigger"] in ("T1", "T2")

    def test_e2_food_bank_run_for_hunger(self):
        s = ("I just ran 5 kilometers in the 'Run for Hunger' charity "
             "event and raised $250 for a local food bank.")
        out = detect_charity_amounts(s)
        assert len(out) == 1
        assert out[0]["amount"] == 250.0
        assert out[0]["trigger"] in ("T1", "T2")

    def test_e3_american_cancer_society(self):
        s = ("I recently completed a charity fitness challenge in "
             "February and managed to raise $500 for the American "
             "Cancer Society.")
        out = detect_charity_amounts(s)
        assert len(out) == 1
        assert out[0]["amount"] == 500.0
        # Matches T1 (American Cancer Society as named org) or T3
        assert out[0]["trigger"] in ("T1", "T2", "T3")

    def test_e4_animal_shelter(self):
        s = ("I helped raise over $2,000 for the local animal shelter "
             "on January 20th.")
        out = detect_charity_amounts(s)
        assert len(out) == 1
        assert out[0]["amount"] == 2000.0
        assert out[0]["trigger"] in ("T1", "T2")


# ─────────────────────────────────────────────────────────────────────────────
# Negative controls — Codex-required: recognizer MUST stay silent
# ─────────────────────────────────────────────────────────────────────────────
class TestNegativesNoFire:
    def test_groceries_purchase(self):
        s = "I spent $50 on groceries at SaveMart this week."
        assert detect_charity_amounts(s) == []

    def test_concert_tickets(self):
        s = "I bought concert tickets for $200."
        assert detect_charity_amounts(s) == []

    def test_family_gift(self):
        s = "I gave my niece $50 for her birthday."
        assert detect_charity_amounts(s) == []

    def test_cashback(self):
        s = "I got $50 cashback at SaveMart."
        assert detect_charity_amounts(s) == []

    def test_savings(self):
        s = "I saved $20 with the coupon."
        assert detect_charity_amounts(s) == []

    def test_rent(self):
        s = "My rent went up to $1,500 this month."
        assert detect_charity_amounts(s) == []

    def test_income(self):
        s = "I earned $300 freelancing this weekend."
        assert detect_charity_amounts(s) == []

    def test_education_not_charity(self):
        """The LME-S music-benefit false positive that V8.2.x has
        seen: 'raised $5,000 for music education'. Per NAR-3 design,
        T1 doesn't fire (education ≠ charity-org keyword), T2
        doesn't fire (no 'charity' literal), T3 doesn't fire (no
        named charity). Recognizer stays silent — leaves the LLM
        free to classify however it wants."""
        s = ("I actually helped organize a music benefit concert at "
             "the Independent back in April, which was a huge success "
             "and raised over $5,000 for the local music education "
             "program.")
        assert detect_charity_amounts(s) == []

    def test_empty_string(self):
        assert detect_charity_amounts("") == []

    def test_no_amount(self):
        s = "I volunteered at a charity bake sale and animal shelter."
        # No $N → nothing to extract
        assert detect_charity_amounts(s) == []


# ─────────────────────────────────────────────────────────────────────────────
# Family-transfer guard — must dominate other triggers
# ─────────────────────────────────────────────────────────────────────────────
class TestFamilyGuard:
    @pytest.mark.parametrize("relation", [
        "niece", "nephew", "sister", "brother", "cousin",
        "mom", "dad", "aunt", "uncle", "son", "daughter",
        "wife", "husband", "partner",
    ])
    def test_family_relation_blocks_match(self, relation):
        s = f"gave $500 to my {relation} for their charity event."
        assert detect_charity_amounts(s) == [], (
            f"family guard should block: '{relation}'")


# ─────────────────────────────────────────────────────────────────────────────
# Trigger T1 — charity-receiver keyword
# ─────────────────────────────────────────────────────────────────────────────
class TestTriggerT1Receiver:
    @pytest.mark.parametrize("receiver", [
        "the local food bank",
        "a food bank",
        "the local animal shelter",
        "an animal shelter",
        "the homeless shelter",
        "the children's hospital",
        "the local hospital",
        "the American Cancer Society",
        "the Salvation Army",
        "Red Cross",
        "UNICEF",
        "Doctors Without Borders",
        "the Humane Society",
        "a nonprofit",
        "the foundation",
        "Doctors Without Borders",
    ])
    def test_receiver_fires_t1(self, receiver):
        s = f"I helped raise $300 for {receiver}."
        out = detect_charity_amounts(s)
        assert out, f"T1 should fire on receiver '{receiver}'"
        assert out[0]["amount"] == 300.0


# ─────────────────────────────────────────────────────────────────────────────
# Trigger T2 — literal 'charity' word near raise/donate verb
# ─────────────────────────────────────────────────────────────────────────────
class TestTriggerT2CharityLiteral:
    def test_charity_bake_sale_phrase(self):
        s = "Raised $750 at a charity bake sale last weekend."
        out = detect_charity_amounts(s)
        assert out, "T2 should fire on 'charity bake sale' near raise"
        assert out[0]["amount"] == 750.0

    def test_charity_event_phrase(self):
        s = "Donated $100 to a charity event yesterday."
        out = detect_charity_amounts(s)
        assert out, "T2 should fire on charity + donate"
        assert out[0]["amount"] == 100.0

    def test_charity_fitness_challenge(self):
        s = "Completed a charity fitness challenge and raised $400."
        out = detect_charity_amounts(s)
        assert out, "T2 should fire on charity fitness challenge + raise"
        assert out[0]["amount"] == 400.0


# ─────────────────────────────────────────────────────────────────────────────
# Trigger T3 — known charity org keywords
# ─────────────────────────────────────────────────────────────────────────────
class TestTriggerT3KnownOrg:
    @pytest.mark.parametrize("org", [
        "Red Cross",
        "UNICEF",
        "American Cancer Society",
        "Doctors Without Borders",
        "Salvation Army",
        "Habitat for Humanity",
    ])
    def test_named_org_fires_t3(self, org):
        s = f"I donated $200 to {org}."
        out = detect_charity_amounts(s)
        assert out, f"T3 should fire on named org '{org}'"
        assert out[0]["amount"] == 200.0


# ─────────────────────────────────────────────────────────────────────────────
# Verb form coverage — fix the base-form 'raise' bug
# ─────────────────────────────────────────────────────────────────────────────
class TestVerbFormCoverage:
    """The core bug NAR-1 exposed: `_amount_verb_to_class` matched
    only 'raised' (past tense). The recognizer must catch all
    inflections."""

    @pytest.mark.parametrize("verb_phrase", [
        "raised",
        "raise",
        "raising",
        "helped raise",
        "helping raise",
        "to raise",
        "donated",
        "donate",
        "donating",
        "contributed",
        "contribute",
    ])
    def test_all_charity_verb_forms(self, verb_phrase):
        s = f"I {verb_phrase} $300 for the local food bank."
        out = detect_charity_amounts(s)
        assert out, f"verb form '{verb_phrase}' should be recognized"


# ─────────────────────────────────────────────────────────────────────────────
# Multiple amounts in one sentence — extract each
# ─────────────────────────────────────────────────────────────────────────────
class TestMultipleAmounts:
    def test_two_amounts_two_emits(self):
        s = ("Last month I raised $500 for the food bank, and earlier "
             "this year I helped raise $1,200 for the children's "
             "hospital.")
        out = detect_charity_amounts(s)
        assert len(out) == 2
        amts = sorted(e["amount"] for e in out)
        assert amts == [500.0, 1200.0]


# ─────────────────────────────────────────────────────────────────────────────
# Output schema invariants
# ─────────────────────────────────────────────────────────────────────────────
class TestOutputSchema:
    def test_each_record_has_required_fields(self):
        s = "I helped raise over $1,000 for the local children's hospital."
        out = detect_charity_amounts(s)
        assert out
        rec = out[0]
        assert "amount" in rec and isinstance(rec["amount"], float)
        assert "phrase" in rec and isinstance(rec["phrase"], str)
        assert "trigger" in rec and rec["trigger"] in ("T1", "T2", "T3")

    def test_phrase_is_non_empty(self):
        s = "I donated $200 to UNICEF."
        out = detect_charity_amounts(s)
        assert out and len(out[0]["phrase"]) > 0
