"""Tests for refinement engines (chat + dream) — no Ollama needed.

Uses a mock LLM to verify logic without network calls.
"""

import pytest

from radiomind.core.config import Config
from radiomind.core.llm import LLMBackend, LLMResponse, LLMRouter
from radiomind.core.types import MemoryEntry, MemoryLevel
from radiomind.refinement.chat import ChatRefinement
from radiomind.refinement.dream import DreamRefinement
from radiomind.storage.database import MemoryStore
from radiomind.storage.hdc import HabitStore


class MockLLMBackend(LLMBackend):
    """Deterministic mock for testing."""

    def __init__(self, responses: dict[str, str] | None = None):
        self._responses = responses or {}
        self._default = "INSIGHT: user values consistency\nCONFIDENCE: 0.7"
        self.calls: list[str] = []

    def generate(self, prompt: str, system: str = "", model: str = "") -> LLMResponse:
        self.calls.append(prompt[:100])
        for key, resp in self._responses.items():
            if key.lower() in prompt.lower():
                return LLMResponse(text=resp, model="mock", tokens_prompt=10, tokens_completion=20)
        return LLMResponse(text=self._default, model="mock", tokens_prompt=10, tokens_completion=20)

    def is_available(self) -> bool:
        return True


def make_mock_router(responses: dict[str, str] | None = None) -> LLMRouter:
    cfg = Config()
    router = LLMRouter(cfg)
    mock = MockLLMBackend(responses)
    router._backends = {"mock": mock}
    cfg.set("llm.default_backend", "mock")
    return router


@pytest.fixture
def store(tmp_path):
    s = MemoryStore(tmp_path / "test.db")
    s.open()
    yield s
    s.close()


@pytest.fixture
def habits(tmp_path):
    h = HabitStore(tmp_path / "hdc")
    h.open()
    yield h
    h.close()


# --- Chat Refinement Tests ---

class TestChatRefinement:
    def test_refine_empty_domain(self, store, habits):
        router = make_mock_router()
        cr = ChatRefinement(store, habits, router)
        result = cr.refine(domain="empty_domain")
        assert result.duration_s >= 0

    def test_refine_with_memories(self, store, habits):
        for i in range(5):
            store.add(MemoryEntry(content=f"user fact {i}", domain="work"))

        router = make_mock_router()
        cr = ChatRefinement(store, habits, router)
        result = cr.refine(domain="work")
        assert result.duration_s > 0

    def test_parse_insights(self, store, habits):
        router = make_mock_router()
        cr = ChatRefinement(store, habits, router)
        insights = cr._parse_insights(
            "INSIGHT: user prefers autonomy\nCONFIDENCE: 0.8\nINSIGHT: user is methodical\nCONFIDENCE: 0.6"
        )
        assert len(insights) == 2
        assert insights[0].confidence == 0.8
        assert insights[1].confidence == 0.6

    def test_parse_none(self, store, habits):
        router = make_mock_router()
        cr = ChatRefinement(store, habits, router)
        insights = cr._parse_insights("NONE")
        assert len(insights) == 0

    def test_debate_calls_three_agents(self, store, habits):
        store.add(MemoryEntry(content="user likes running", domain="health"))
        router = make_mock_router({"Guardian": "consistent", "Explorer": "novel", "Reducer": "merge"})
        cr = ChatRefinement(store, habits, router)
        round_result = cr._debate_round("health")
        assert round_result.guardian_response != ""
        assert round_result.explorer_response != ""
        assert round_result.reducer_response != ""


# --- Dream Refinement Tests ---

class TestDreamRefinement:
    def test_dream_empty(self, store, habits):
        router = make_mock_router()
        dr = DreamRefinement(store, habits, router)
        result = dr.dream()
        assert result.duration_s >= 0

    def test_text_similarity(self, store, habits):
        router = make_mock_router()
        dr = DreamRefinement(store, habits, router)
        assert dr._are_similar_text("user likes running every day", "user likes running each day")
        assert not dr._are_similar_text("user likes running", "the weather is sunny")

    def test_parse_insights(self, store, habits):
        router = make_mock_router()
        dr = DreamRefinement(store, habits, router)
        insights = dr._parse_insights("INSIGHT: meta-pattern found\nCONFIDENCE: 0.4")
        assert len(insights) == 1
        assert insights[0].confidence == 0.4

    def test_wander_with_data(self, store, habits):
        habits.add_habit("values autonomy", [("user", "autonomy")])
        habits.add_habit("likes morning", [("user", "morning")])
        habits.add_habit("prefers quiet", [("user", "quiet")])

        router = make_mock_router({"unrelated": "INSIGHT: user needs calm autonomy\nCONFIDENCE: 0.5"})
        dr = DreamRefinement(store, habits, router)
        result = dr.dream()
        assert result.duration_s > 0
