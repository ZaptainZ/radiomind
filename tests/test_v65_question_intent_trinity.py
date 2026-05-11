"""Tests for V6.5: question-intent trinity (题干侧拆解).

V6.5 puts trinity on QUESTION side, not answer side. Stance library
+ dynamic n_stances per query features. Outputs QuestionIntent
(structured signature) that conditions the answer prompt.

Critical avoid-V6.4-B-self-pollution: QuestionIntent is structured
fields, not free-form profile. Generator/consumer LLMs see
different content.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from radiomind.core.attention import (
    QuestionIntent,
    _STANCE_LIBRARY,
    _select_intent_stances,
    analyze,
    analyze_question_intent_with_trinity,
    format_intent_directive,
)


class _SequenceStubLLM:
    def __init__(self, responses):
        self._seq = [json.dumps(r) if isinstance(r, dict) else r for r in responses]
        self.calls = 0

    def is_available(self) -> bool:
        return True

    def generate(self, prompt, system=""):
        idx = min(self.calls, len(self._seq) - 1)
        self.calls += 1
        r = SimpleNamespace()
        r.text = self._seq[idx]
        return r


def _intent_response(
    granularity: str = "specific_entity",
    answer_form: str = "name",
    focus_type: str | None = None,
    literal: str = "",
    semantic: str = "",
    n_stances: int = 2,
    directive_applicability: float = 0.85,
) -> dict:
    """Build a canned LLM response with N stance objects.

    V6.5.1: directive_applicability defaults high (0.85) so existing
    tests stay green; tests that exercise low-applicability gating
    pass an explicit low value.
    """
    return {
        "stances": [
            {"name": f"stance{i}", "emphasis": "x",
             "conclusion": "x", "confidence": 0.85}
            for i in range(n_stances)
        ],
        "final_answer": f"granularity={granularity}, form={answer_form}",
        "confidence": 0.85,
        "literal_target": literal or "literal X",
        "semantic_target": semantic or "semantic X",
        "expected_granularity": granularity,
        "answer_form": answer_form,
        "focus_entity_type": focus_type,
        "directive_applicability": directive_applicability,
    }


# === Stance selection (dynamic, not hardcoded) ===


def test_stance_selection_minimum_2_for_basic_query():
    """Even a basic query gets literal-target + semantic-target."""
    sig = analyze("Just a simple question.")
    stances = _select_intent_stances("Just a simple question.", sig)
    assert "literal-target" in stances
    assert "semantic-target" in stances
    assert len(stances) >= 2


def test_stance_selection_abstract_query_adds_granularity():
    """'about' marker → +granularity-check stance."""
    sig = analyze("What is Nate's favorite book series about?")
    stances = _select_intent_stances("What is Nate's favorite book series about?", sig)
    assert "granularity-check" in stances


def test_stance_selection_direction_query_adds_direction():
    """'might X's status be' → +direction-check stance."""
    sig = analyze("What might John's financial status be?")
    stances = _select_intent_stances("What might John's financial status be?", sig)
    assert "direction-check" in stances


def test_stance_selection_entity_query_adds_entity_type():
    """'Which X' → +entity-type-check stance."""
    sig = analyze("Which national park did they visit?")
    stances = _select_intent_stances("Which national park did they visit?", sig)
    assert "entity-type-check" in stances


def test_stance_selection_temporal_query_adds_temporal_precision():
    """'When did X' → +temporal-precision-check stance."""
    sig = analyze("When did John move to Boston?")
    stances = _select_intent_stances("When did John move to Boston?", sig)
    assert "temporal-precision-check" in stances


def test_stance_selection_complex_inference_query_adds_check():
    """Long inference query → +complex-inference-check stance."""
    q = "What might Nate consider as an alternative career after gaming if he wanted a change?"
    sig = analyze(q)
    stances = _select_intent_stances(q, sig)
    assert "complex-inference-check" in stances


def test_stance_selection_caps_at_5():
    """Many triggers fire but selection caps at 5 stances."""
    q = "Which X might X's status be about when did X if X considers Y?"
    sig = analyze(q)
    stances = _select_intent_stances(q, sig)
    assert len(stances) <= 5


# === analyze_question_intent_with_trinity — consistency + abstain ===


def test_intent_returns_none_when_no_llm():
    assert analyze_question_intent_with_trinity("any query", llm=None) is None


def test_intent_returns_none_when_llm_unavailable():
    class _DownLLM:
        def is_available(self): return False
    assert analyze_question_intent_with_trinity("any query", llm=_DownLLM()) is None


def test_intent_consistent_returns_signature():
    """Both calls agree on granularity + form → return signature."""
    llm = _SequenceStubLLM([
        _intent_response(granularity="concept", answer_form="topic"),
        _intent_response(granularity="concept", answer_form="topic"),
    ])
    out = analyze_question_intent_with_trinity(
        "What is Nate's favorite book series about?", llm=llm,
    )
    assert out is not None
    assert out.expected_granularity == "concept"
    assert out.answer_form == "topic"
    assert "literal-target" in out.stances_used
    assert "granularity-check" in out.stances_used


def test_intent_inconsistent_granularity_returns_none():
    """Call 1 says 'concept', call 2 says 'specific_entity' → abstain."""
    llm = _SequenceStubLLM([
        _intent_response(granularity="concept", answer_form="topic"),
        _intent_response(granularity="specific_entity", answer_form="name"),
    ])
    out = analyze_question_intent_with_trinity(
        "What is X about?", llm=llm,
    )
    assert out is None


