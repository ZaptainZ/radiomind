"""RadioMind — main entry point. Wires all components together."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from radiomind.core.config import Config
from radiomind.core.gate import gate
from radiomind.core.llm import LLMRouter
from radiomind.core.types import (
    Habit,
    MemoryEntry,
    MemoryLevel,
    Message,
    RefinementResult,
    SearchResult,
    SelfProfile,
    UserProfile,
)
from radiomind.meta.profiles import ProfileManager
from radiomind.refinement.chat import ChatRefinement
from radiomind.refinement.dream import DreamRefinement
from radiomind.storage.database import MemoryStore
from radiomind.storage.hdc import HabitStore
from radiomind.storage.knowledge_graph import KnowledgeGraph
from radiomind.storage.pyramid import PyramidAggregator, PyramidSearch


class RadioMind:
    """Bionic memory core for AI agents.

    Usage::

        mind = RadioMind()
        mind.initialize()
        mind.ingest(messages)
        results = mind.search("query")
        mind.shutdown()
    """

    def __init__(self, config: Config | None = None, llm: Any = None):
        """Initialize RadioMind.

        Args:
            config: Configuration (loads ~/.radiomind/config.toml if None).
            llm: Optional external LLM callable with signature (prompt: str, system: str) → str.
                 When provided, RadioMind uses this instead of its own LLM config.
                 This lets host frameworks pass their existing LLM without extra config.
        """
        self.config = config or Config.load()
        self._external_llm = llm
        self._initialized = False
        self._store: MemoryStore | None = None
        self._habits: HabitStore | None = None
        self._llm: LLMRouter | None = None
        self._pyramid: PyramidSearch | None = None
        self._aggregator: PyramidAggregator | None = None
        self._chat_refine: ChatRefinement | None = None
        self._dream_refine: DreamRefinement | None = None
        self._meta: ProfileManager | None = None
        self._kg: KnowledgeGraph | None = None
        self._embedder = None

    def initialize(self, config_overrides: dict[str, Any] | None = None) -> None:
        if config_overrides:
            for k, v in config_overrides.items():
                self.config.set(k, v)

        home = self.config.home
        (home / "data").mkdir(parents=True, exist_ok=True)

        self._store = MemoryStore(self.config.db_path)
        self._store.open()

        hdc_dim = self.config.get("hdc.dim", 10000)
        self._habits = HabitStore(home / "data" / "hdc", dim=hdc_dim)
        self._habits.open()

        self._llm = self._resolve_llm()

        self._pyramid = PyramidSearch(self._store)
        self._aggregator = PyramidAggregator(self._store, self._llm)

        chat_cfg = self.config.get("refinement.chat", {})
        self._chat_refine = ChatRefinement(self._store, self._habits, self._llm, config=chat_cfg)

        dream_cfg = self.config.get("refinement.dream", {})
        self._dream_refine = DreamRefinement(self._store, self._habits, self._llm, config=dream_cfg)

        self._meta = ProfileManager(home / "data" / "meta", self.config, store=self._store)
        self._meta.open()

        self._kg = KnowledgeGraph(self.config.db_path.parent / "knowledge.db")
        self._kg.open()

        # Optional: load embedding encoder (silent fallback)
        try:
            from radiomind.storage.embedding import EmbeddingEncoder
            self._embedder = EmbeddingEncoder(home / "models" / "embedding")
            if not self._embedder.load():
                self._embedder = None
        except Exception:
            self._embedder = None

        self._initialized = True

    def shutdown(self) -> None:
        for component in (self._meta, self._kg, self._habits, self._store):
            if component is not None:
                try:
                    component.close()
                except Exception:
                    pass
        self._initialized = False

    # --- L1: Ingest ---

    def ingest(self, messages: list[Message]) -> list[MemoryEntry]:
        self._check_init()
        result = gate(messages)

        added = []
        for entry in result.entries:
            if self._embedder:
                entry.embedding = self._embedder.encode(entry.content)
            mid = self._store.add(entry)
            if mid > 0:
                added.append(entry)
        result.entries = added

        # Update user profile + knowledge graph from conversation
        for msg in messages:
            if msg.role == "user":
                self._meta.update_from_text(msg.content)
                if self._kg:
                    triples = self._kg.extract_triples_from_text(msg.content)
                    for subj, rel, obj in triples:
                        self._kg.add_triple(subj, rel, obj)

        # Check if any domain needs aggregation
        for domain in result.domains_detected:
            if self._llm.is_available():
                self._aggregator.check_and_aggregate(domain)

        return result.entries

    # --- L2: Search ---

    def search(self, query: str, domain: str | None = None) -> list[SearchResult]:
        self._check_init()
        return self._pyramid.search(query, domain=domain)

    def search_pyramid(self, query: str, start_level: int = 2) -> list[SearchResult]:
        self._check_init()
        return self._pyramid.search_pyramid(query)

    # --- L3: Habits ---

    def query_habits(self, query: str) -> list[Habit]:
        self._check_init()
        results = self._habits.query([query], top_k=5)
        return [h for h, score in results if score > 0.1]

    # --- Refinement ---

    def trigger_chat(self, domain: str | None = None) -> RefinementResult:
        self._check_init()
        result = self._chat_refine.refine(domain=domain)
        self._meta.refresh_self()
        return result

    def trigger_dream(self) -> RefinementResult:
        self._check_init()
        result = self._dream_refine.dream()
        self._meta.refresh_self()
        return result

    # --- Step Refinement (host AI drives the thinking) ---

    def refine_step(self, step: str, domain: str = "", response: str = "") -> dict:
        """Execute a single refinement step. Host AI provides the reasoning.

        This is the recommended mode when running inside CC/Codex/Hermes —
        RadioMind organizes, the host AI thinks.

        Steps for chat: prepare → guardian → explorer → reducer → synthesize
        Steps for dream: dream_prune → dream_apply, dream_wander → dream_apply
        """
        self._check_init()
        if not hasattr(self, "_step_refiner") or self._step_refiner is None:
            from radiomind.refinement.step import StepRefiner
            self._step_refiner = StepRefiner(self._store, self._habits)

        result = self._step_refiner.step(step, domain=domain, response=response)

        if result.done:
            self._meta.refresh_self()

        return {
            "step": result.step,
            "done": result.done,
            "prompt": result.prompt,
            "context": result.context,
            "next_step": result.next_step,
            "insights": result.insights,
            "actions": result.actions,
            "session": result.session_data,
        }

    # --- Training (L3 → LoRA) ---

    def generate_training_data(self, output_path: str | None = None) -> tuple[int, str]:
        """Generate JSONL training data from habits + memories."""
        self._check_init()
        from radiomind.training.data_gen import TrainingDataGenerator

        path = output_path or str(self.config.home / "models" / "train.jsonl")
        gen = TrainingDataGenerator(self._store, self._habits)
        count = gen.generate(Path(path))
        return count, path

    def train(self, **kwargs) -> "TrainResult":
        """Run LoRA fine-tuning on accumulated knowledge."""
        self._check_init()
        from radiomind.training.lora import TrainConfig, train_lora

        count, data_path = self.generate_training_data()
        if count == 0:
            from radiomind.training.lora import TrainResult
            return TrainResult(success=False, error="No training data. Ingest conversations first.")

        tc = TrainConfig.from_config(self.config)
        for k, v in kwargs.items():
            if hasattr(tc, k):
                setattr(tc, k, v)

        return train_lora(Path(data_path), tc)

    # --- Meta ---

    def get_user_profile(self) -> UserProfile:
        self._check_init()
        return self._meta.user

    def get_self_profile(self) -> SelfProfile:
        self._check_init()
        return self._meta.self_profile

    def get_context_digest(self, token_budget: int | None = None) -> str:
        self._check_init()
        budget = token_budget or self.config.get("meta.digest_token_budget", 250)
        return self._meta.get_digest(token_budget=budget)

    # --- External Knowledge (L4) ---

    def learn(self, text: str) -> list[MemoryEntry]:
        """Ingest external knowledge as L2 facts (walks same consolidation path)."""
        self._check_init()
        entry = MemoryEntry(
            content=text,
            level=MemoryLevel.FACT,
            metadata={"source": "learn", "type": "external"},
        )
        self._store.add(entry)
        return [entry]

    # --- Stats ---

    def stats(self) -> dict[str, Any]:
        self._check_init()
        db_stats = self._store.stats()
        db_stats["habits"] = self._habits.count
        db_stats["llm_available"] = self._llm.is_available()
        db_stats["llm_backends"] = self._llm.available_backends()
        db_stats["llm_usage"] = {
            "total_calls": self._llm.usage.total_calls,
            "total_tokens": self._llm.usage.total_prompt_tokens + self._llm.usage.total_completion_tokens,
        }
        db_stats["knowledge_graph_triples"] = self._kg.count() if self._kg else 0
        db_stats["embedding_available"] = self._embedder is not None
        return db_stats

    # --- Config ---

    def update_config(self, key: str, value: Any) -> None:
        self.config.set(key, value)
        self.config.save()
        if self._meta:
            self._meta.refresh_self()

    def is_llm_available(self) -> bool:
        return self._llm is not None and self._llm.is_available()

    # --- Internal ---

    def _resolve_llm(self) -> LLMRouter:
        """Resolve LLM backend with priority:
        1. Explicit llm= passed by host framework
        2. Environment variables (OPENAI_API_KEY, etc.)
        3. Local Ollama
        4. config.toml (if it has LLM config)
        5. None (pure memory mode — add/search/digest still work)
        """
        from radiomind.core.llm_auto import auto_detect

        router = LLMRouter(Config())  # empty config — don't load config.toml backends yet

        # Priority 1: explicit llm from host framework
        if self._external_llm is not None:
            detected = auto_detect(self._external_llm)
            if detected:
                router._backends["host"] = detected
                router.config.set("llm.default_backend", "host")
                return router

        # Priority 2: environment variables
        from radiomind.core.llm_auto import _from_env
        env_backend = _from_env()
        if env_backend:
            router._backends["env"] = env_backend
            router.config.set("llm.default_backend", "env")
            return router

        # Priority 3: local Ollama
        from radiomind.core.llm_auto import _from_ollama
        ollama_backend = _from_ollama()
        if ollama_backend:
            router._backends["ollama"] = ollama_backend
            router.config.set("llm.default_backend", "ollama")
            return router

        # Priority 4: config.toml (advanced users / standalone deployment)
        config_router = LLMRouter(self.config)
        if config_router.is_available():
            return config_router

        # Priority 5: no LLM — pure memory mode
        return router

    def _check_init(self) -> None:
        if not self._initialized:
            raise RuntimeError("RadioMind not initialized. Call initialize() first.")
