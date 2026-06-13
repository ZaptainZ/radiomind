"""SmallUserReadiness-1b: diversity metrics + narrow-adapter gating.

Deterministic — pure functions + a stubbed generator. No LLM / store.
Multi-domain path must stay unchanged; single-domain only trains when
diverse enough; metadata/flag carried through.
"""
from __future__ import annotations

from radiomind.training.diversity import (
    NARROW_MAX_NEAR_DUP,
    diversity_report,
    narrow_training_ok,
)
from radiomind.training.data_gen import DataGenReport


# ---------------- diversity_report ----------------

def test_distinct_sources_and_vocab():
    sources = [
        "hand-write parsers for full control over edge cases",
        "add circuit breakers to network services",
        "prefer adapters over rewriting systems",
    ]
    rep = diversity_report(sources, habit_count=3)
    assert rep.example_count == 3
    assert rep.distinct_sources == 3
    assert rep.distinct_concept_tokens >= 12  # rich vocabulary
    assert rep.near_dup_ratio == 0.0


def test_near_dup_ratio_detects_repetition():
    answers = ["I validate inputs defensively at every boundary"] * 4
    rep = diversity_report(answers, habit_count=1)
    # 3 of 4 are near-dups of an earlier one
    assert rep.near_dup_ratio == 0.75
    assert rep.distinct_sources == 1


def test_exact_duplicates_collapse_sources():
    rep = diversity_report(["same text here", "same text here", "other one"], 2)
    assert rep.distinct_sources == 2


# ---------------- narrow_training_ok ----------------

def test_narrow_ok_when_diverse():
    rep = diversity_report([
        "hand-write parsers for control over edge cases",
        "add circuit breakers and backoff to network services",
        "prefer adapter layers over rewriting systems",
        "cache aggressively near the edge for latency",
    ], habit_count=5)
    ok, why = narrow_training_ok(rep)
    assert ok and why == ""


def test_narrow_refused_when_repetitive():
    rep = diversity_report(["I validate inputs defensively"] * 6, habit_count=5)
    ok, why = narrow_training_ok(rep)
    assert not ok and "near-duplicate" in why


def test_narrow_refused_when_too_few_concepts():
    # tiny shared vocabulary → below NARROW_MIN_CONCEPTS
    rep = diversity_report(["deploy code", "ship code"], habit_count=5)
    ok, why = narrow_training_ok(rep)
    assert not ok and ("concepts" in why or "near-duplicate" in why)


# ---------------- DataGenReport carries narrow flag ----------------

def test_report_narrow_default_false():
    r = DataGenReport(train_count=0, valid_count=0, dropped_pii=0,
                      dropped_dup=0, dropped_short=0, habits_used=0,
                      domains_used=0)
    assert r.narrow_adapter is False


def test_trainresult_carries_narrow_flag():
    from radiomind.training.lora import TrainResult
    r = TrainResult(success=True)
    assert r.narrow_adapter is False
    r.narrow_adapter = True
    assert r.narrow_adapter is True


# ---------------- integration: real generator + stub store ----------------

def _gen_with_single_domain(texts):
    import tempfile
    from pathlib import Path
    from radiomind.core.types import Habit, MemoryEntry, MemoryLevel, MemoryStatus
    from radiomind.training.data_gen import TrainingDataGenerator

    class _Store:
        def __init__(self, f): self._f = f
        def stats(self):
            return {"domains": [{"name": "coding", "memory_count": len(self._f)}]}
        def list_by_level(self, level, limit=20): return []
        def list_by_domain(self, dom, level=None, limit=8):
            return self._f[:limit] if (level == MemoryLevel.FACT and dom == "coding") else []

    class _Habits:
        def __init__(self, h): self._h = h
        def all_habits(self): return self._h

    habits = [Habit(description=t, status=MemoryStatus.CONFIRMED, confidence=0.9,
                    evidence="e", falsifier="f") for t in texts]
    facts = [MemoryEntry(content=t, domain="coding", level=MemoryLevel.FACT)
             for t in texts]
    gen = TrainingDataGenerator(_Store(facts), _Habits(habits))
    with tempfile.TemporaryDirectory() as d:
        return gen.generate_with_report(Path(d) / "t.jsonl")


def test_diverse_single_domain_trains_narrow():
    rep = _gen_with_single_domain([
        "The user hand-writes parsers for control over edge cases",
        "The user adds circuit breakers and backoff to network services",
        "The user prefers adapter layers over rewriting systems",
        "The user builds layered fallbacks for AI features",
        "The user validates inputs defensively at boundaries",
        "The user caches aggressively near the edge for latency",
    ])
    assert not rep.refused
    assert rep.narrow_adapter is True
    assert rep.domains_used == 1


def test_diversity_measured_on_sources_not_augmented_examples():
    # augmentation makes per-habit variants near-dup; the narrow gate must
    # still pass because diversity is measured on the distinct SOURCES.
    rep = _gen_with_single_domain([
        "The user hand-writes parsers for control over edge cases",
        "The user adds circuit breakers and backoff to network services",
        "The user prefers adapter layers over rewriting systems",
        "The user builds layered fallbacks for AI features",
        "The user validates inputs defensively at boundaries",
        "The user caches aggressively near the edge for latency",
    ])
    assert rep.narrow_adapter is True and rep.distinct_examples >= 30


# ---------------- source-guard: multi-domain path unchanged ----------------

def test_datagen_domain_guard_logic_present():
    src = (__import__("pathlib").Path(__file__).resolve().parents[1]
           / "src" / "radiomind" / "training" / "data_gen.py").read_text()
    # narrow path only triggers on exactly 1 domain; >=2 unchanged, 0 refused
    assert "if len(domains) == 1:" in src
    assert "narrow_training_ok(" in src
    assert "narrow_adapter = True" in src
    # examples/habits guards still come first (unconditional)
    assert "need >= {MIN_DISTINCT_EXAMPLES} unique examples" in src
