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


class TestTrinityClassPromotion:
    """Trinity class promotion at ingest: when LLM/regex leave amounts in
    the generic `amount_events` bucket, trinity reads the original sentence
    and decides whether to promote to a specific class. Closes the
    d851d5ba failure mode where bake-sale charity events stayed generic
    on certain LLM seeds and got missed by query-time scope filters.
    """

    def test_promotes_generic_amount_to_charity_donations(self, sandbox):
        """LLM extracts amounts as generic; trinity promotes to charity."""
        import json as _json
        from radiomind import RadioMind

        # Stateful mock: extraction returns generic class; trinity assigns
        # specific class. Distinguish by prompt content.
        call_count = {"n": 0}

        def _mock_llm(prompt, system=""):
            call_count["n"] += 1
            if "Extract OWNERSHIP" in prompt or "events" in prompt.lower() and "OWNERSHIP" in prompt:
                # Phase 1: batch extraction (generic class)
                return _json.dumps({
                    "events": [
                        {"turn": 0, "polarity": "amount",
                         "entity_class": "amount_events",
                         "canonical_member": "", "amount": 1000, "currency": "USD"},
                        {"turn": 1, "polarity": "amount",
                         "entity_class": "amount_events",
                         "canonical_member": "", "amount": 750, "currency": "USD"},
                    ]
                })
            if "triangulate" in prompt.lower() and "assignments" in prompt.lower():
                # Phase 2: trinity class promotion vote
                return _json.dumps({
                    "stances": [
                        {"name": "literal", "emphasis": "named-charity",
                         "conclusion": "promote both"},
                        {"name": "inference", "emphasis": "verb+target",
                         "conclusion": "promote both"},
                        {"name": "skeptic", "emphasis": "ambiguity",
                         "conclusion": "promote both"},
                    ],
                    "final_answer": "promote both to charity_donations",
                    "assignments": [
                        {"event_id": 0, "entity_class": "charity_donations"},
                        {"event_id": 1, "entity_class": "charity_donations"},
                    ],
                })
            # Other LLM calls (refinement, classify_batch) — return empty/no-op
            return _json.dumps({"events": []})

        m = RadioMind(llm=_mock_llm)
        m.initialize()
        # Sentences that pass the cardinal-signal gate (` for $`)
        # but use verbs NOT in the regex AMOUNT_PATTERNS verb list
        # (sponsored/pledged are unmapped). LLM is the sole class
        # arbiter — and we mock it to return the generic class. This
        # mirrors the d851d5ba failure mode: regex doesn't classify,
        # LLM mis-classifies as generic, scope filter for "charity"
        # misses the events.
        m.ingest_turns_raw(
            _turns(
                # Gate keyword: "donation". Regex AMOUNT_PATTERNS need
                # "i/we" subject — "Last weekend's drive" doesn't match,
                # so regex extracts NO class hint. LLM is sole arbiter.
                ("Last weekend's donation drive raised $1,000 for the "
                 "children's hospital fund",
                 "s1", "2025-01-10"),
                ("The charity gala collected $750 in donations Friday night",
                 "s2", "2025-02-11"),
            ),
            domain="personal", user_id="alice",
        )
        # Trinity should have promoted both into charity_donations
        charity = m._numeric_agg.get_cardinal(
            "alice", "personal", "charity_donations",
        )
        assert charity is not None, (
            "trinity_class_promotion failed to promote generic amounts "
            "into charity_donations"
        )
        assert charity.total_amount == 1750, (
            f"expected $1750 (both promoted), got ${charity.total_amount}"
        )
        m.shutdown()

    def test_skips_when_only_one_ambiguous_event(self, sandbox):
        """Single ambiguous amount → skip trinity (not worth the LLM call)."""
        import json as _json
        from radiomind import RadioMind

        trinity_called = {"n": 0}

        def _mock_llm(prompt, system=""):
            if "triangulate" in prompt.lower() and "assignments" in prompt.lower():
                trinity_called["n"] += 1
                return _json.dumps({
                    "stances": [], "final_answer": "x",
                    "assignments": [{"event_id": 0,
                                    "entity_class": "charity_donations"}],
                })
            if "OWNERSHIP" in prompt:
                return _json.dumps({
                    "events": [
                        {"turn": 0, "polarity": "amount",
                         "entity_class": "amount_events",
                         "canonical_member": "", "amount": 500, "currency": "USD"},
                    ]
                })
            return _json.dumps({"events": []})

        m = RadioMind(llm=_mock_llm)
        m.initialize()
        m.ingest_turns_raw(
            _turns(("I gave $500 somewhere", "s1", "2025-01-10")),
            domain="personal", user_id="alice",
        )
        # < 2 ambiguous → trinity should NOT fire (cost guard)
        assert trinity_called["n"] == 0
        m.shutdown()

    def test_does_not_downgrade_already_specific_class(self, sandbox):
        """Trinity result `amount_events` for a specific class → keep specific."""
        import json as _json
        from radiomind import RadioMind

        def _mock_llm(prompt, system=""):
            if "OWNERSHIP" in prompt:
                # LLM already classifies as specific (charity_donations)
                return _json.dumps({
                    "events": [
                        {"turn": 0, "polarity": "amount",
                         "entity_class": "charity_donations",
                         "canonical_member": "", "amount": 1000, "currency": "USD"},
                        {"turn": 1, "polarity": "amount",
                         "entity_class": "charity_donations",
                         "canonical_member": "", "amount": 500, "currency": "USD"},
                    ]
                })
            # Trinity should not fire (no ambiguous candidates)
            return _json.dumps({"events": []})

        m = RadioMind(llm=_mock_llm)
        m.initialize()
        m.ingest_turns_raw(
            _turns(
                ("I donated $1000 to Red Cross", "s1", "2025-01-10"),
                ("I donated $500 to UNICEF", "s2", "2025-02-11"),
            ),
            domain="personal", user_id="alice",
        )
        charity = m._numeric_agg.get_cardinal(
            "alice", "personal", "charity_donations",
        )
        assert charity is not None
        assert charity.total_amount == 1500
        m.shutdown()


