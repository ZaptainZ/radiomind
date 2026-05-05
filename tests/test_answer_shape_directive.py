"""Tests for `mind.answer_shape_directive` — wiring AttentionSignature's
`answer_shape` field into the final answer prompt.

This was a previously-undriven attention field — the shape was computed
inside `analyze()` but never reached the answer LLM. Now exposed as a
public method that returns a one-line guidance block based on the
shape category. Bench harness prepends it to the answer prompt.

Closes the GAP for judge-stringency edge cases where the model's
extra filler ("100 more points") gets judged ≠ gold ("100").
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def sandbox(monkeypatch):
    tmp = tempfile.mkdtemp(prefix="rm-shape-")
    monkeypatch.setenv("RADIOMIND_HOME", tmp)
    yield Path(tmp)


@pytest.fixture
def mind(sandbox):
    from radiomind import RadioMind
    m = RadioMind()
    m.initialize()
    yield m
    m.shutdown()


def test_count_question_returns_number_directive(mind):
    """'How many X' → wants=count, answer_shape=number → directive present."""
    out = mind.answer_shape_directive("How many points do I need to redeem a free product?")
    assert out, "expected a directive for count question"
    assert "ANSWER SHAPE" in out
    assert "integer count" in out.lower() or "number" in out.lower()


def test_amount_question_returns_amount_directive(mind):
    """'how much money in total' → answer_shape=amount → currency directive."""
    out = mind.answer_shape_directive("How much money did I donate in total?")
    assert out, "expected an amount directive"
    assert "ANSWER SHAPE" in out
    assert "$" in out or "dollar" in out.lower()


def test_duration_question_returns_duration_directive(mind):
    """'How long has X' → wants=date, answer_shape=duration."""
    out = mind.answer_shape_directive("How long have I been working at Google?")
    assert out, "expected duration directive"
    assert "duration" in out.lower() or "weeks" in out.lower() or "months" in out.lower()


def test_relative_offset_returns_offset_directive(mind):
    """'How many days ago' → answer_shape=relative_offset."""
    out = mind.answer_shape_directive("How many days ago did I buy the smoker?")
    # "how many days ago" → date wants, relative_offset shape
    assert out, "expected directive for relative-offset question"
    assert "ANSWER SHAPE" in out


def test_factual_lookup_returns_no_constraint(mind):
    """Plain lookup 'what was X' → answer_shape=sentence (default) → empty."""
    out = mind.answer_shape_directive("What was my last meal yesterday?")
    # sentence shape = no override
    assert out == ""


def test_no_query_returns_empty(mind):
    """Empty/None query → empty directive."""
    out = mind.answer_shape_directive("")
    assert out == ""


def test_named_entity_lookup_returns_entity_directive(mind):
    """'Who was X' / 'Which book did X' → wants=detail, possibly named_entity."""
    out = mind.answer_shape_directive("Which book did the bookstore recommend?")
    # may or may not match named_entity depending on regex; accept either
    # — this test just confirms the function doesn't crash on this shape
    assert isinstance(out, str)


def test_directive_skipped_when_attention_router_off(mind, monkeypatch):
    """RADIOMIND_ATTENTION_ROUTER=off disables the directive."""
    monkeypatch.setenv("RADIOMIND_ATTENTION_ROUTER", "off")
    out = mind.answer_shape_directive("How many guitars do I own?")
    assert out == ""
