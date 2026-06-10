"""DreamMergeRolePrefix-1a: dream's redundancy merge must preserve the
"[user]/[assistant]" role prefix and must refuse cross-role merges.

Deterministic — stub store/LLM, no network, no real DB.
Origin-3b probe evidence: _merge_pair rewrote "[assistant] It is
undeniable..." into prefix-less text and merged a user turn into an
assistant turn (ids 527→528), corrupting the role-tagged format that
SelfAnchor user-turn scans and the answer prompt rely on.
"""
from __future__ import annotations

from radiomind.refinement.dream import DreamRefinement, split_role_prefix
from radiomind.core.types import MemoryEntry


class _Resp:
    def __init__(self, text: str):
        self.text = text


class _StubLLM:
    def __init__(self, reply: str):
        self.reply = reply
        self.prompts: list[str] = []

    def generate(self, prompt: str, system: str = ""):
        self.prompts.append(prompt)
        return _Resp(self.reply)


class _StubStore:
    def __init__(self):
        self.updated: list[MemoryEntry] = []
        self.archived: list[int] = []

    def update(self, entry):
        self.updated.append(entry)

    def archive(self, mem_id):
        self.archived.append(mem_id)


def _refiner(store, llm):
    return DreamRefinement(store=store, habits=None, llm=llm)


def _entry(mem_id: int, content: str) -> MemoryEntry:
    e = MemoryEntry(content=content)
    e.id = mem_id
    return e


# ---------------- split_role_prefix ----------------

def test_split_role_prefix_tagged():
    assert split_role_prefix("[user] hello there") == ("user", "hello there")
    assert split_role_prefix("[assistant] hi") == ("assistant", "hi")


def test_split_role_prefix_untagged_and_edge():
    assert split_role_prefix("no tag here") == (None, "no tag here")
    assert split_role_prefix("") == (None, "")
    # bracketed text mid-sentence is not a prefix
    assert split_role_prefix("see [user] later") == (None, "see [user] later")


# ---------------- same-role merge keeps the prefix ----------------

def test_same_role_merge_preserves_prefix():
    store, llm = _StubStore(), _StubLLM("merged body without prefix")
    a = _entry(1, "[user] I hiked 3 miles on Saturday")
    b = _entry(2, "[user] On Saturday I did a 3-mile hike")
    merged = _refiner(store, llm)._merge_pair(a, b)
    assert merged == "[user] merged body without prefix"
    assert a.content == merged
    assert store.archived == [2]
    # the LLM never saw the prefixes — bodies only
    assert "[user]" not in llm.prompts[0]


def test_llm_echoing_prefix_is_not_doubled():
    store, llm = _StubStore(), _StubLLM("[user] merged body")
    a = _entry(1, "[user] fact one")
    b = _entry(2, "[user] fact one again")
    merged = _refiner(store, llm)._merge_pair(a, b)
    assert merged == "[user] merged body"


# ---------------- cross-role merge is refused ----------------

def test_cross_role_merge_refused_no_mutation():
    store, llm = _StubStore(), _StubLLM("should never be used")
    a = _entry(1, "[assistant] It is true that the church used fear")
    b = _entry(2, "[user] But didn't the church also use fear")
    merged = _refiner(store, llm)._merge_pair(a, b)
    assert merged is None
    assert store.updated == [] and store.archived == []
    assert llm.prompts == []           # refused before any LLM call
    assert a.content.startswith("[assistant] ")


def test_tagged_with_untagged_refused():
    store, llm = _StubStore(), _StubLLM("x")
    a = _entry(1, "[user] tagged")
    b = _entry(2, "untagged memory")
    assert _refiner(store, llm)._merge_pair(a, b) is None
    assert store.archived == []


# ---------------- untagged pair behaves as before ----------------

def test_untagged_pair_merges_plainly():
    store, llm = _StubStore(), _StubLLM("combined memory")
    a = _entry(1, "likes morning runs")
    b = _entry(2, "enjoys running in the morning")
    merged = _refiner(store, llm)._merge_pair(a, b)
    assert merged == "combined memory"
    assert store.archived == [2]


def test_empty_llm_reply_no_mutation():
    store, llm = _StubStore(), _StubLLM("   ")
    a = _entry(1, "[user] a")
    b = _entry(2, "[user] b")
    assert _refiner(store, llm)._merge_pair(a, b) is None
    assert store.updated == [] and store.archived == []
