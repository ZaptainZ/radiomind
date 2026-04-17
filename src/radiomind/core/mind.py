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
    SearchResponse,
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

        # Load embedder FIRST so PyramidSearch can use it. Local ONNX MiniLM
        # is preferred (fast, offline). When it can't load (typically missing
        # `tokenizers` wheel in constrained sandboxes), fall through to the
        # DashScope embedding API if credentials are present — better than
        # FTS-only, same float32-bytes contract.
        try:
            from radiomind.storage.embedding import EmbeddingEncoder
            self._embedder = EmbeddingEncoder(home / "models" / "embedding")
            if not self._embedder.load():
                self._embedder = None
        except Exception:
            self._embedder = None
        if self._embedder is None:
            try:
                oc = self.config.get("llm.openai", {}) or {}
                base = (oc.get("base_url") or "").strip()
                key = (oc.get("api_key") or "").strip()
                if base and key and "dashscope" in base.lower():
                    from radiomind.storage.embedding_dashscope import DashScopeEmbedder
                    ds = DashScopeEmbedder(base, key)
                    if ds.load():
                        self._embedder = ds
            except Exception:
                pass

        # Reranker — opt-in via config (off by default: 2.3GB download,
        # ~30ms/query latency). When present, gives the retrieval pipeline
        # its last +10-20% R@5 by cross-encoder rescoring of top-20 RRF.
        # Fallback order: local BGE (offline, fast) → DashScope gte-rerank-v2
        # (API, no torch needed) → none.
        self._reranker = None
        if self.config.get("retrieval.reranker.enabled", False):
            try:
                from radiomind.storage.reranker import CrossEncoderReranker
                model_id = self.config.get("retrieval.reranker.model", "BAAI/bge-reranker-v2-m3")
                # cache_dir=None → use HF default cache (~/.cache/huggingface/hub),
                # which the user may have populated manually with bge-reranker-v2-m3.
                # Avoids re-downloading the 2.3GB model per sandbox.
                r = CrossEncoderReranker(model_id=model_id, cache_dir=None)
                if r.load():
                    self._reranker = r
            except Exception:
                self._reranker = None
            if self._reranker is None:
                try:
                    oc = self.config.get("llm.openai", {}) or {}
                    base = (oc.get("base_url") or "").strip()
                    key = (oc.get("api_key") or "").strip()
                    if base and key and "dashscope" in base.lower():
                        from radiomind.storage.reranker_dashscope import DashScopeReranker
                        rr = DashScopeReranker(api_key=key)
                        if rr.load():
                            self._reranker = rr
                except Exception:
                    pass

        # Query rewriter — opt-in; uses LLMRouter to produce 2-3 paraphrases
        # per search. Trades ~200-500ms latency for recall gains on tough
        # queries (preference, multi-hop).
        self._query_rewriter = None
        if self.config.get("retrieval.query_rewriter.enabled", False):
            try:
                from radiomind.storage.query_rewriter import QueryRewriter
                def _llm_fn(prompt: str) -> str:
                    resp = self._llm.generate(prompt, system="You rewrite search queries.")
                    return resp.text
                self._query_rewriter = QueryRewriter(
                    llm_fn=_llm_fn,
                    cache_path=home / "data" / "query_rewrite_cache.json",
                )
            except Exception:
                self._query_rewriter = None

        # KG must open BEFORE pyramid so pyramid can route temporal/entity
        # queries through the structured store.
        self._kg = KnowledgeGraph(self.config.db_path.parent / "knowledge.db")
        self._kg.open()

        self._pyramid = PyramidSearch(
            self._store,
            embedder=self._embedder,
            reranker=self._reranker,
            query_rewriter=self._query_rewriter,
            kg=self._kg,
        )
        self._aggregator = PyramidAggregator(self._store, self._llm)

        chat_cfg = self.config.get("refinement.chat", {})
        self._chat_refine = ChatRefinement(self._store, self._habits, self._llm, config=chat_cfg)

        dream_cfg = self.config.get("refinement.dream", {})
        self._dream_refine = DreamRefinement(self._store, self._habits, self._llm, config=dream_cfg)

        self._meta = ProfileManager(
            home / "data" / "meta", self.config,
            store=self._store, habits=self._habits,
        )
        self._meta.open()

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

    def ingest(
        self,
        messages: list[Message],
        user_id: str = "",
        agent_id: str = "",
        session_id: str = "",
    ) -> list[MemoryEntry]:
        self._check_init()
        result = gate(messages)

        added = []
        for entry in result.entries:
            entry.user_id = user_id
            entry.agent_id = agent_id
            entry.session_id = session_id
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

    def ingest_turns_raw(
        self,
        turns: list[dict],
        domain: str = "",
        user_id: str = "",
        agent_id: str = "",
        session_id: str = "",
        run_aggregation: bool = True,
        run_refinement: bool = False,
    ) -> dict:
        """Bulk-ingest raw conversation turns preserving everything.

        Unlike ingest(), this skips the L1 EXTRACTION_PATTERNS gate — which
        is right for real-time Claude-Code-style monitoring (only keep
        "我叫 X"/"I prefer Y" style statements) but wrong for benchmarks,
        migrations, and bulk data loads where every turn carries context
        the retrieval layer later needs. Full upstream pipeline still runs:

          1. Store each turn as L2 FACT (embedding, metadata preserved)
          2. Extract KG triples from user turns
          3. Update Meta profile
          4. Run L2 aggregation per domain (facts → patterns → principles)
          5. Optional: trigger chat refinement (three-body debate → L3 habits)

        turns: list of {"content": str, "role": str, "metadata": dict}.
          - metadata keys used: session_date, turn_id, session, created_at
        run_refinement: set True to actively run three-body debate at end.
          Costs one LLM round per domain — off by default for ingestion
          speed. Benchmark callers typically run this once after all turns
          for a given domain are in.

        Returns {ingested, kg_triples, aggregations, refinement_insights}.
        """
        self._check_init()
        ingested = 0
        kg_triples = 0
        # Collect per-domain facts-seen count to drive optional refinement.
        domains_touched: set[str] = set()

        for t in turns:
            content = (t.get("content") or "").strip()
            if not content:
                continue
            role = t.get("role", "user")
            meta = dict(t.get("metadata") or {})
            meta.setdefault("role", role)

            dom = domain or meta.get("domain", "") or ""

            entry = MemoryEntry(
                content=content,
                domain=dom,
                level=MemoryLevel.FACT,
                metadata=meta,
                user_id=user_id,
                agent_id=agent_id,
                session_id=session_id,
            )
            if "created_at" in meta:
                try:
                    entry.created_at = float(meta["created_at"])
                except (TypeError, ValueError):
                    pass
            if self._embedder:
                entry.embedding = self._embedder.encode(content)

            mid = self._store.add(entry, dedup=False)
            if mid <= 0:
                continue
            ingested += 1
            if dom:
                domains_touched.add(dom)

            # Meta profile from user turns
            if role == "user":
                try:
                    self._meta.update_from_text(content)
                except Exception:
                    pass

            # KG triples from user turns (gives structured temporal queries
            # something to chew on — essential for "previous X" type questions).
            if self._kg is not None and role == "user":
                try:
                    for subj, rel, obj in self._kg.extract_triples_from_text(content):
                        self._kg.add_triple(subj, rel, obj, source_id=mid)
                        kg_triples += 1
                except Exception:
                    pass

        aggregations: dict[str, int] = {}
        if run_aggregation and self._llm is not None and self._llm.is_available():
            for dom in domains_touched:
                try:
                    created = self._aggregator.check_and_aggregate(dom)
                    if created:
                        aggregations[dom] = len(created)
                except Exception:
                    pass

        refinement_insights: dict[str, int] = {}
        if run_refinement and self._llm is not None and self._llm.is_available():
            for dom in domains_touched:
                try:
                    r = self._chat_refine.refine(domain=dom)
                    refinement_insights[dom] = len(r.new_insights)
                    # Mirror each fresh habit into L2 as PRINCIPLE so that
                    # pyramid.search can surface it via vector/FTS — HDC
                    # similarity scores for NL queries are too low (< 0.01)
                    # to be usable for retrieval. HDC keeps its role for
                    # habit stability tracking; MemoryStore makes the
                    # habit description searchable.
                    for insight in r.new_insights:
                        mirror = MemoryEntry(
                            content=insight.description,
                            domain=dom,
                            level=MemoryLevel.PRINCIPLE,
                            metadata={
                                "source": "chat_refine",
                                "confidence": insight.confidence,
                                "evidence": insight.evidence[:300] if insight.evidence else "",
                                "falsifier": insight.falsifier[:200] if insight.falsifier else "",
                            },
                        )
                        if self._embedder:
                            mirror.embedding = self._embedder.encode(insight.description)
                        self._store.add(mirror, dedup=False)
                except Exception:
                    pass
            # Meta self-profile gets a refresh after new habits land
            try:
                self._meta.refresh_self()
            except Exception:
                pass

        return {
            "ingested": ingested,
            "kg_triples": kg_triples,
            "domains": sorted(domains_touched),
            "aggregations": aggregations,
            "refinement_insights": refinement_insights,
        }

    def ingest_batch(
        self,
        message_batches: list[list[Message]],
        user_id: str = "",
        agent_id: str = "",
        session_id: str = "",
    ) -> list[MemoryEntry]:
        """Batch-ingest multiple conversations in a single transaction.

        10-20× faster than calling ingest() per batch for bulk imports.
        Skips per-conversation KG/profile updates to keep it lean — call
        refresh_self() afterwards if you need profiles recomputed.
        """
        self._check_init()
        all_entries: list[MemoryEntry] = []
        for msgs in message_batches:
            result = gate(msgs)
            for entry in result.entries:
                entry.user_id = user_id
                entry.agent_id = agent_id
                entry.session_id = session_id
                if self._embedder:
                    entry.embedding = self._embedder.encode(entry.content)
                all_entries.append(entry)

        ids = self._store.add_many(all_entries)
        return [e for e, mid in zip(all_entries, ids) if mid > 0]

    # --- L2: Search ---

    def search(
        self,
        query: str,
        domain: str | None = None,
        user_id: str = "",
        agent_id: str = "",
        session_id: str = "",
        max_results: int = 10,
        fuse_habits: bool = True,
    ) -> list[SearchResult]:
        """Retrieve memories relevant to the query.

        By default fuses three sources from the pyramid: L2 facts (via
        pyramid.search, which itself pulls in KG, patterns, and context),
        and L3 habits (HDC-matched). Habits encode pre-digested insight
        ("user has visited 3 doctors: X, Y, Z") that would require
        multi-hop retrieval otherwise.

        Habits ride on top of the result list at a fixed promotion cap so
        they surface even when the raw-fact retrieval already saturates
        max_results. Set fuse_habits=False for a pure L2-only comparison
        (e.g., when measuring what the habit layer contributes).
        """
        self._check_init()
        results = self._pyramid.search(query, domain=domain, max_results=max_results)

        if fuse_habits and self._habits is not None:
            try:
                # Record HDC hits on the matched habits so the habit-store
                # still tracks which habits are getting used — even though
                # we don't inject them into results here (they're already
                # mirrored into the pyramid as PRINCIPLE entries during
                # refinement, so pyramid.search surfaces them naturally via
                # level-weighted sorting).
                self._habits.query(
                    [query], top_k=3, record_hits=True, min_score=0.005,
                )
            except Exception:
                pass

        if user_id or agent_id or session_id:
            filtered = []
            for r in results:
                if user_id and r.entry.user_id != user_id:
                    continue
                if agent_id and r.entry.agent_id != agent_id:
                    continue
                if session_id and r.entry.session_id != session_id:
                    continue
                filtered.append(r)
            return filtered
        return results

    # --- CRUD ---

    def get_memory(self, memory_id: int) -> MemoryEntry | None:
        self._check_init()
        return self._store.get(memory_id)

    def update_memory(
        self, memory_id: int, content: str | None = None, metadata: dict | None = None
    ) -> MemoryEntry | None:
        self._check_init()
        entry = self._store.get(memory_id)
        if entry is None:
            return None
        if content is not None:
            entry.content = content
            if self._embedder:
                entry.embedding = self._embedder.encode(content)
        if metadata is not None:
            entry.metadata = metadata
        self._store.update(entry)
        return entry

    def delete_memory(self, memory_id: int) -> bool:
        self._check_init()
        if self._store.get(memory_id) is None:
            return False
        self._store.delete(memory_id)
        return True

    def delete_all_memories(
        self, user_id: str = "", agent_id: str = "", session_id: str = ""
    ) -> int:
        self._check_init()
        return self._store.delete_all(
            user_id=user_id, agent_id=agent_id, session_id=session_id
        )

    def memory_history(self, memory_id: int) -> list[dict]:
        self._check_init()
        return self._store.get_history(memory_id)

    def list_memories(
        self,
        user_id: str = "",
        agent_id: str = "",
        session_id: str = "",
        limit: int = 100,
    ) -> list[MemoryEntry]:
        self._check_init()
        return self._store.list_filtered(
            user_id=user_id, agent_id=agent_id, session_id=session_id, limit=limit
        )

    def search_with_habits(
        self,
        query: str,
        domain: str | None = None,
        user_id: str = "",
        agent_id: str = "",
        session_id: str = "",
    ) -> SearchResponse:
        """Search + auto-attach top-3 HDC-matched habits (microsecond-fast).

        For MCP / API consumers that want per-query habit context alongside
        search results. The host AI sees both the retrieved memories AND
        the relevant user habits in a single response.
        """
        results = self.search(
            query, domain=domain,
            user_id=user_id, agent_id=agent_id, session_id=session_id,
        )
        matched_habits = self._habits.query(
            [query], top_k=3, record_hits=True, min_score=0.1,
        )
        return SearchResponse(results=results, matched_habits=matched_habits)

    def search_pyramid(self, query: str, start_level: int = 2) -> list[SearchResult]:
        self._check_init()
        return self._pyramid.search_pyramid(query)

    # --- L3: Habits ---

    def query_habits(self, query: str) -> list[Habit]:
        self._check_init()
        results = self._habits.query([query], top_k=5)
        return [h for h, score in results if score > 0.1]

    def reject_habit(self, index: int, reason: str = "") -> None:
        """Mark a habit as incorrect. Two rejections auto-archive it."""
        self._check_init()
        self._habits.reject_habit(index, reason=reason)

    def push_habits(
        self,
        platform: str | None = None,
        project_dir: str | None = None,
        dry_run: bool = False,
    ) -> dict:
        """Push confirmed habits to host platform's native memory."""
        self._check_init()
        from pathlib import Path as _P
        from radiomind.hooks.habit_pusher import HabitPusher
        pusher = HabitPusher(
            platform=platform,
            project_dir=_P(project_dir) if project_dir else None,
        )
        return pusher.push(self._habits.all_habits(), dry_run=dry_run)

    def prune_stale_habits(self) -> int:
        """Archive candidate habits with 0 hits older than ARCHIVE_AGE_DAYS."""
        self._check_init()
        return self._habits.prune_stale()

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
            state_path = self.config.home / "data" / "refine_sessions.json"
            self._step_refiner = StepRefiner(self._store, self._habits, state_path=state_path)

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
        """Generate JSONL training data + valid split from habits + memories.

        Returns (train_count, train_path). On quality-gate refusal returns
        (0, path_or_empty) and the caller should inspect the reason via
        generate_training_data_with_report().
        """
        self._check_init()
        from radiomind.training.data_gen import TrainingDataGenerator

        path = output_path or str(self.config.home / "models" / "train.jsonl")
        gen = TrainingDataGenerator(self._store, self._habits)
        count = gen.generate(Path(path))
        return count, path

    def generate_training_data_with_report(
        self, output_path: str | None = None
    ):
        """Same as generate_training_data but returns the DataGenReport."""
        self._check_init()
        from radiomind.training.data_gen import TrainingDataGenerator

        path = output_path or str(self.config.home / "models" / "train.jsonl")
        gen = TrainingDataGenerator(self._store, self._habits)
        report = gen.generate_with_report(Path(path))
        return report, path

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