def test_intent_inconsistent_form_returns_none():
    """Same granularity but different form → still abstain."""
    llm = _SequenceStubLLM([
        _intent_response(granularity="concept", answer_form="topic"),
        _intent_response(granularity="concept", answer_form="list"),
    ])
    out = analyze_question_intent_with_trinity(
        "What is X about?", llm=llm,
    )
    assert out is None


def test_intent_both_parse_failed_returns_none():
    """Both calls return invalid JSON → None."""
    llm = _SequenceStubLLM(["not valid json {", "also not valid"])
    out = analyze_question_intent_with_trinity("X?", llm=llm)
    assert out is None


# === V6.5.1: directive_applicability self-gating ===


def test_intent_low_applicability_returns_none():
    """Both calls agree on fields but applicability < 0.6 → None (abstain)."""
    llm = _SequenceStubLLM([
        _intent_response(granularity="specific_entity", answer_form="number",
                         directive_applicability=0.3),
        _intent_response(granularity="specific_entity", answer_form="number",
                         directive_applicability=0.3),
    ])
    out = analyze_question_intent_with_trinity(
        "How many writings made it to the big screen?", llm=llm,
    )
    assert out is None  # trinity self-says directive would not help


def test_intent_high_applicability_returns_signature():
    """High applicability → emit intent (with applicability field)."""
    llm = _SequenceStubLLM([
        _intent_response(granularity="concept", answer_form="topic",
                         directive_applicability=0.85),
        _intent_response(granularity="concept", answer_form="topic",
                         directive_applicability=0.85),
    ])
    out = analyze_question_intent_with_trinity(
        "What is X's favorite series about?", llm=llm,
    )
    assert out is not None
    assert out.directive_applicability == 0.85


def test_intent_borderline_applicability_averaged():
    """One call 0.55, other 0.65 → avg 0.60 boundary, just emits."""
    llm = _SequenceStubLLM([
        _intent_response(granularity="concept", answer_form="topic",
                         directive_applicability=0.55),
        _intent_response(granularity="concept", answer_form="topic",
                         directive_applicability=0.65),
    ])
    out = analyze_question_intent_with_trinity(
        "What is X about?", llm=llm,
    )
    assert out is not None
    assert abs(out.directive_applicability - 0.60) < 0.01


def test_intent_applicability_below_threshold_avg_abstains():
    """Avg slightly below 0.6 → abstain."""
    llm = _SequenceStubLLM([
        _intent_response(granularity="concept", answer_form="topic",
                         directive_applicability=0.5),
        _intent_response(granularity="concept", answer_form="topic",
                         directive_applicability=0.6),
    ])
    out = analyze_question_intent_with_trinity(
        "What is X about?", llm=llm,
    )
    assert out is None  # avg 0.55 < 0.6 threshold


# === format_intent_directive — prompt rendering ===


def test_format_directive_none_returns_empty():
    assert format_intent_directive(None) == ""


def test_format_directive_default_returns_empty():
    """Sentence form + description granularity = default, no directive."""
    intent = QuestionIntent(
        literal_target="x", semantic_target="x",
        expected_granularity="description",
        answer_form="sentence",
        focus_entity_type=None,
    )
    assert format_intent_directive(intent) == ""


def test_format_directive_concept_mentions_theme():
    intent = QuestionIntent(
        literal_target="x", semantic_target="x",
        expected_granularity="concept",
        answer_form="topic",
        focus_entity_type=None,
    )
    out = format_intent_directive(intent)
    assert "QUESTION INTENT" in out
    assert "CONCEPT" in out or "THEME" in out
    assert "TOPIC" in out


def test_format_directive_direction_mentions_judgment():
    intent = QuestionIntent(
        literal_target="x", semantic_target="x",
        expected_granularity="direction",
        answer_form="judgment",
        focus_entity_type=None,
    )
    out = format_intent_directive(intent)
    assert "JUDGMENT" in out
    assert "VERDICT" in out


def test_format_directive_category_mentions_kind():
    intent = QuestionIntent(
        literal_target="x", semantic_target="x",
        expected_granularity="category",
        answer_form="name",
        focus_entity_type=None,
    )
    out = format_intent_directive(intent)
    assert "CATEGORY" in out
    assert "specific instance" in out.lower() or "kind/type" in out.lower()


# === Library extensibility (no main-flow change to add a stance) ===


def test_stance_library_is_dict_with_required_fields():
    """New stances added by appending to _STANCE_LIBRARY dict."""
    for name, entry in _STANCE_LIBRARY.items():
        assert isinstance(name, str)
        assert "desc" in entry and isinstance(entry["desc"], str)
        assert "trigger" in entry and callable(entry["trigger"])


def test_dynamic_n_stances_by_query_features():
    """Different queries → different stance counts."""
    sig_simple = analyze("plain query")
    sig_complex = analyze("What might John's financial status be about when did this happen?")
    n_simple = len(_select_intent_stances("plain query", sig_simple))
    n_complex = len(_select_intent_stances(
        "What might John's financial status be about when did this happen?",
        sig_complex,
    ))
    assert n_complex > n_simple  # complex query triggers more stances
