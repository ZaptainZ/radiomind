"""TrinityErrorVisibility-1a: refinement LLM-call swallow points stay
control-flow-identical (return ""/None/[]/skip) BUT emit a diagnostic
warning first. Deterministic — raising stub LLMs, no network.

Regression target: the LLMRouter-1b debugging stalled on trinity._call_llm
swallowing a 45s timeout into "" with no trace.
"""
from __future__ import annotations

import logging

from radiomind.core.types import Habit, MemoryEntry, MemoryStatus
from radiomind.refinement import trinity
from radiomind.refinement.dream import DreamRefinement
from radiomind.refinement.decompose import QueryDecomposer


class _Resp:
    def __init__(self, text):
        self.text = text


class _RaisingLLM:
    """has .generate that raises — mimics a backend timeout/HTTP error."""
    name = "stub-backend"

    def generate(self, prompt, system=""):
        raise TimeoutError("read operation timed out")

    def is_available(self):
        return True


# ---------------- trinity._call_llm ----------------

def test_call_llm_swallows_to_empty_but_warns(caplog):
    with caplog.at_level(logging.WARNING, logger="radiomind.refinement.trinity"):
        out = trinity._call_llm("a prompt", _RaisingLLM(), stage="answerer/round1")
    assert out == ""  # control flow unchanged
    recs = [r for r in caplog.records if "LLM call failed" in r.message]
    assert len(recs) == 1
    msg = recs[0].message
    assert "answerer/round1" in msg          # stage
    assert "TimeoutError" in msg             # exception type
    assert "stub-backend" in msg             # backend label
    assert "prompt_len=8" in msg             # input size


def test_call_llm_success_no_warning(caplog):
    class _OK:
        def generate(self, prompt, system=""):
            return _Resp('{"x":1}')
    with caplog.at_level(logging.WARNING, logger="radiomind.refinement.trinity"):
        out = trinity._call_llm("p", _OK())
    assert out == '{"x":1}'
    assert not [r for r in caplog.records if "LLM call failed" in r.message]


# ---------------- trinity._parse_json ----------------

def test_parse_json_junk_warns_returns_none(caplog):
    with caplog.at_level(logging.WARNING, logger="radiomind.refinement.trinity"):
        out = trinity._parse_json("this is not json at all", stage="critic/round2")
    assert out is None
    recs = [r for r in caplog.records if "JSON parse failed" in r.message]
    assert len(recs) == 1 and "critic/round2" in recs[0].message


def test_parse_json_empty_raw_no_warning(caplog):
    # empty raw == _call_llm already warned; don't double-log
    with caplog.at_level(logging.WARNING, logger="radiomind.refinement.trinity"):
        out = trinity._parse_json("", stage="x")
    assert out is None
    assert not [r for r in caplog.records if "JSON parse failed" in r.message]


def test_parse_json_valid_no_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="radiomind.refinement.trinity"):
        out = trinity._parse_json('{"final_answer": "yes", "stances": []}')
    assert out == {"final_answer": "yes", "stances": []}
    assert not caplog.records


# ---------------- _describe_llm ----------------

def test_describe_llm_prefers_config_backend():
    class _Router:
        class _Cfg:
            def get(self, k, default=None):
                return "dashscope" if k == "llm.default_backend" else default
        config = _Cfg()
    assert trinity._describe_llm(_Router()) == "dashscope"


def test_describe_llm_falls_back_to_name_then_type():
    assert trinity._describe_llm(_RaisingLLM()) == "stub-backend"
    assert trinity._describe_llm(object()) == "object"


# ---------------- dream._merge_pair ----------------

class _StubStore:
    def __init__(self):
        self.updated, self.archived = [], []

    def update(self, e):
        self.updated.append(e)

    def archive(self, mid):
        self.archived.append(mid)


def _entry(mid, content):
    e = MemoryEntry(content=content)
    e.id = mid
    return e


def test_dream_merge_swallow_warns(caplog):
    store = _StubStore()
    dr = DreamRefinement(store=store, habits=None, llm=_RaisingLLM())
    a, b = _entry(1, "[user] I hike often"), _entry(2, "[user] I hike a lot")
    with caplog.at_level(logging.WARNING, logger="radiomind.refinement.dream"):
        out = dr._merge_pair(a, b)
    assert out is None                       # control flow unchanged
    assert store.updated == [] and store.archived == []
    recs = [r for r in caplog.records if "dream merge LLM call failed" in r.message]
    assert len(recs) == 1
    assert "dream/merge" in recs[0].message and "TimeoutError" in recs[0].message


# ---------------- decompose() LLM swallow ----------------

class _Result:
    def __init__(self, content):
        self.entry = MemoryEntry(content=content)


def test_decompose_swallow_warns(caplog):
    dec = QueryDecomposer(store=_StubStore(), llm=_RaisingLLM())
    results = [_Result("guitars: I own three guitars and a bass")]
    with caplog.at_level(logging.WARNING, logger="radiomind.refinement.decompose"):
        out = dec.decompose("how many guitars do I own", results,
                            domain="music", focus="guitars")
    assert out == []                         # control flow unchanged
    recs = [r for r in caplog.records if "decompose LLM call failed" in r.message]
    assert len(recs) == 1
    assert "stage=decompose" in recs[0].message and "TimeoutError" in recs[0].message


# ---------------- dream._wander LLM swallow ----------------

class _Princ:
    def __init__(self, content):
        self.content = content
        self.domain = "d"


class _WanderStore(_StubStore):
    def list_by_level(self, level, limit=20):
        from radiomind.core.types import MemoryLevel
        if level == MemoryLevel.PRINCIPLE:
            return [_Princ(f"principle {i}") for i in range(3)]
        return []


class _Habits:
    def all_habits(self):
        return []


def test_dream_wander_swallow_warns(caplog):
    from radiomind.refinement.dream import DreamJournal
    dr = DreamRefinement(store=_WanderStore(), habits=_Habits(), llm=_RaisingLLM())
    j = DreamJournal()
    with caplog.at_level(logging.WARNING, logger="radiomind.refinement.dream"):
        dr._wander(j)                        # must not raise
    assert j.insights == []                  # control flow unchanged
    recs = [r for r in caplog.records if "dream wander LLM call failed" in r.message]
    assert len(recs) == 1 and "dream/wander" in recs[0].message
