"""Tests for AttentionSignature analyze() — wants + aux_flags routing.

Covers GAP-1 (preference_anchor signal lifted from inline regex into the
shared signature) and GAP-2 (temporal_constraint flag for 2nd-order
scope filtering on aggregation queries).
"""
from __future__ import annotations

from radiomind.core.attention import analyze


# --- Preference anchor (GAP-1) ---

def test_preference_anchor_set_for_recommend_query():
    sig = analyze("Can you recommend some good resources?")
    assert sig.aux_flags.get("preference_anchor") is True


def test_preference_anchor_set_for_should_i_query():
    sig = analyze("Should I attend my high school reunion?")
    assert sig.aux_flags.get("preference_anchor") is True


def test_preference_anchor_set_for_any_tips_query():
    sig = analyze("any tips for keeping my kitchen clean?")
    assert sig.aux_flags.get("preference_anchor") is True


def test_preference_anchor_set_for_what_should_i():
    sig = analyze("what should I do about my noisy neighbor?")
    assert sig.aux_flags.get("preference_anchor") is True


def test_preference_anchor_set_for_advice_request():
    sig = analyze("give me advice on my upcoming trip")
    assert sig.aux_flags.get("preference_anchor") is True


def test_preference_anchor_unset_on_factual_lookup():
    sig = analyze("What degree did I graduate with?")
    assert not sig.aux_flags.get("preference_anchor")


def test_preference_anchor_unset_on_count_query():
    sig = analyze("How many guitars do I own?")
    assert not sig.aux_flags.get("preference_anchor")


def test_preference_anchor_unset_on_date_query():
    sig = analyze("When did I move to Tokyo?")
    assert not sig.aux_flags.get("preference_anchor")


# --- Temporal constraint (GAP-2) ---

def test_temporal_constraint_set_for_consecutive_weekends():
    sig = analyze(
        "What's the total distance of the hikes I did on two "
        "consecutive weekends?"
    )
    assert sig.aux_flags.get("temporal_constraint") is True


def test_temporal_constraint_set_for_during_trip():
    sig = analyze("how much did I spend during my trip to Paris?")
    assert sig.aux_flags.get("temporal_constraint") is True


def test_temporal_constraint_set_for_last_week():
    sig = analyze("how many calories did I eat last week?")
    assert sig.aux_flags.get("temporal_constraint") is True


def test_temporal_constraint_set_for_specific_month():
    sig = analyze("how many books did I finish in March?")
    assert sig.aux_flags.get("temporal_constraint") is True


def test_temporal_constraint_unset_on_unconstrained_count():
    """Plain 'how many X do I own' should not flag a constraint."""
    sig = analyze("how many musical instruments do I own?")
    assert not sig.aux_flags.get("temporal_constraint")


def test_temporal_constraint_unset_on_factual_query():
    sig = analyze("what's my favorite restaurant?")
    assert not sig.aux_flags.get("temporal_constraint")


# --- Combined signals coexist ---

def test_preference_and_temporal_coexist():
    """A query can carry BOTH flags; they are independent dimensions."""
    sig = analyze("any tips for getting more out of my hikes during my trip?")
    assert sig.aux_flags.get("preference_anchor") is True
    assert sig.aux_flags.get("temporal_constraint") is True
