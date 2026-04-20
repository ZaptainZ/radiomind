"""Tests for NumericAggregator — bottom-up cardinal accumulation."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def sandbox(monkeypatch):
    """Isolated RADIOMIND_HOME per test — never touch user's real store."""
    tmp = tempfile.mkdtemp(prefix="rm-numagg-test-")
    monkeypatch.setenv("RADIOMIND_HOME", tmp)
    yield Path(tmp)


@pytest.fixture
def mind(sandbox):
    from radiomind import RadioMind
    m = RadioMind()
    m.initialize()
    yield m
    m.shutdown()


def _turns(*triples):
    """Compact fixture builder: (content, turn_id, session_date) tuples."""
    return [
        {
            "content": c, "role": "user",
            "metadata": {"turn_id": tid, "session_date": d},
        }
        for c, tid, d in triples
    ]


class TestOwnership:
    """Ownership statements increment the class count."""

    def test_basic_ownership_counts_each_distinct_item(self, mind):
        mind.ingest_turns_raw(
            _turns(
                ("I bought a Yamaha guitar yesterday", "s1", "2025-01-10"),
                ("I picked up a ukulele at the thrift store", "s2", "2025-02-11"),
                ("I have a Roland digital piano at home", "s3", "2025-03-05"),
            ),
            domain="personal", user_id="alice",
        )
        entry = mind._numeric_agg.get_cardinal(
            user_id="alice", domain="personal", entity_class="musical_instruments",
        )
        assert entry is not None
        assert entry.count == 3, f"expected 3, got {entry.count}: {entry.members}"

    def test_ontology_rollup_merges_to_parent_class(self, mind):
        """Guitar + piano + ukulele all roll up to musical_instruments."""
        mind.ingest_turns_raw(
            _turns(
                ("I bought a guitar", "s1", "2025-01-10"),
                ("I got a piano", "s2", "2025-01-11"),
            ),
            domain="personal", user_id="alice",
        )
        parent = mind._numeric_agg.get_cardinal("alice", "personal", "musical_instruments")
        guitars = mind._numeric_agg.get_cardinal("alice", "personal", "guitars")
        pianos = mind._numeric_agg.get_cardinal("alice", "personal", "pianos")
        assert parent is not None and parent.count == 2
        assert guitars is not None and guitars.count == 1
        assert pianos is not None and pianos.count == 1

    def test_intervening_adverbs_do_not_block_match(self, mind):
        """'I also got', 'I just bought', 'I later picked up' all match."""
        mind.ingest_turns_raw(
            _turns(
                ("I also got a new toaster", "s1", "2025-01-10"),
                ("I just bought a coffee maker", "s2", "2025-01-11"),
                ("Later I picked up a blender", "s3", "2025-01-12"),
            ),
            domain="personal", user_id="alice",
        )
        kitchen = mind._numeric_agg.get_cardinal("alice", "personal", "kitchen_items")
        assert kitchen is not None and kitchen.count == 3


class TestAmounts:
    """Amount events accumulate total_amount."""

    def test_charity_donations_sum(self, mind):
        mind.ingest_turns_raw(
            _turns(
                ("I raised $1500 for charity at the gala", "s1", "2025-01-10"),
                ("Later I donated another $500 to the animal shelter", "s2", "2025-02-01"),
                ("Then I donated 1000 dollars to the school fundraiser", "s3", "2025-03-01"),
                ("I donated $750 to research", "s4", "2025-04-01"),
            ),
            domain="personal", user_id="alice",
        )
        charity = mind._numeric_agg.get_cardinal("alice", "personal", "charity_donations")
        assert charity is not None
        assert charity.count == 4
        assert charity.total_amount == pytest.approx(3750.0)

    def test_amount_regex_tolerates_another_about_roughly(self, mind):
        """Intervening 'another' / 'about' / 'roughly' mustn't block the match."""
        mind.ingest_turns_raw(
            _turns(
                ("I donated another $500 to the shelter", "s1", "2025-01-10"),
                ("I raised about $1000 at the charity event", "s2", "2025-02-01"),
                ("I earned roughly $200 from the sale", "s3", "2025-03-01"),
            ),
            domain="personal", user_id="alice",
        )
        charity = mind._numeric_agg.get_cardinal("alice", "personal", "charity_donations")
        income = mind._numeric_agg.get_cardinal("alice", "personal", "income_events")
        assert charity is not None and charity.count == 2
        assert charity.total_amount == pytest.approx(1500.0)
        assert income is not None and income.count == 1
        assert income.total_amount == pytest.approx(200.0)


class TestQueryInterface:
    """get_numeric_cardinal routes queries to the cache correctly."""

    def test_aggregation_count_query_hits_rollup(self, mind):
        mind.ingest_turns_raw(
            _turns(
                ("I bought a guitar", "s1", "2025-01-10"),
                ("I got a ukulele", "s2", "2025-01-11"),
                ("I have a piano", "s3", "2025-01-12"),
            ),
            domain="personal", user_id="alice",
        )
        view = mind.get_numeric_cardinal(
            "How many musical instruments do I currently own?",
            domain="personal", user_id="alice",
        )
        assert "musical_instruments" in view
        assert "count=3" in view

    def test_alias_resolution_money_to_charity(self, mind):
        """'how much money did I raise for charity' → charity_donations via alias."""
        mind.ingest_turns_raw(
            _turns(
                ("I raised $500 for charity", "s1", "2025-01-10"),
                ("I donated $1000 to charity", "s2", "2025-02-11"),
            ),
            domain="personal", user_id="alice",
        )
        view = mind.get_numeric_cardinal(
            "How much money did I raise for charity in total?",
            domain="personal", user_id="alice",
        )
        assert "charity_donations" in view
        assert "1500" in view or "1,500" in view

    def test_non_cardinal_query_returns_empty(self, mind):
        """Questions that aren't asking for a count get an empty view."""
        mind.ingest_turns_raw(
            _turns(
                ("I bought a guitar", "s1", "2025-01-10"),
            ),
            domain="personal", user_id="alice",
        )
        assert mind.get_numeric_cardinal(
            "What instrument did I buy?", domain="personal", user_id="alice",
        ) == ""
        assert mind.get_numeric_cardinal(
            "How many days ago did I buy the guitar?",
            domain="personal", user_id="alice",
        ) == ""


