"""Tests for V6.5.2: trinity.debate `agent_role` parameter.

agent 侧写 is now a first-class trinity parameter. Roles are
registered in `_AGENT_ROLES`; default 'answerer' preserves V5
behavior. New 'question-intent-analyzer' role explicitly tells the
LLM it is decomposing a question, not answering it — preventing the
V5 "abstain on thin evidence" instruction from misfiring on
question-only inputs.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from radiomind.refinement.trinity import _AGENT_ROLES, debate


class _CaptureLLM:
    """Records every prompt sent so tests can assert what the LLM saw."""

    def __init__(self, canned: dict | str):
        self._text = canned if isinstance(canned, str) else json.dumps(canned)
        self.prompts: list[str] = []

    def is_available(self) -> bool:
        return True

    def generate(self, prompt, system=""):
        self.prompts.append(prompt)
        r = SimpleNamespace()
        r.text = self._text
        return r


def _ok_response(final: str = "x", confidence: float = 0.85) -> dict:
    return {
        "stances": [
            {"name": "s0", "emphasis": "e", "conclusion": "c", "confidence": 0.9},
            {"name": "s1", "emphasis": "e", "conclusion": "c", "confidence": 0.9},
            {"name": "s2", "emphasis": "e", "conclusion": "c", "confidence": 0.9},
        ],
        "final_answer": final,
        "confidence": confidence,
    }


# === Library shape ===


def test_agent_roles_library_has_required_roles():
    assert "answerer" in _AGENT_ROLES
    assert "question-intent-analyzer" in _AGENT_ROLES


def test_answerer_preamble_mentions_answer():
    assert "answer" in _AGENT_ROLES["answerer"].lower()


def test_question_intent_analyzer_preamble_forbids_abstain():
    """Critical: V6.5.2 fix — the preamble explicitly forbids 'insufficient'."""
    text = _AGENT_ROLES["question-intent-analyzer"].lower()
    # word-stem match: characteriz* covers characterize / characterization /
    # characterizable; decompos* covers decompose / decomposition.
    assert "decompos" in text or "characteriz" in text
    assert "not to answer" in text or "not an answerer" in text
    assert "insufficient" in text  # mentioned (as forbidden)


def test_question_intent_analyzer_v653_strengthening():
    """V6.5.3: the preamble explicitly forbids conclusion-typed stance themes."""
    text = _AGENT_ROLES["question-intent-analyzer"].lower()
    # Must call out the linguist/syntactician framing
    assert "linguist" in text or "syntactician" in text
    # Must explicitly name forbidden stance themes
    forbidden_themes = ["missing entity", "ambiguity", "skeptic", "cannot resolve"]
    for theme in forbidden_themes:
        assert theme in text, f"preamble must explicitly forbid '{theme}' stance theme"
    # Must include examples of correct execution
    assert "✓" in _AGENT_ROLES["question-intent-analyzer"]
    assert "✗" in _AGENT_ROLES["question-intent-analyzer"]


# === Default behavior preserved ===


def test_default_agent_role_is_answerer():
    """No agent_role passed → answerer preamble emitted (V5 behavior)."""
    llm = _CaptureLLM(_ok_response())
    debate(task="x", evidence="y", llm=llm)
    assert len(llm.prompts) == 1
    p = llm.prompts[0]
    assert "triangulate an answer" in p
    assert "abstain" in p


def test_explicit_answerer_role_emits_same_preamble():
    llm = _CaptureLLM(_ok_response())
    debate(task="x", evidence="y", llm=llm, agent_role="answerer")
    assert "triangulate an answer" in llm.prompts[0]


# === New role swaps preamble ===


def test_question_intent_analyzer_swaps_preamble():
    """V6.5.2: this role makes the prompt say 'decompose, not answer'."""
    llm = _CaptureLLM(_ok_response())
    debate(task="x", evidence="(question-only)\nQ?", llm=llm,
           agent_role="question-intent-analyzer")
    p = llm.prompts[0].lower()
    # 'triangulate an answer' from default MUST be gone
    assert "triangulate an answer" not in p
    # The intent-analyzer language must be present (stem match)
    assert "decompos" in p or "characteriz" in p
    assert "not to answer" in p or "not an answerer" in p


def test_question_intent_analyzer_omits_thin_evidence_abstain_instruction():
    """The default prompt instructs LLM to 'abstain when evidence is thin'.
    The intent-analyzer role must NOT carry that instruction (it's exactly
    what broke V6.5: question-only evidence → abstain misfire).
    """
    llm = _CaptureLLM(_ok_response())
    debate(task="x", evidence="(question-only)", llm=llm,
           agent_role="question-intent-analyzer")
    p = llm.prompts[0].lower()
    # The forbidden V5 instruction is "when evidence is thin, abstain"
    assert "evidence is thin, abstain" not in p


# === Unknown role falls back gracefully ===


def test_unknown_role_used_as_literal_preamble():
    """Unknown role name → treated as literal preamble (custom one-off)."""
    custom_preamble = "You are a TEST agent for unit testing only."
    llm = _CaptureLLM(_ok_response())
    debate(task="x", evidence="y", llm=llm, agent_role=custom_preamble)
    assert "TEST agent for unit testing" in llm.prompts[0]