class TestNERThirdSource:
    """LLM-as-NER pass adds a third independent evidence channel to
    `_trinity_class_promotion` (alongside LLM batch extraction and
    regex verb hint). NER tags ORG / EVENT / CAUSE / VENUE point to
    classes that surface verbs miss.
    """

    def test_ner_returns_empty_when_no_money_turns(self, sandbox):
        """Pre-filter on $: turns without money signal don't reach NER."""
        import json as _json
        from radiomind import RadioMind

        ner_called = {"n": 0}
        def _llm(prompt, system=""):
            if "Identify named entities" in prompt:
                ner_called["n"] += 1
                return _json.dumps({"ner": []})
            return _json.dumps({"events": []})

        m = RadioMind(llm=_llm)
        m.initialize()
        m.ingest_turns_raw(
            _turns(
                ("I went to the park yesterday", "s1", "2025-01-10"),
                ("I love hiking in the mountains", "s2", "2025-02-11"),
            ),
            domain="personal", user_id="alice",
        )
        # No turns mention $ → NER call should be skipped entirely
        assert ner_called["n"] == 0
        m.shutdown()

    def test_ner_called_on_money_turns(self, sandbox):
        """Turns with $ pass the gate and trigger one NER call."""
        import json as _json
        from radiomind import RadioMind

        ner_called = {"n": 0}
        def _llm(prompt, system=""):
            if "Identify named entities" in prompt:
                ner_called["n"] += 1
                return _json.dumps({
                    "ner": [
                        {"turn_id": "s1", "entities": [
                            {"type": "ORG", "text": "Red Cross"},
                            {"type": "MONEY", "text": "$500"},
                            {"type": "CAUSE", "text": "disaster relief"},
                        ]},
                    ]
                })
            if "OWNERSHIP" in prompt:
                return _json.dumps({"events": [
                    {"turn": 0, "polarity": "amount",
                     "entity_class": "amount_events",
                     "canonical_member": "", "amount": 500, "currency": "USD"},
                    {"turn": 1, "polarity": "amount",
                     "entity_class": "amount_events",
                     "canonical_member": "", "amount": 200, "currency": "USD"},
                ]})
            if "triangulate" in prompt.lower() and "assignments" in prompt.lower():
                # Trinity sees evidence WITH NER tags now — confirm the
                # promotion completes (test the wire-up, not the LLM).
                return _json.dumps({
                    "stances": [{"name": "x", "emphasis": "x", "conclusion": "x", "confidence": 0.8}] * 3,
                    "final_answer": "promote both",
                    "confidence": 0.85,
                    "assignments": [
                        {"event_id": 0, "entity_class": "charity_donations"},
                        {"event_id": 1, "entity_class": "charity_donations"},
                    ],
                })
            return _json.dumps({"events": []})

        m = RadioMind(llm=_llm)
        m.initialize()
        # Both turns have $ — both should hit NER (in one batched call).
        # Both phrasings use third-person subjects so regex
        # AMOUNT_PATTERN (which requires "i/we" subject) doesn't
        # classify EITHER. LLM extracts both as generic amount_events.
        # ≥2 ambiguous candidates → trinity_class_promotion fires; NER
        # tags inform the trinity vote (the entire purpose of this test).
        m.ingest_turns_raw(
            _turns(
                # "raised $" passes the cardinal-signal gate; subject is
                # third-person ("fundraiser"), so regex AMOUNT_PATTERN
                # (requires "i/we" subject) doesn't extract.
                ("The Red Cross fundraiser raised $500 for disaster relief",
                 "s1", "2025-01-10"),
                # "received" + "donations" pass gate; subject is "the
                # organization" so regex AMOUNT_PATTERN doesn't match.
                ("The literacy organization received $200 in donations last month",
                 "s2", "2025-02-11"),
            ),
            domain="personal", user_id="alice",
        )
        assert ner_called["n"] >= 1
        # Trinity then promoted via NER+LLM evidence (no regex available
        # because both subjects are organizations, not "I/we").
        charity = m._numeric_agg.get_cardinal(
            "alice", "personal", "charity_donations",
        )
        assert charity is not None
        assert charity.total_amount == 700
        m.shutdown()

    def test_ner_unparseable_does_not_crash(self, sandbox):
        """NER returns garbage → empty NER dict, trinity still runs."""
        import json as _json
        from radiomind import RadioMind

        def _llm(prompt, system=""):
            if "Identify named entities" in prompt:
                return "not json {invalid"
            if "OWNERSHIP" in prompt:
                return _json.dumps({"events": [
                    {"turn": 0, "polarity": "amount",
                     "entity_class": "charity_donations",
                     "canonical_member": "", "amount": 100, "currency": "USD"},
                ]})
            return _json.dumps({"events": []})

        m = RadioMind(llm=_llm)
        m.initialize()
        m.ingest_turns_raw(
            _turns(("I donated $100 to charity", "s1", "2025-01-10")),
            domain="personal", user_id="alice",
        )
        # Should not have crashed; charity entry should still exist
        charity = m._numeric_agg.get_cardinal(
            "alice", "personal", "charity_donations",
        )
        assert charity is not None
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