class TestDisposal:
    """Disposal reduces count."""

    def test_sell_decrements_count(self, mind):
        mind.ingest_turns_raw(
            _turns(
                ("I bought a Fender Stratocaster guitar", "s1", "2025-01-10"),
                ("I got a Yamaha guitar later", "s2", "2025-02-11"),
                ("I sold the Fender Stratocaster", "s3", "2025-05-15"),
            ),
            domain="personal", user_id="alice",
        )
        guitars = mind._numeric_agg.get_cardinal("alice", "personal", "guitars")
        assert guitars is not None
        # Count should be 1 after dispose (2 owned - 1 sold)
        assert guitars.count == 1


class TestLLMBatchExtraction:
    """When an LLM is injected, the batch extractor replaces regex."""

    def test_llm_extracts_implicit_ownership_reveals(self, sandbox, monkeypatch):
        """'I've had my Fender for 5 years' must yield OWN (regex would miss)."""
        import json as _json
        from radiomind import RadioMind

        def _mock_llm(prompt, system=""):
            # Mock returns two OWN events for instruments
            return _json.dumps({
                "events": [
                    {"turn": 0, "polarity": "own", "entity_class": "musical_instruments",
                     "canonical_member": "Fender Stratocaster", "amount": None, "currency": None},
                    {"turn": 1, "polarity": "own", "entity_class": "musical_instruments",
                     "canonical_member": "Yamaha FG800", "amount": None, "currency": None},
                ]
            })

        m = RadioMind(llm=_mock_llm)
        m.initialize()
        m.ingest_turns_raw(
            _turns(
                ("I've had my Fender Stratocaster for 5 years", "s1", "2025-01-10"),
                ("My Yamaha FG800 is 8 years old and still plays great", "s2", "2025-02-11"),
            ),
            domain="personal", user_id="alice",
        )
        entry = m._numeric_agg.get_cardinal("alice", "personal", "musical_instruments")
        assert entry is not None and entry.count == 2
        assert "Fender Stratocaster" in entry.members
        assert "Yamaha FG800" in entry.members
        m.shutdown()

    def test_llm_emits_both_own_and_amount_for_purchase(self, sandbox, monkeypatch):
        """Purchase emits OWN (instrument) + AMOUNT (spending)."""
        import json as _json
        from radiomind import RadioMind

        def _mock_llm(prompt, system=""):
            return _json.dumps({
                "events": [
                    {"turn": 0, "polarity": "own", "entity_class": "musical_instruments",
                     "canonical_member": "Korg B1", "amount": None, "currency": None},
                    {"turn": 0, "polarity": "amount", "entity_class": "spending_events",
                     "canonical_member": "Korg B1", "amount": 600, "currency": "USD"},
                ]
            })
        m = RadioMind(llm=_mock_llm)
        m.initialize()
        m.ingest_turns_raw(
            _turns(
                ("I bought a Korg B1 for $600", "s1", "2025-01-10"),
            ),
            domain="personal", user_id="alice",
        )
        inst = m._numeric_agg.get_cardinal("alice", "personal", "musical_instruments")
        spend = m._numeric_agg.get_cardinal("alice", "personal", "spending_events")
        assert inst is not None and inst.count == 1
        assert spend is not None and spend.count == 1 and spend.total_amount == 600
        m.shutdown()

    def test_llm_parse_failure_falls_back_to_regex(self, sandbox, monkeypatch):
        """Invalid JSON from LLM → regex fast-path still captures what it can."""
        from radiomind import RadioMind

        def _bad_llm(prompt, system=""):
            return "this is not json at all"

        m = RadioMind(llm=_bad_llm)
        m.initialize()
        m.ingest_turns_raw(
            _turns(
                ("I bought a guitar", "s1", "2025-01-10"),
            ),
            domain="personal", user_id="alice",
        )
        # Regex fallback should still catch "I bought a guitar"
        entry = m._numeric_agg.get_cardinal("alice", "personal", "musical_instruments")
        assert entry is not None and entry.count == 1
        m.shutdown()


class TestPersistence:
    """Cache survives restart."""

    def test_data_persists_across_restart(self, sandbox, monkeypatch):
        from radiomind import RadioMind
        m1 = RadioMind()
        m1.initialize()
        m1.ingest_turns_raw(
            _turns(
                ("I bought a guitar", "s1", "2025-01-10"),
                ("I got a piano", "s2", "2025-01-11"),
            ),
            domain="personal", user_id="alice",
        )
        m1.shutdown()

        m2 = RadioMind()
        m2.initialize()
        entry = m2._numeric_agg.get_cardinal("alice", "personal", "musical_instruments")
        assert entry is not None and entry.count == 2
        m2.shutdown()
