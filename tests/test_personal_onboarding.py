"""PersonalOnboarding-1c: Hermes provider authorization gating + readiness.

Deny-by-default is the headline: with no granted scopes the provider performs
NO background ingest / refinement / dream. Deterministic — the RadioMind
instance is stubbed; no real store, LLM, or threads-that-touch-network.
"""
from __future__ import annotations

import time

from radiomind.adapters.hermes import RadioMindProvider
from radiomind.adapters.onboarding import (
    AuthorizationState,
    HostCapabilities,
    ReadinessReport,
    readiness_report,
)


class _StubLLM:
    def is_available(self):
        return True


class _StubMind:
    """Records side effects instead of performing them."""
    def __init__(self):
        self.ingested = 0
        self.chats = 0
        self.dreams = 0
        self.learned = []
        self._llm = _StubLLM()
        self._habits = None

    def ingest(self, messages):
        self.ingested += 1

    def trigger_chat(self):
        self.chats += 1

    def trigger_dream(self):
        self.dreams += 1

    def learn(self, text):
        self.learned.append(text)

    def is_llm_available(self):
        return True


def _provider(scopes=None, caps=None):
    p = RadioMindProvider()
    p._mind = _StubMind()
    p._authz = AuthorizationState.from_iterable(scopes)
    if caps is not None:
        p._capabilities = caps
    p._auto_dream = p._authz.has("dream_after_session")
    return p


def _run_sync(p, msg="m"):
    p.sync_turn(msg, "a")
    # sync_turn spawns a daemon thread; wait briefly for it
    for _ in range(50):
        if p._mind.ingested or p._mind.chats:
            break
        time.sleep(0.01)
    time.sleep(0.02)


# ---------------- deny-by-default ----------------

def test_default_no_ingest():
    p = _provider(scopes=None)
    _run_sync(p)
    assert p._mind.ingested == 0 and p._mind.chats == 0


def test_default_no_dream():
    p = _provider(scopes=None)
    assert p._auto_dream is False
    p.on_session_end([])
    assert p._mind.dreams == 0


def test_default_no_memory_mirror():
    p = _provider(scopes=None)
    p.on_memory_write("write", "USER.md", "Alice likes tea")
    assert p._mind.learned == []


# ---------------- grants restore behavior ----------------

def test_ingest_after_grant():
    p = _provider(scopes=["ingest_new_turns"])
    _run_sync(p)
    assert p._mind.ingested == 1
    assert p._mind.chats == 0  # refinement NOT granted → still off


def test_refinement_needs_both_grants():
    p = _provider(scopes=["ingest_new_turns", "background_refinement"])
    p._mind._turn_count = 0
    for _ in range(10):
        _run_sync(p)
    assert p._mind.ingested == 10
    assert p._mind.chats == 1  # fired once at the 10th turn


def test_dream_after_grant():
    p = _provider(scopes=["dream_after_session"])
    assert p._auto_dream is True
    p.on_session_end([])
    assert p._mind.dreams == 1


def test_mirror_after_import_grant():
    p = _provider(scopes=["import_existing_memory"])
    p.on_memory_write("write", "USER.md", "Alice likes tea")
    assert p._mind.learned == ["[hermes/USER.md] Alice likes tea"]


# ---------------- initialize backward-compat / kwargs ----------------

def test_initialize_accepts_caps_dict_and_scopes():
    import radiomind.adapters.hermes as H

    class _M:
        def initialize(self): pass
    # monkeypatch RadioMind to avoid real init
    orig = H.RadioMind
    H.RadioMind = lambda config=None, llm=None: _M()
    try:
        p = RadioMindProvider()
        p.initialize("sess",
                     capabilities={"host_name": "hermes", "can_import_memory": True,
                                   "bogus_field": 1},
                     authorized_scopes=["ingest_new_turns", "not_a_scope"])
        assert p._capabilities.host_name == "hermes"
        assert p._capabilities.can_import_memory is True
        assert p._authz.has("ingest_new_turns")
        assert not p._authz.has("not_a_scope")  # unknown scope dropped
    finally:
        H.RadioMind = orig


def test_old_initialize_no_scopes_is_conservative():
    import radiomind.adapters.hermes as H

    class _M:
        def initialize(self): pass
    orig = H.RadioMind
    H.RadioMind = lambda config=None, llm=None: _M()
    try:
        p = RadioMindProvider()
        p.initialize("sess")  # old-style call, no caps/scopes
        assert p._authz.granted == frozenset()
        assert p._auto_dream is False
    finally:
        H.RadioMind = orig


# ---------------- readiness_report (pure) ----------------

def test_readiness_conservative_defaults():
    r = readiness_report(None, None, llm_available=False)
    assert isinstance(r, ReadinessReport)
    assert r.host_llm == "missing"
    assert r.retrieval == "fts_only"
    assert r.background_hooks == "unsupported"
    assert r.lora == "disabled"
    assert r.privacy_status == "local_only"
    assert "host LLM" in r.recommended_next_action


def test_readiness_escalates_with_grants():
    caps = HostCapabilities(has_host_llm=True, can_import_memory=True,
                            supports_background_hooks=True,
                            has_embedding_provider=True)
    az = AuthorizationState.from_iterable([
        "import_existing_memory", "ingest_new_turns", "background_refinement",
        "enable_background_hooks", "call_external_embedding", "train_lora",
    ])
    r = readiness_report(caps, az, llm_available=True,
                         habit_count=6, example_count=40)
    assert r.host_llm == "ready"
    assert r.memory_import == "ready"
    assert r.retrieval == "local_ready"
    assert r.background_hooks == "authorized"
    assert r.lora == "ready"
    assert r.privacy_status == "external_calls_authorized"


def test_readiness_lora_needs_more_data():
    az = AuthorizationState.from_iterable(["train_lora"])
    r = readiness_report(HostCapabilities(), az, llm_available=True,
                         habit_count=2, example_count=5)
    assert r.lora == "needs_more_data"


def test_provider_readiness_method():
    p = _provider(scopes=["ingest_new_turns"])
    rep = p.readiness()
    assert rep["host_llm"] == "ready"  # stub llm available
    assert rep["privacy_status"] == "local_only"
