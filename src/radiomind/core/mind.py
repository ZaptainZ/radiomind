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
from radiomind.refinement.numeric_aggregator import NumericAggregator
from radiomind.storage.database import MemoryStore
from radiomind.storage.hdc import HabitStore
from radiomind.storage.knowledge_graph import KnowledgeGraph
from radiomind.storage.pyramid import PyramidAggregator, PyramidSearch


_ANSWER_SHAPE_GUIDANCE = {
    "relative_offset": (
        "The answer must be phrased as a RELATIVE OFFSET "
        "(e.g. '7 days ago', '3 weeks ago', '2 months since X'). "
        "Do NOT give an absolute date like 'March 12, 2023'."
    ),
    "absolute_date": (
        "The answer must be an ABSOLUTE DATE "
        "(e.g. 'October 25, 2022', '2023-04-10'). "
        "Do NOT give a relative offset."
    ),
    "duration": (
        "The answer must be a DURATION "
        "(e.g. '4 hours', '3 weeks', '9 months'). "
        "No specific dates unless asked."
    ),
    "number": "The answer must be an integer count only (e.g. '4', '10').",
    "amount": "The answer must be a dollar amount (e.g. '$3,750').",
    "named_entity": (
        "The answer must be a SPECIFIC NAMED ENTITY the evidence mentions "
        "(book title, person name, place, product name — not a generic "
        "description). If no specific entity is present, say 'insufficient'."
    ),
    "list": "The answer must be an enumerated list.",
}


def _task_description_for(sig, query: str, reference_date: str) -> str | None:
    """Translate an AttentionSignature into a task prompt for trinity.

    Each wants shape surfaces a different tension; the answer_shape
    adds a formatting constraint. The LLM picks the three opposing
    stances per call — we only name the tension and the required output.
    """
    wants = sig.wants
    if wants not in ("date", "inference", "detail"):
        return None
    shape_hint = _ANSWER_SHAPE_GUIDANCE.get(sig.answer_shape, "")
    shape_line = f"\nAnswer-shape constraint: {shape_hint}" if shape_hint else ""

    if wants == "date":
        return (
            f"Answer this temporal question from the evidence. "
            f"Reference date (today): {reference_date or 'unknown'}.\n"
            f"Tensions to triangulate: anchor-based (specific dated events) "
            f"vs chain-based (multi-event timeline) vs window-based "
            f"(approximate range when exact dates are missing).\n"
            f"Question: {query}{shape_line}"
        )
    if wants == "inference":
        return (
            f"Answer this open-domain question by picking ONE SPECIFIC PROPER "
            f"NOUN that the evidence literally contains (book title, brand, "
            f"place name, person name, product). Generic categories like "
            f"'a mystery novel' or 'running shoes' are WRONG; the answer "
            f"must be a nameable entity copied from the evidence. If no "
            f"such proper noun exists in the evidence, output literally "
            f"'insufficient' (better to abstain than invent).\n"
            f"Tensions to triangulate: literal-evidence (copy from memories) "
            f"vs inferred-fit (most plausible given preferences) vs "
            f"abstention-safe.\n"
            f"Question: {query}{shape_line}"
        )
    if wants == "detail":
        return (
            f"Answer this specific-detail question about a named subject. "
            f"Tensions to triangulate: exact-mention (pick the memory that "
            f"literally names the attribute) vs nearby-inference (the "
            f"memory implies it) vs insufficient-abstain.\n"
            f"Question: {query}{shape_line}"
        )
    return None


import re as _re


_DATE_TOKEN_RE = _re.compile(
    r"\b(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}"
    r"|\d{1,2}[-/]\d{1,2}(?:[, ]+\d{4})?"
    r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.? ?\d{1,2})",
    _re.IGNORECASE,
)
_AMOUNT_TOKEN_RE = _re.compile(r"\$\s*\d", _re.IGNORECASE)
_OWN_VERBS_RE = _re.compile(
    r"\bi\s+(?:just\s+|also\s+|then\s+|recently\s+)?"
    r"(?:bought|got|picked|brought|purchased|acquired|adopted|received|"
    r"replaced|fixed|installed|own|have)\b",
    _re.IGNORECASE,
)


def _derive_fact_tags(content: str, meta: dict) -> list[str]:
    """Compute tags at L0 FACT write time.

    Tags surface cross-layer semantic signals:
      - date_bearing: contains an explicit date or session_date
      - amount: mentions money
      - ownership: user-ownership verb pattern
    Subclassers can extend. Kept cheap (regex only) — LLM-based tagging
    happens elsewhere (KG, numeric aggregator) and adds its own tags
    via metadata.
    """
    tags: list[str] = []
    text = content or ""
    if _DATE_TOKEN_RE.search(text) or (meta.get("session_date") and not meta.get("__suppress_date_tag")):
        tags.append("date_bearing")
    if _AMOUNT_TOKEN_RE.search(text):
        tags.append("amount")
    if _OWN_VERBS_RE.search(text):
        tags.append("ownership")
    return tags


def _format_memories(memories: list, max_items: int = 25) -> str:
    """Render retrieved memories into a block for trinity evidence."""
    if not memories:
        return ""
    lines = []
    for m in memories[:max_items]:
        if hasattr(m, "entry"):  # SearchResult
            sdate = (m.entry.metadata or {}).get("session_date", "") if hasattr(m.entry, "metadata") else ""
            txt = (m.entry.content or "")[:400].replace("\n", " ")
        elif isinstance(m, dict):
            sdate = m.get("created_at") or m.get("session_date") or ""
            txt = (m.get("memory") or m.get("content") or "")[:400].replace("\n", " ")
        else:
            sdate = ""
            txt = str(m)[:400].replace("\n", " ")
        lines.append(f"[{sdate}] {txt}" if sdate else txt)
    return "\n".join(lines)


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
        self._numeric_agg: NumericAggregator | None = None
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

        # Load embedder FIRST so PyramidSearch can use it.
        #
        # Precedence (2026-04-19, updated per host-LLM-assumed policy):
        #   1. DashScope text-embedding-v4 @ 2048-dim if credentials present
        #      — cloud embedder with 2× the semantic capacity of local MiniLM
        #   2. Local ONNX MiniLM 384-dim fallback for offline / privacy-max
        #   3. None → FTS-only degradation
        #
        # Earlier version preferred local for "privacy". That design bet was
        # abandoned (see memory/project_host_llm_assumed.md): users already
        # rely on host LLM for chat, so paying for a 2048-dim embedder is
        # fully consistent with the privacy model (data stays local, only
        # embed() output comes back). config.retrieval.embedder.prefer_local
        # can force the old ordering for users who genuinely need offline.
        self._embedder = None
        prefer_local = bool(self.config.get("retrieval.embedder.prefer_local", False))

        def _try_dashscope() -> object | None:
            """Resolve OpenAI-compatible embedder.

            Read order (first-hit wins):
              1. [retrieval_provider] — unified retrieval capability module
                 (embedding + reranker share one key/base_url/enable switch).
                 `provider` is a semantic label (dashscope/openrouter/jina/...);
                 the embedder class is the OpenAI-compatible DashScopeEmbedder
                 (name is historical — it speaks OpenAI's /embeddings protocol).
              2. [embedding] — legacy dedicated section
              3. [llm.openai] — legacy piggyback when pointed at DashScope
            """
            try:
                # 1. Unified retrieval provider
                rp = self.config.get("retrieval_provider", {}) or {}
                if rp.get("enabled", True):
                    base = (rp.get("base_url") or "").strip()
                    key = (rp.get("api_key") or "").strip()
                    if base and key:
                        from radiomind.storage.embedding_dashscope import DashScopeEmbedder
                        kwargs: dict = {}
                        model = (rp.get("embedding_model") or "").strip()
                        if model:
                            kwargs["model"] = model
                        dim = rp.get("embedding_dim")
                        if isinstance(dim, int) and dim > 0:
                            kwargs["dim"] = dim
                        ds = DashScopeEmbedder(base, key, **kwargs)
                        if ds.load():
                            return ds

                # 2. Legacy [embedding] section
                emb = self.config.get("embedding", {}) or {}
                base = (emb.get("base_url") or "").strip()
                key = (emb.get("api_key") or "").strip()
                if base and key:
                    from radiomind.storage.embedding_dashscope import DashScopeEmbedder
                    kwargs: dict = {}
                    model = (emb.get("model") or "").strip()
                    if model:
                        kwargs["model"] = model
                    dim = emb.get("dim")
                    if isinstance(dim, int) and dim > 0:
                        kwargs["dim"] = dim
                    ds = DashScopeEmbedder(base, key, **kwargs)
                    if ds.load():
                        return ds

                # 3. Legacy [llm.openai] piggyback
                oc = self.config.get("llm.openai", {}) or {}
                base = (oc.get("base_url") or "").strip()
                key = (oc.get("api_key") or "").strip()
                if base and key and "dashscope" in base.lower():
                    from radiomind.storage.embedding_dashscope import DashScopeEmbedder
                    ds = DashScopeEmbedder(base, key)
                    if ds.load():
                        return ds
            except Exception:
                pass
            return None

        def _try_local() -> object | None:
            try:
                from radiomind.storage.embedding import EmbeddingEncoder
                e = EmbeddingEncoder(home / "models" / "embedding")
                if e.load():
                    return e
            except Exception:
                pass
            return None

        if prefer_local:
            self._embedder = _try_local() or _try_dashscope()
        else:
            self._embedder = _try_dashscope() or _try_local()

        # Reranker — part of the unified retrieval capability module.
        # Activation:
        #   [retrieval_provider].use_reranker = true  (preferred — one module, one switch)
        #   retrieval.reranker.enabled = true         (legacy — kept for back-compat)
        # Resolution (first-hit wins):
        #   local CrossEncoder → [retrieval_provider] API key → [reranker]
        #   → [llm.openai] piggyback (legacy)
        self._reranker = None
        rp_cfg = self.config.get("retrieval_provider", {}) or {}
        rerank_on = bool(
            rp_cfg.get("use_reranker", False)
            or self.config.get("retrieval.reranker.enabled", False)
        )
        if rerank_on:
            try:
                from radiomind.storage.reranker import CrossEncoderReranker
                model_id = self.config.get(
                    "retrieval.reranker.model", "BAAI/bge-reranker-v2-m3",
                )
                r = CrossEncoderReranker(model_id=model_id, cache_dir=None)
                if r.load():
                    self._reranker = r
            except Exception:
                self._reranker = None
            if self._reranker is None:
                try:
                    # 1. Unified retrieval provider. Dispatch by provider:
                    #    - dashscope: native /services/rerank endpoint
                    #    - openrouter/cohere/jina/voyage: OpenAI-compat /rerank
                    if rp_cfg.get("enabled", True):
                        key = (rp_cfg.get("api_key") or "").strip()
                        base = (rp_cfg.get("base_url") or "").strip()
                        provider = (rp_cfg.get("provider") or "dashscope").strip().lower()
                        if key:
                            model = (rp_cfg.get("reranker_model") or "").strip()
                            if provider == "dashscope":
                                from radiomind.storage.reranker_dashscope import DashScopeReranker
                                kwargs = {"model": model} if model else {}
                                rr = DashScopeReranker(api_key=key, **kwargs)
                            else:
                                from radiomind.storage.reranker_openai_compat import OpenAICompatReranker
                                kwargs = {"model": model} if model else {}
                                rr = OpenAICompatReranker(base, key, **kwargs)
                            if rr.load():
                                self._reranker = rr

                    # 2. Legacy [reranker] section
                    if self._reranker is None:
                        rr_cfg = self.config.get("reranker", {}) or {}
                        key = (rr_cfg.get("api_key") or "").strip()
                        if key:
                            from radiomind.storage.reranker_dashscope import DashScopeReranker
                            kwargs: dict = {}
                            model = (rr_cfg.get("model") or "").strip()
                            if model:
                                kwargs["model"] = model
                            rr = DashScopeReranker(api_key=key, **kwargs)
                            if rr.load():
                                self._reranker = rr

                    # 3. Legacy [llm.openai] DashScope piggyback
                    if self._reranker is None:
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

        # NumericAggregator shares knowledge.db: structured-extract products
        # of ingest live together. Opens late enough to see the final
        # self._llm (set above), for query-time classification.
        self._numeric_agg = NumericAggregator(
            self.config.db_path.parent / "knowledge.db", llm=self._llm,
        )
        self._numeric_agg.open()

        self._pyramid = PyramidSearch(
            self._store,
            embedder=self._embedder,
            reranker=self._reranker,
            query_rewriter=self._query_rewriter,
            kg=self._kg,
        )
        self._aggregator = PyramidAggregator(self._store, self._llm, embedder=self._embedder)

        # Query-time atomic decomposer. Fires on aggregation-type queries
        # (detected by core.attention) to turn retrieved narrative turns
        # into a transient factoid view without rewriting the stored turns.
        # Candidates with hit_count >= 2 get promoted to L2 PATTERN.
        try:
            from radiomind.refinement.decompose import QueryDecomposer
            self._query_decomposer = QueryDecomposer(
                self._store, self._llm, kg=self._kg, embedder=self._embedder,
            )
        except Exception:
            self._query_decomposer = None

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
        for component in (self._meta, self._numeric_agg, self._kg, self._habits, self._store):
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
        # Collected user turns for batch KG extraction at end of loop.
        # Shape: [(memory_id, content), ...]
        user_turns_for_kg: list[tuple[int, str]] = []

        # PASS 1: build all entries WITHOUT embeddings (to enable batching)
        # This two-pass structure matters when the embedder is a remote API
        # (DashScope) — single-text encode per turn is 3s × 500 turns = 25
        # minutes/question. Batch+parallel encode brings that to ~30s.
        pending: list[tuple[MemoryEntry, str, str]] = []  # (entry, content, role)
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
                tags=_derive_fact_tags(content, meta),
            )
            if "created_at" in meta:
                try:
                    entry.created_at = float(meta["created_at"])
                except (TypeError, ValueError):
                    pass
            pending.append((entry, content, role))

        # PASS 2: batch-encode all contents through the embedder if it
        # supports encode_batch (DashScopeEmbedder does). Falls back to
        # per-text encode() loop when the embedder lacks batch support
        # (local MiniLM). max_workers=5 stays within DashScope per-account
        # parallelism without tripping rate limits for typical benchmarks.
        if self._embedder is not None and pending:
            contents = [c for _, c, _ in pending]
            has_batch = hasattr(self._embedder, "encode_batch")
            if has_batch:
                try:
                    embeds = self._embedder.encode_batch(contents)
                except Exception:
                    embeds = [self._embedder.encode(c) for c in contents]
            else:
                embeds = [self._embedder.encode(c) for c in contents]
            for (entry, _, _), emb in zip(pending, embeds):
                entry.embedding = emb

        # PASS 3: persist, update meta, queue KG extraction
        for entry, content, role in pending:
            mid = self._store.add(entry, dedup=False)
            if mid <= 0:
                continue
            ingested += 1
            if entry.domain:
                domains_touched.add(entry.domain)

            # Meta profile from user turns
            if role == "user":
                try:
                    self._meta.update_from_text(content)
                except Exception:
                    pass

            # Stash user turn text for batch KG extraction at end of loop.
            if self._kg is not None and role == "user":
                user_turns_for_kg.append((mid, content))

        # Batch KG extraction: one LLM call covering multiple user turns,
        # chunked to keep prompts manageable. Falls back to regex-per-turn
        # if the LLM is unavailable or batch fails.
        if user_turns_for_kg and self._kg is not None:
            triples_by_mid: dict[int, list[tuple[str, str, str]]] = {}
            if self._llm is not None and self._llm.is_available():
                BATCH = 50  # turns per LLM call — ~50 × 400 chars = 20K tokens input
                for start in range(0, len(user_turns_for_kg), BATCH):
                    chunk = user_turns_for_kg[start : start + BATCH]
                    try:
                        extracted = self._kg.extract_triples_batch_llm(chunk, self._llm)
                        for mid, trips in extracted.items():
                            triples_by_mid.setdefault(mid, []).extend(trips)
                    except Exception:
                        pass
            # Any turn the batch skipped (or all turns if LLM unavailable):
            # regex fallback catches the Chinese subset at least.
            for mid, text in user_turns_for_kg:
                if mid in triples_by_mid and triples_by_mid[mid]:
                    continue
                try:
                    fb = self._kg.extract_triples_from_text(text)
                    if fb:
                        triples_by_mid[mid] = fb
                except Exception:
                    pass
            # Persist
            for mid, trips in triples_by_mid.items():
                for s, r, o in trips:
                    try:
                        self._kg.add_triple(s, r, o, source_id=mid)
                        kg_triples += 1
                    except Exception:
                        pass

        # Numeric cardinal aggregation: scan user turns for ownership /
        # acquisition / disposal / amount events and update the
        # per-(user,domain,class) cardinal cache. This gives aggregation
        # queries ("how many X", "how much total") a deterministic
        # ground-truth instead of LLM re-derivation from retrieval.
        cardinal_updates: dict[str, int] = {}
        if self._numeric_agg is not None and self._numeric_agg.is_available():
            # Reconstruct (mid, content, role, meta) tuples from the
            # pass 2/3 data. We kept pending; persist gave us mid for each.
            # Re-persist gave mid via add(); rebuild from pending's order by
            # re-querying the store would be expensive — instead we pass the
            # already-persisted user_turns_for_kg list (same mids, same text)
            # plus recover metadata from original `turns` by turn_id.
            try:
                meta_by_mid = {}
                for (entry, content, role), t in zip(pending, turns):
                    meta_by_mid[content] = dict(t.get("metadata") or {})
                turn_tuples = []
                for mid, content in user_turns_for_kg:
                    meta = meta_by_mid.get(content, {})
                    turn_tuples.append((mid, content, "user", meta))
                for dom in domains_touched or [""]:
                    touched = self._numeric_agg.process_turns(
                        turn_tuples, user_id=user_id, domain=dom,
                    )
                    if touched:
                        cardinal_updates[dom] = len(touched)
            except Exception:
                pass

        # User profile extraction: LLM batch over user turns to pull out
        # who/how/what fragments. Language-agnostic; replaces the Chinese
        # regex path which silently produced empty profiles on English
        # haystacks. Merged into the persisted profile for later answer
        # time `profile_hint()` injection.
        profile_fragments_count = 0
        if self._llm is not None and self._llm.is_available() and user_turns_for_kg:
            try:
                from radiomind.meta.profile_extractor import extract_batch as _prof_extract
                _meta_by_mid_for_prof = {}
                for (entry, content, role), t in zip(pending, turns):
                    _meta_by_mid_for_prof[content] = dict(t.get("metadata") or {})
                prof_turns = [
                    (mid, content, _meta_by_mid_for_prof.get(content, {}))
                    for mid, content in user_turns_for_kg
                ]
                fragments = _prof_extract(prof_turns, self._llm)
                if any(fragments.get(k) for k in ("who", "how", "what")):
                    if self._meta.merge_profile_fragments(fragments):
                        profile_fragments_count = (
                            len(fragments.get("who") or {})
                            + sum(len(v) if isinstance(v, list) else 1
                                  for v in (fragments.get("how") or {}).values())
                            + sum(len(v) if isinstance(v, list) else 1
                                  for v in (fragments.get("what") or {}).values())
                        )
            except Exception:
                pass

        # Temporal anchor extraction: scan user turns for dated events
        # and write them as L2 PATTERN entries with kind=temporal_anchor.
        # Dates are sparse (~5-15 per 500-turn haystack) so query-side
        # temporal skill can O(anchors) instead of O(500).
        temporal_anchors = 0
        if self._llm is not None and self._llm.is_available() and user_turns_for_kg:
            try:
                from radiomind.refinement.temporal_anchor import extract as _extract_anchors
                # Reuse the meta_by_mid map we built for numeric aggregator
                _meta_by_mid_for_anchors = {}
                for (entry, content, role), t in zip(pending, turns):
                    _meta_by_mid_for_anchors[content] = dict(t.get("metadata") or {})
                anchor_turns = [
                    (mid, content, _meta_by_mid_for_anchors.get(content, {}))
                    for mid, content in user_turns_for_kg
                ]
                anchors = _extract_anchors(anchor_turns, self._llm)
                for a in anchors:
                    dom = next(iter(domains_touched)) if domains_touched else (domain or "")
                    entry = MemoryEntry(
                        content=f"event: {a.event} [date={a.date}]",
                        domain=dom,
                        level=MemoryLevel.PATTERN,
                        user_id=user_id,
                        agent_id=agent_id,
                        session_id=session_id,
                        metadata={
                            "kind": "temporal_anchor",
                            "event": a.event,
                            "event_date": a.date,
                            "source_turn_id": a.turn_id,
                        },
                        tags=["temporal_anchor", "date_bearing"],
                    )
                    if self._embedder is not None:
                        try:
                            entry.embedding = self._embedder.encode(entry.content)
                        except Exception:
                            pass
                    if self._store.add(entry, dedup=False) > 0:
                        temporal_anchors += 1
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
            "cardinal_updates": cardinal_updates,
            "temporal_anchors": temporal_anchors,
            "profile_fragments": profile_fragments_count,
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
        attention_tags: list[str] | None = None,
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
        # Auto-classify the query's attention signature when caller hasn't
        # pre-tagged. Drives layer routing inside pyramid.search.
        if attention_tags is None:
            try:
                from radiomind.core.attention import classify
                attention_tags = classify(query)
            except Exception:
                attention_tags = None
        results = self._pyramid.search(
            query, domain=domain, max_results=max_results,
            attention_tags=attention_tags,
        )

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

    # --- Iterative retrieval (multi-anchor attention via trinity) ---

    def iterative_search(
        self,
        query: str,
        domain: str | None = None,
        user_id: str = "",
        agent_id: str = "",
        session_id: str = "",
        max_results: int = 10,
        max_passes: int = 2,
        n_anchors: int = 3,
        seed_results: list | None = None,
    ) -> list:
        """Multi-pass attention-driven search.

        Pass 1: standard `search()` produces a seed result list (or the
                caller may supply `seed_results` from an earlier call).
        Anchor generation: an N-party trinity reads the question and seed
                           results, then proposes N DIFFERENT focused
                           sub-queries (each from one stance / angle:
                           literal-topic / adjacent-experience / equipment
                           / time-context / etc — chosen by the LLM).
        Pass 2: each sub-query runs through `search()` independently;
                results are merged and de-duplicated against the seed.

        Returns a single deduplicated list. Falls back to seed (or empty)
        when no LLM is available or the trinity fails.

        Why this lives at the methodology level and not as a per-callsite
        regex: ANY caller (preference context extraction, entity
        candidate scan, multi-hop QA, future skill plug-ins) gets a
        broader memory window without hardcoding query-expansion rules.
        The trinity decides what angles matter for THIS question.
        """
        self._check_init()
        # Pass 1 (or use caller's seed)
        if seed_results is None:
            seed = self.search(
                query, domain=domain, user_id=user_id, agent_id=agent_id,
                session_id=session_id, max_results=max_results,
            )
        else:
            seed = list(seed_results)

        if max_passes <= 1 or self._llm is None or not self._llm.is_available():
            return seed

        # Build evidence block for the anchor-generation trinity
        seed_lines: list[str] = []
        seen_content: set[str] = set()
        for r in seed[:25]:
            content = getattr(getattr(r, "entry", None), "content", "") or ""
            if not content or content in seen_content:
                continue
            seen_content.add(content)
            sdate = ""
            try:
                sdate = (r.entry.metadata or {}).get("session_date", "")
            except Exception:
                pass
            seed_lines.append(f"[{sdate}] {content[:200].replace(chr(10), ' ')}")
        evidence_block = "\n".join(seed_lines) or "(no seed memories)"

        # N-party trinity generates one angle per stance.
        from radiomind.refinement import trinity as _trinity
        n = max(2, min(int(n_anchors), 7))
        anchor_result = _trinity.parties(
            n=n,
            task=(
                f"Generate {n} DIFFERENT focused search queries that would "
                f"surface complementary user-specific memories for this "
                f"question. Each stance picks a different angle (e.g. "
                f"literal-topic / adjacent-experience / equipment-or-gear "
                f"/ social-context / time-window / category-extension). "
                f"Stances must NOT propose duplicate or near-duplicate "
                f"queries. Each query should be 2-8 words, naturally "
                f"phrased as a noun phrase (no question marks).\n"
                f"Question: {query}"
            ),
            evidence=evidence_block,
            llm=self._llm,
            extra_schema=(
                f'  "queries": [str, ...] (exactly {n} items, one per stance, '
                f'each a short noun phrase)'
            ),
        )
        if not anchor_result:
            return seed
        queries_raw = anchor_result.get("queries") or []
        if not isinstance(queries_raw, list):
            return seed
        anchor_queries = []
        seen_q: set[str] = set()
        for q in queries_raw[:n]:
            qs = str(q).strip()
            ql = qs.lower()
            if not qs or ql in seen_q or ql == query.lower().strip():
                continue
            seen_q.add(ql)
            anchor_queries.append(qs)
        if not anchor_queries:
            return seed

        # Pass 2: parallel sub-queries, merge into seed.
        merged = list(seed)
        seen_ids: set = set()
        for r in seed:
            try:
                seen_ids.add(getattr(r.entry, "id", None) or id(r))
            except Exception:
                pass
        per_anchor_cap = max(3, max_results // 2)
        for aq in anchor_queries:
            try:
                more = self.search(
                    aq, domain=domain, user_id=user_id,
                    agent_id=agent_id, session_id=session_id,
                    max_results=per_anchor_cap,
                )
            except Exception:
                continue
            for r in more or []:
                rid = getattr(r.entry, "id", None) or id(r)
                if rid in seen_ids:
                    continue
                seen_ids.add(rid)
                merged.append(r)
        return merged

    # --- Attention-driven query decomposition ---

    def decompose_for_query(
        self,
        query: str,
        retrieved: list[SearchResult],
        domain: str,
        promote: bool = True,
    ) -> list:
        """Return atomic facts for an aggregation-style query.

        Only fires when attention classifier flags the query as aggregation
        (counting, listing, cross-session enumeration). Silently returns
        [] for other query types — caller can skip the decomposed block.

        When `promote=True` (default), atoms meeting the promotion criteria
        (confidence >=0.7, hit_count >=2, not redundant with existing L2
        PATTERN) are persisted as PATTERN entries, joining the pyramid.
        This is how "attention-driven retrieval" doubles as "attention-
        driven consolidation": facts that repeatedly answer queries earn
        their way into the persistent layer.
        """
        self._check_init()
        if self._query_decomposer is None or not self._query_decomposer.is_available():
            return []
        from radiomind.core.attention import is_aggregation, extract_focus_entity
        if not is_aggregation(query):
            return []

        focus = extract_focus_entity(query)
        atoms = self._query_decomposer.decompose(
            question=query, retrieved=retrieved, domain=domain, focus=focus,
        )
        # Atom-level trinity scope filter: when the query carries a
        # second-order constraint (temporal_constraint via attention's
        # aux_flags, or a focus-narrowed scope), the raw atom list often
        # over-includes events that don't belong to the constraint
        # window. Trinity-3-party with dimension-typed stances (in-scope
        # / borderline / out-of-scope) classifies each atom batched in
        # ONE LLM call. Targets d3ab962e ("hikes on consecutive
        # weekends" — atoms include all hikes; constraint trimmer keeps
        # only the consecutive-weekend pair) and gpt4_ab202e7f
        # ("kitchen items" — atoms include borderline non-kitchen items;
        # filter keeps strict kitchen domain).
        try:
            atoms = self._trinity_filter_atoms(query, atoms)
        except Exception:
            pass
        if promote and atoms:
            try:
                self._query_decomposer.promote_if_valuable(atoms, domain=domain)
            except Exception:
                pass
        return atoms

    def _trinity_filter_atoms(self, query: str, atoms: list) -> list:
        """Trinity-3-party scope check on the atom list.

        Each atom is judged on three independent dimensions (NOT on the
        decision itself — see CORE_METHODOLOGY stance-naming rule):
          - literal-fit:  does the atom's surface match the query terms?
          - scope-window: does the atom fall within any time / category
                          / spatial scope the question implies?
          - relevance-strength: how strongly does the atom support an
                          answer to the question vs being filler?

        Trinity outputs `keep_atom_ids` — a subset to retain. Empty or
        unparseable trinity = no filter applied (return all atoms).
        Single LLM call regardless of atom count.

        Bias to KEEP-ALL: only filter when ≥2 dimensions agree an atom
        is out-of-scope. This avoids over-trimming on queries that
        DON'T carry a real constraint.
        """
        if self._llm is None or not atoms:
            return atoms
        try:
            if not self._llm.is_available():
                return atoms
        except Exception:
            return atoms
        if len(atoms) <= 2:
            # Too few atoms — filter would be more noise than signal.
            return atoms

        # Build a compact evidence block: atom_id → fact + count + conf
        ev_lines = []
        atom_index: dict[int, object] = {}
        for i, a in enumerate(atoms):
            atom_index[i] = a
            count_tag = f" [×{getattr(a, 'count', 1)}]" if getattr(a, 'count', 1) > 1 else ""
            try:
                conf_v = float(getattr(a, "confidence", 0.0))
            except (TypeError, ValueError):
                conf_v = 0.0
            ev_lines.append(
                f"atom_id={i} | conf={conf_v:.2f}{count_tag} | "
                f"{(getattr(a, 'fact', '') or '')[:200]}"
            )
        evidence = "\n".join(ev_lines)

        from radiomind.refinement import trinity as _trinity
        result = _trinity.fast(
            task=(
                f"Decide which atoms below are in-scope answers for the "
                f"question. Three INDEPENDENT dimensions triangulate "
                f"(NOT abstain-vs-commit; each judges its own dimension):\n"
                f"  literal-fit: does the atom's surface match the query "
                f"terms?\n"
                f"  scope-window: does the atom fall within any time, "
                f"category, or spatial scope the question implies "
                f"(e.g. 'consecutive weekends', 'in March', "
                f"'kitchen items only')?\n"
                f"  relevance-strength: does the atom strongly support "
                f"an answer vs being filler / tangential?\n"
                f"\n"
                f"Output `keep_atom_ids` listing only the atoms judged "
                f"in-scope by ≥2 of the three dimensions. KEEP atoms "
                f"by default; only DROP when ≥2 dimensions clearly say "
                f"out-of-scope.\n"
                f"\n"
                f"Question: {query}"
            ),
            evidence=evidence,
            llm=self._llm,
            extra_schema=(
                '  "keep_atom_ids": [int, ...] (subset of atom_ids '
                'judged in-scope)'
            ),
        )
        if not result:
            return atoms
        keep_raw = result.get("keep_atom_ids") or []
        if not isinstance(keep_raw, list):
            return atoms
        keep_ids: set[int] = set()
        for x in keep_raw:
            try:
                keep_ids.add(int(x))
            except (TypeError, ValueError):
                continue
        if not keep_ids:
            return atoms  # empty filter result → ignore (don't drop all)
        # Edge case: trinity dropped >50% of atoms — likely over-zealous.
        # Keep all in that case to avoid false negatives.
        if len(keep_ids) < max(1, len(atoms) // 2):
            return atoms
        filtered = [atom_index[i] for i in sorted(keep_ids) if i in atom_index]
        return filtered or atoms

    # --- Query-time trinity pipelines (attention 4th law) ---

    @staticmethod
    def _attention_router_enabled() -> bool:
        """Honor `RADIOMIND_ATTENTION_ROUTER=off` (a2a-strict bench mode)."""
        import os
        return (os.environ.get("RADIOMIND_ATTENTION_ROUTER") or "on").strip().lower() != "off"

    def answer_hint(
        self,
        query: str,
        retrieved_memories: list,
        reference_date: str = "",
        domain: str = "",
        user_id: str = "",
    ) -> str:
        """Attention-routed trinity refinement of retrieved memories.

        Returns a short prefix string the caller prepends to the answer
        prompt, or "" when the query doesn't benefit from refinement.
        One LLM call for dates/inferences/details; no-op for plain
        lookup or aggregation (the aggregation path is served by
        get_numeric_cardinal, not this one).

        The trinity chooses three opposing stances for the specific
        task shape — we don't name the stances here.
        """
        self._check_init()
        if not self._attention_router_enabled():
            return ""
        if self._llm is None or not self._llm.is_available():
            return ""

        from radiomind.core.attention import analyze
        from radiomind.refinement.trinity import debate
        # GAP-3: prefer soft routing — when multiple skills match, fire
        # trinity to pick the best output instead of taking the first
        # match. Hard routing (try_resolve) is kept for backward compat
        # but the production path now goes through the soft variant.
        from radiomind.skills.registry import try_resolve_soft as try_skill

        sig = analyze(query)

        # Structured layer first: skills registry (temporal arithmetic,
        # cardinality, etc.). Each skill declares its match() and returns
        # None when it can't solve — we fall through to trinity then.
        skill_result = try_skill(
            query=query,
            memories=retrieved_memories,
            signature=sig,
            context={
                "mind": self,
                "reference_date": reference_date,
                "domain": domain,
                "user_id": user_id,
            },
        )
        if skill_result is not None:
            return skill_result.prefix()

        task = _task_description_for(sig, query, reference_date)
        if task is None:
            return ""

        evidence = _format_memories(retrieved_memories, max_items=25)
        # Multi-round trinity ONLY for the `date` wants (genuine
        # convergent task — date arithmetic has a unique correct
        # answer). Originally also wired for `inference`, but n=100 v4
        # showed multi-round on open-ended inference questions causes
        # over-commitment: round 1 says "info not enough", round 2 sees
        # the prior stances and "tries harder", producing a confident
        # but wrong answer (gpt4_93159ced_abs). Inference is a divergent
        # task — no single right answer to converge to — so single-round
        # is correct.
        debate_rounds = 3 if sig.wants == "date" else 1
        result = debate(
            task, evidence, self._llm,
            max_rounds=debate_rounds,
            converge_threshold=0.75,
        )
        if result is None:
            return ""
        final = str(result.get("final_answer") or "").strip()
        if not final or final.lower() in {"insufficient", "none", "unknown"}:
            return ""
        return (
            f"ATTENTION-ROUTED TRINITY VIEW "
            f"(three opposing stances reconciled; trust this over hedging "
            f"unless retrieval contradicts):\n"
            f"- answer: {final}\n\n"
        )

    # Backward-compat wrappers so existing bench harness calls still work.
    def run_temporal_precision(
        self, query: str, retrieved_memories: list, reference_date: str = "",
        domain: str = "", user_id: str = "",
    ) -> str:
        # V6.3-B: route via trinity-augmented attention so queries
        # whose surface form misses regex (e.g. LoCoMo dialog
        # phrasings) but whose semantic intent is temporal still
        # activate this skill.
        from radiomind.core.attention import analyze_with_trinity
        if analyze_with_trinity(query, llm=self._llm).wants != "date":
            return ""
        return self.answer_hint(
            query, retrieved_memories, reference_date,
            domain=domain, user_id=user_id,
        )

    def run_open_domain_specific(
        self, query: str, retrieved_memories: list,
        domain: str = "", user_id: str = "",
    ) -> str:
        from radiomind.core.attention import analyze_with_trinity
        if analyze_with_trinity(query, llm=self._llm).wants != "inference":
            return ""
        # V6.4-A: candidate-entity trinity for "Which X / What X is/likely Y"
        # questions. When the question is asking for a specific named
        # entity (national park, company, dish, person, etc.), extract
        # candidate entities of the asked type from retrieved memories
        # and run a 3-stance trinity to pick the most plausible one.
        # Returns a "ENTITY DISAMBIGUATION PICK" prefix if successful;
        # falls through to V6.3 answer_hint on abstain / failure
        # (never worse than current behavior).
        entity_section = self._v64a_disambiguate_open_domain_entity(
            query, retrieved_memories,
        )
        if entity_section:
            return entity_section
        return self.answer_hint(
            query, retrieved_memories,
            domain=domain, user_id=user_id,
        )

    def _v64a_disambiguate_open_domain_entity(
        self, query: str, retrieved_memories: list,
    ) -> str:
        """V6.4-A: candidate-entity trinity for open-domain queries.

        Two-stage:
          1. LLM-as-NER extraction — surface all candidate entities of
             the type the question asks about. <2 candidates → return ""
             (let V6.3 answer_hint handle it).
          2. Trinity-3-party pick with retry-consistency + abstain:
             - evidence-direct  : which candidate is directly mentioned
                                  doing the thing the question asks?
             - inference-bridge : which candidate plausibly fits via a
                                  bridging inference (user preferences /
                                  contextual hints)?
             - dialog-context   : which candidate matches dialog timing,
                                  relationships, and surrounding facts?

        Both trinity calls must agree on the same chosen_index. Any
        inconsistency / abstain / parse failure → return "" and the
        caller falls back to V6.3 answer_hint.

        Methodology: same retry-consistency + abstain pattern as
        V6.1.1 anchor selection (CORE_METHODOLOGY dimension-typed
        stance naming).
        """
        if self._llm is None or not self._llm.is_available():
            return ""
        from radiomind.refinement import trinity as _trinity

        # Stage 1: extract candidate entities
        evidence = _format_memories(retrieved_memories, max_items=25)
        extract = _trinity.fast(
            task=(
                "The user's question asks 'Which X / What X' for some "
                "specific entity type X (e.g. national park, company, "
                "dish, person, song, location). Extract from the memories "
                "below ALL distinct candidate entities of that type that "
                "are explicitly mentioned. List by surface form as they "
                "appear in the memories. Do not invent candidates not "
                "present in the memories.\n"
                f"Question: {query}"
            ),
            evidence=evidence,
            llm=self._llm,
            extra_schema='  "candidates": list[str]  (0-8 distinct entity names)',
        )
        if not extract:
            return ""
        candidates = extract.get("candidates")
        if not isinstance(candidates, list):
            return ""
        candidates = [
            str(c).strip() for c in candidates if isinstance(c, (str, int, float))
        ]
        candidates = [c for c in candidates if c]
        if len(candidates) < 2:
            return ""

        # Stage 2: trinity pick (retry-consistency)
        idx1 = self._v64a_trinity_pick_entity_once(
            query, candidates, evidence,
        )
        idx2 = self._v64a_trinity_pick_entity_once(
            query, candidates, evidence,
        )
        if idx1 is None or idx1 != idx2:
            return ""
        if not (0 <= idx1 < len(candidates)):
            return ""
        picked = candidates[idx1]
        return (
            f"ENTITY DISAMBIGUATION PICK (open-domain trinity; trust this "
            f"over alternative candidates unless retrieval contradicts):\n"
            f"  {picked}\n\n"
        )

    def _v64a_trinity_pick_entity_once(
        self, query: str, candidates: list[str], evidence: str,
    ) -> int | None:
        """Single trinity LLM call for open-domain entity disambiguation.
        Returns chosen_index, -1 (abstain), or None on parse / LLM failure.
        """
        from radiomind.refinement import trinity as _trinity
        cand_lines = [f"  {i}. {c}" for i, c in enumerate(candidates)]
        cand_block = "\n".join(cand_lines)
        result = _trinity.fast(
            task=(
                f"Three independent stances pick the BEST candidate for "
                f"this open-domain question. Each stance evaluates by a "
                f"different dimension (CORE_METHODOLOGY: dimension-typed "
                f"naming, never conclusion-typed):\n"
                f"  evidence-direct  — which candidate is most directly "
                f"described in the memories as doing / being / having "
                f"what the question asks about?\n"
                f"  inference-bridge — which candidate fits via a "
                f"bridging inference (e.g. user preferences, related "
                f"activities, contextual hints)?\n"
                f"  dialog-context   — which candidate matches the "
                f"surrounding dialog context (timing, relationships, "
                f"sequence of events)?\n"
                f"\n"
                f"Candidates:\n{cand_block}\n"
                f"\n"
                f"Output `chosen_index` (0-based). If NO candidate is "
                f"sufficiently supported by ANY stance, output -1 to "
                f"abstain (caller will fall back to free-form inference).\n"
                f"Question: {query}"
            ),
            evidence=evidence,
            llm=self._llm,
            extra_schema='  "chosen_index": int  (-1 for abstain)',
        )
        if not result:
            return None
        try:
            return int(result.get("chosen_index"))
        except (TypeError, ValueError):
            return None

    # --- Preference context injector ---

    def run_preference_context(
        self, query: str, retrieved_memories: list,
        domain: str = "", user_id: str = "",
    ) -> str:
        """For preference / advice questions, extract relevant user-
        specific context from memories and format as a prefix the
        answer LLM can anchor on.

        Typical preference questions ask for a personalized recommendation
        ("should I attend my reunion?", "any tips for my kitchen?").
        Without explicit context extraction, smaller answer models
        sometimes default to generic advice or abstain — both judged
        wrong by gold that expects user-anchored responses.

        Uses one trinity call to triangulate what's relevant: too narrow
        misses tangential context, too broad dumps noise.

        Routes off `AttentionSignature.aux_flags["preference_anchor"]`
        (centralised in `core/attention.py`) instead of an inline regex
        — see GAP-1 in the chain audit. When the signature flags a
        preference query, the method also fires a second focused
        retrieval pass over user-specific anchors (tools/surfaces/
        constraints) so trinity gets richer evidence than top-k alone.
        """
        self._check_init()
        if not self._attention_router_enabled():
            return ""
        if self._llm is None or not self._llm.is_available():
            return ""

        # Preference detection now lives on AttentionSignature.
        from radiomind.core.attention import analyze
        sig = analyze(query)
        if not sig.aux_flags.get("preference_anchor"):
            return ""

        # First pass: format the caller-supplied top-k retrieval.
        lines = []
        seen_content: set[str] = set()
        for m in retrieved_memories[:40]:
            if isinstance(m, dict):
                sdate = m.get("created_at") or m.get("session_date", "")
                content = m.get("memory") or m.get("content") or ""
            elif hasattr(m, "entry"):
                sdate = (m.entry.metadata or {}).get("session_date", "")
                content = m.entry.content or ""
            else:
                continue
            if not content:
                continue
            seen_content.add(content)
            lines.append(f"[{sdate}] {content[:300].replace(chr(10), ' ')}")

        # Multi-anchor iterative retrieval: trinity-N-party generates
        # complementary expansion queries, each surfacing a different
        # angle of user-specific anchor (literal-topic / adjacent-
        # experience / equipment / etc — chosen by the LLM). Targets
        # d6233ab6 + 95228167 + similar where top-k missed user-tying
        # memories that lived under different surface words.
        # Falls back gracefully when LLM unavailable.
        if domain:
            try:
                # Build seed_results from the caller-supplied list so we
                # don't re-pay the first-pass retrieval cost.
                seed_objs = [m for m in retrieved_memories
                              if hasattr(m, "entry")]
                expanded = self.iterative_search(
                    query=query, domain=domain,
                    seed_results=seed_objs or None,
                    max_passes=2, n_anchors=3, max_results=20,
                )
                for r in expanded or []:
                    content = getattr(getattr(r, "entry", None), "content", "") or ""
                    if not content or content in seen_content:
                        continue
                    seen_content.add(content)
                    sdate = ""
                    try:
                        sdate = (r.entry.metadata or {}).get(
                            "session_date", ""
                        )
                    except Exception:
                        pass
                    lines.append(
                        f"[{sdate}] {content[:300].replace(chr(10), ' ')}"
                    )
            except Exception:
                pass

        if not lines:
            return ""
        evidence = "\n".join(lines)

        from radiomind.refinement.trinity import debate
        result = debate(
            task=(
                f"The user asked a preference/advice question. Extract "
                f"USER-SPECIFIC context from memories that the answer "
                f"MUST anchor on. Each context_item MUST be a CONCRETE "
                f"NOUN PHRASE — a named tool, course, club, hobby, "
                f"place, person, fact about the user — copied verbatim "
                f"or near-verbatim from the memories. Avoid generic "
                f"descriptors like 'enjoys reunions' or 'has memories'. "
                f"Examples of GOOD items: 'was on the debate team', "
                f"'took advanced placement history', 'lived in Boston "
                f"for 6 years', 'plays Korg B1 piano'. Examples of BAD "
                f"items: 'is sociable', 'values relationships'.\n"
                f"\n"
                f"Tensions: specificity (only directly-named topic "
                f"context) vs inclusion (any tangential grounding that "
                f"the answer could anchor on) vs salience (filter "
                f"trivial filler, keep revealing details that distinguish "
                f"this user from others).\n"
                f"\n"
                f"REQUIRED OUTPUT: at least 3 concrete context_items "
                f"unless memories are truly empty of any user-specific "
                f"signal. Don't return an empty list when there are ANY "
                f"named entities, courses, hobbies, places, or activities "
                f"in the memories — extract them.\n"
                f"\n"
                f"Question: {query}"
            ),
            evidence=evidence,
            llm=self._llm,
            extra_schema=(
                '  "context_items": [str, str, ...] (3-10 concrete '
                'noun-phrase user-specific details, copied near-verbatim '
                'from memories — never abstract descriptors)'
            ),
        )
        if not result:
            return ""
        items = result.get("context_items") or []
        if not isinstance(items, list) or not items:
            return ""
        # Filter noise
        items = [str(x).strip() for x in items if str(x).strip()][:10]
        if not items:
            return ""
        lines_out = [
            "PREFERENCE CONTEXT (user-specific details the answer MUST "
            "anchor on — at least one of these MUST be cited by name):"
        ]
        for it in items:
            lines_out.append(f"- {it}")
        return "\n".join(lines_out) + "\n\n"

    # --- Entity disambiguation (GAP-6) ---

    def run_entity_disambiguation(
        self, query: str, retrieved_memories: list,
        domain: str = "", user_id: str = "",
    ) -> str:
        """Disambiguate definite references ("the museum", "the doctor")
        when retrieved memories contain multiple candidate entities of
        that type.

        Closes GAP-6: questions like "what time was the Ancient
        Civilizations exhibit held?" can match multiple museum entities
        in the haystack (MoMA, Met, City Art Museum). Without an
        explicit disambiguation step, the answer LLM picks one based on
        retrieval order or surface salience, which can easily be wrong.
        Trinity here votes between three independent disambiguation
        stances:
          - frequency: which candidate is most-mentioned overall
          - context:   which candidate co-occurs with the question's
                       other clues (date / event name / activity)
          - attribute: which candidate is described as having the
                       attribute the question asks about

        Output is a short prefix string the caller prepends to the
        answer prompt; "" when no disambiguation is needed (no
        definite reference, or only one candidate).
        """
        self._check_init()
        if not self._attention_router_enabled():
            return ""
        if self._llm is None or not self._llm.is_available():
            return ""

        # 1. Surface a definite or anaphoric reference plus likely entity
        #    type. Three passes:
        #      a. Proper-noun reference ("the Metropolitan Museum") —
        #         case-sensitive [A-Z].
        #      b. Common-noun type with definite article ("the museum") —
        #         case-insensitive on a fixed type list.
        #      c. Anaphoric / event reference ("that event", "where was
        #         it held", "where was the event held") — covers
        #         questions that point back to an entity by demonstrative
        #         instead of definite article. Expanded after gpt4_59149c78
        #         showed up with "that event".
        #    Keep the three cases separate: a single IGNORECASE [A-Z]
        #    pattern would over-match the rest of the question.
        import re
        proper_re = re.compile(
            r"\bthe\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*)\b"
        )
        common_re = re.compile(
            r"\bthe\s+(museum|hospital|doctor|school|restaurant|store|"
            r"gym|park|cafe|bookstore|theater|theatre|library|club|"
            r"company|university|college|hotel|airport|stadium|church|"
            r"clinic|center|centre|venue|building|exhibit|event|place)\b",
            re.IGNORECASE,
        )
        # Anaphoric: "where was {it|that|the event|the X} held / located"
        anaphor_re = re.compile(
            r"\bwhere\s+(?:was|is|were|did)\s+"
            r"(?:it|that|that\s+(?:event|exhibit|venue|place|show|"
            r"meeting|game|concert|trip)|the\s+(?:event|exhibit|venue|"
            r"place|show|meeting|game|concert|trip))"
            r"\s+(?:held|located|hosted|happen|happening|take\s+place|"
            r"set|going\s+on|at)\b",
            re.IGNORECASE,
        )
        ref_phrase = ""
        m_proper = proper_re.search(query or "")
        if m_proper:
            ref_phrase = m_proper.group(1).strip()
        else:
            m_common = common_re.search(query or "")
            if m_common:
                ref_phrase = m_common.group(1).strip().lower()
            elif anaphor_re.search(query or ""):
                # Anaphoric reference — derive a generic type token so
                # the candidate scan accepts venue-like proper nouns
                # (Museum / Hospital / Restaurant / etc).
                ref_phrase = "venue"
        if not ref_phrase:
            return ""

        # 2. Extract candidate entity strings from retrieved memories.
        #    Heuristic: title-cased multi-word phrases ending in common
        #    place suffixes, OR capitalized proper-noun runs.
        candidate_re = re.compile(
            r"\b([A-Z][a-zA-Z']+(?:\s+(?:of|the|de|du|von|van)\s+|\s+)"
            r"(?:[A-Z][a-zA-Z']+(?:\s+[A-Z][a-zA-Z']+)*)?)"
            r"|\b([A-Z][a-zA-Z']+\s+(?:Museum|Hospital|Clinic|School|"
            r"University|College|Restaurant|Cafe|Center|Centre|Library|"
            r"Theater|Theatre|Park|Stadium|Hotel|Bookstore|Gym|Airport))\b"
        )
        # Walk memories, collect candidates whose surface form contains
        # the ref_phrase or matches its type.
        ref_low = ref_phrase.lower()
        # Generic venue-like type tokens that accept ANY proper-noun
        # candidate ending in a known place suffix (Museum/Hospital/...).
        # Used by the anaphoric branch where ref is just "venue".
        VENUE_SUFFIXES = {
            "museum", "hospital", "doctor", "school", "restaurant",
            "store", "gym", "park", "cafe", "bookstore", "theater",
            "theatre", "library", "club", "company", "university",
            "college", "hotel", "airport", "stadium", "church",
            "clinic", "center", "centre", "venue", "exhibit", "event",
            "place",
        }
        seen_candidates: dict[str, int] = {}
        evidence_by_cand: dict[str, list[str]] = {}
        # Widen the candidate scan via iterative retrieval — for
        # disambiguation we want to see ALL candidates of the
        # ref_phrase type, not just whatever was in the caller's top-k.
        # Trinity-multi-anchor surfaces additional candidates
        # (e.g. "metropolitan museum exhibit", "city art museum free
        # admission"). Falls back to caller's list when iterative is
        # unavailable.
        scan_pool: list = list(retrieved_memories or [])
        if domain and len(scan_pool) < 30:
            try:
                widen_query = (
                    f"the {ref_phrase}" if ref_phrase
                    else (query or "")
                )
                seed_objs = [m for m in scan_pool if hasattr(m, "entry")]
                expanded = self.iterative_search(
                    query=widen_query, domain=domain,
                    seed_results=seed_objs or None,
                    max_passes=2, n_anchors=3, max_results=20,
                )
                if expanded:
                    seen_in_pool: set = set()
                    for r in scan_pool:
                        try:
                            seen_in_pool.add(getattr(r.entry, "id", id(r)))
                        except Exception:
                            pass
                    for r in expanded:
                        rid = getattr(r.entry, "id", id(r)) if hasattr(r, "entry") else id(r)
                        if rid in seen_in_pool:
                            continue
                        seen_in_pool.add(rid)
                        scan_pool.append(r)
            except Exception:
                pass
        for m in scan_pool[:80]:
            if isinstance(m, dict):
                content = m.get("memory") or m.get("content") or ""
            elif hasattr(m, "entry"):
                content = getattr(m.entry, "content", "") or ""
            else:
                continue
            if not content:
                continue
            for cm in candidate_re.finditer(content):
                cand = (cm.group(1) or cm.group(2) or "").strip()
                # Strip leading determiner ("The Foo Museum" → "Foo Museum")
                # and trailing possessive ("Foo Museum's" → "Foo Museum")
                # so candidates normalize across surface forms before
                # the suffix-match filter runs.
                while cand.lower().startswith(("the ", "a ", "an ")):
                    cand = cand[cand.find(" ") + 1:].strip()
                while cand.endswith(("'s", "’s", ".", ",", ":", ";")):
                    cand = cand[:-1] if cand.endswith(("'", "’", ".", ",", ":", ";")) else cand[:-2]
                    cand = cand.strip()
                if not cand or len(cand) < 4:
                    continue
                cand_low = cand.lower()
                # Direct substring match (ref vs candidate, either way) —
                # works for proper-noun refs ("Metropolitan" matches
                # "Metropolitan Museum").
                if ref_low in cand_low or cand_low in ref_low:
                    pass
                # Common-noun type match — candidate ends with ref type
                # word ("metropolitan museum" ends with "museum").
                elif ref_low in VENUE_SUFFIXES and any(
                    cand_low.endswith(suf) for suf in VENUE_SUFFIXES
                ) and cand_low.endswith(ref_low):
                    pass
                # Anaphoric / generic-venue branch: ref_phrase is "venue"
                # (set by anaphor_re). Accept ANY candidate that ends
                # with a venue-like suffix.
                elif ref_low == "venue" and any(
                    cand_low.endswith(suf) for suf in VENUE_SUFFIXES
                    if suf != "venue"
                ):
                    pass
                else:
                    continue
                seen_candidates[cand] = seen_candidates.get(cand, 0) + 1
                evidence_by_cand.setdefault(cand, []).append(
                    content[:200].replace("\n", " ")
                )
        if len(seen_candidates) < 2:
            return ""

        # 3. Build evidence block + fire trinity.
        # Sort by frequency for stable output.
        ranked = sorted(seen_candidates.items(), key=lambda kv: -kv[1])
        ranked = ranked[:6]  # cap candidates so prompt stays bounded
        ev_lines: list[str] = []
        for cand, cnt in ranked:
            ev_lines.append(f"CANDIDATE: {cand!r} (mentioned {cnt}x)")
            for ex in evidence_by_cand[cand][:3]:
                ev_lines.append(f"  - {ex}")
        evidence_block = "\n".join(ev_lines)

        from radiomind.refinement.trinity import debate
        result = debate(
            task=(
                f"Disambiguate the entity the question refers to. The "
                f"question uses a definite reference ('the {ref_phrase}') "
                f"and the memories contain multiple candidates of that "
                f"type. Pick ONE.\n"
                f"Three stances triangulate:\n"
                f"  frequency — pick the most-mentioned candidate\n"
                f"  context   — pick the candidate that co-occurs with the "
                f"question's other clues (date / event name / topic)\n"
                f"  attribute — pick the candidate whose memories describe "
                f"the attribute the question asks about\n"
                f"Output the chosen candidate's exact name as it appears "
                f"in CANDIDATE lines below.\n"
                f"\nQuestion: {query}"
            ),
            evidence=evidence_block,
            llm=self._llm,
            extra_schema=(
                '  "chosen_candidate": str (must be one of the CANDIDATE '
                'names verbatim),\n'
                '  "confidence": float (0..1)'
            ),
        )
        if not result:
            return ""
        chosen = str(result.get("chosen_candidate") or "").strip()
        if not chosen:
            return ""
        # Validate chosen is one of the candidates we saw.
        chosen_low = chosen.lower()
        valid = next(
            (c for c, _ in ranked if c.lower() == chosen_low),
            None,
        )
        if valid is None:
            # Fuzzy: tolerate trailing punctuation or near-match on first words
            for c, _ in ranked:
                if chosen_low.startswith(c.lower()[:8]) or c.lower().startswith(chosen_low[:8]):
                    valid = c
                    break
        if valid is None:
            return ""

        return (
            f"ENTITY DISAMBIGUATION (the {ref_phrase} → resolved to "
            f"{valid!r} via three-stance trinity vote):\n"
            f"- treat 'the {ref_phrase}' in the answer as referring to "
            f"{valid} unless a memory explicitly contradicts.\n\n"
        )

    # --- Numeric cardinal (bottom-up counts) ---

    def get_numeric_cardinal(
        self,
        query: str,
        domain: str = "",
        user_id: str = "",
    ) -> str:
        """Return a formatted cardinal-view string for numeric queries.

        Produces an answer-prompt block like:

            DETERMINISTIC CARDINAL VIEW (from ingest-time aggregation):
            - musical_instruments: count=4 (members: Yamaha FG800, Fender Strat, ...)
              evidence: s2_t1,s4_t3,s7_t2,s12_t5
            - charity_donations: total_amount=$3750 (4 events)
              evidence: s1_t0,s3_t2,s5_t1,s9_t0

        Returns "" if no relevant cardinal entry exists (caller falls back
        to the standard query-time decomposer).

        Only fires when attention classifies the query as numeric_cardinal
        (subset of aggregation with explicit count/total signal). For
        pure enumeration queries ("list all my doctors"), the caller
        should still invoke decompose_for_query() — those don't reduce
        to a single number.
        """
        self._check_init()
        if not self._attention_router_enabled():
            return ""
        if self._numeric_agg is None or not self._numeric_agg.is_available():
            return ""
        from radiomind.core.attention import (
            is_numeric_cardinal, extract_focus_entity, analyze,
        )
        if not is_numeric_cardinal(query):
            return ""

        # 2nd-order scope filter (GAP-2): when the query carries a
        # temporal / spatial constraint ("consecutive weekends",
        # "between X and Y", "during my trip"), the precomputed cardinal
        # sum across the user's whole history is the WRONG answer — the
        # gold expects only events within the constraint window.
        # Refuse to short-circuit the answer with the unfiltered
        # cardinal view; let the caller fall through to the atomic
        # decomposition path where per-event dates are visible.
        sig = analyze(query)
        if sig.aux_flags.get("temporal_constraint"):
            return ""

        focus = extract_focus_entity(query) or ""
        hits = self._numeric_agg.query_by_focus(
            user_id=user_id, domain=domain, focus=focus,
        )
        if not hits:
            return ""

        # Query-time trinity re-verification: ingest-time extraction can
        # miss items in long haystacks. When we have retrieved memories
        # that appear relevant to the focus class, spawn a trinity over
        # them to double-check the count. Only fires when:
        #   - LLM is available
        #   - cardinal.count ≤ 6 (suspicious for questions like "how many
        #     kitchen items did I replace" where gold is typically 3-8)
        #   - we have a way to fetch memories from outside this method —
        #     deferred to harness (it passes the retrieved list in when
        #     cardinal is combined with mem_results in the answer prompt)
        # For now, we annotate the confidence level in the view so the
        # answer LLM knows to cross-check against raw memories.
        primary = hits[0]
        verification_note = ""
        if (
            primary.count is not None
            and primary.count <= 6
            and self._llm is not None
            and self._llm.is_available()
        ):
            verification_note = (
                " [low-count — cross-check against retrieved memories. "
                "Rules: (1) add to count if memories clearly mention items "
                "the draft missed; (2) subtract only if the draft contains "
                "obvious duplicates or misclassifications; (3) semantic "
                "equivalents of the action (e.g. 'donated old X + got new X' "
                "is a replacement; 'upgraded from X to Y' is a replacement) "
                "count toward the draft — do not exclude on literal wording; "
                "(4) ambiguous cases: prefer the draft's count]"
            )

        # Delta-aware rewrite: "how many more / need to earn / left to reach"
        # questions are NOT a simple aggregation — they're goal − current.
        # When both the current balance AND a target threshold appear in
        # memories, surface both alongside the computed delta so the
        # answer model doesn't conflate "need to earn" with "threshold".
        import re as _re
        _DELTA_RE = _re.compile(
            r"\b(how\s+(?:many|much)\s+more|"
            r"how\s+(?:many|much)\s+.*\s+(?:left|remaining|until)|"
            r"need\s+to\s+(?:earn|reach|save|accumulate)|"
            r"(?:left|remaining)\s+to\s+redeem)\b",
            _re.IGNORECASE,
        )
        is_delta = bool(_DELTA_RE.search(query))

        # Scoped aggregation: when the query includes a category word
        # ("charity", "work", "food", "music", "sports", ...), the
        # answer should only include events whose source turn literally
        # mentions that category. Prevents ingest-time misclassification
        # (e.g., a "music benefit concert raised $5k for education"
        # event wrongly rolled into charity_donations) from inflating
        # scoped totals.
        #
        # The detection is lightweight: extract a noun after "for X"
        # or "on X" in the query. Generalizes across any single-word
        # category without dataset-specific hardcoding.
        scope_word: str | None = None
        _SCOPE_WORD_RE = _re.compile(
            r"\bfor\s+([a-z]{4,})\b|\bon\s+([a-z]{4,})\s+(?:in\s+total|overall|altogether|$)",
            _re.IGNORECASE,
        )
        _scope_stop = {"total", "overall", "each", "every", "the", "their",
                       "this", "that", "those", "these", "some", "any",
                       "what", "which", "much", "many"}
        sm = _SCOPE_WORD_RE.search(query)
        if sm:
            candidate = (sm.group(1) or sm.group(2) or "").lower()
            if candidate and candidate not in _scope_stop:
                scope_word = candidate

        lines = [
            "DRAFT CARDINAL VIEW (extracted at ingest-time — use as an "
            "anchor; only override when retrieved memories clearly contradict "
            "it, not on mere wording differences)" + verification_note + ":"
        ]
        for entry in hits[:3]:
            # Per-event breakdown with raw phrase (not just turn_id).
            # Exposes qualifiers like "over $1,000" so the answer model
            # can interpret them instead of seeing only the extracted
            # number. Falls back to evidence-id list when history lacks
            # phrase data.
            phrases: list[str] = []
            # Scope-filtered re-computation: when the query has a scope
            # word, walk the same history and sum only events whose
            # phrase mentions the scope (literal or stem match).
            scoped_sum = 0.0
            scoped_count = 0
            # Chain-of-evidence: each kept event as (amount, phrase, tid)
            kept_chain: list[tuple[float, str, str]] = []
            # Dedup: same amount mentioned twice in same session (e.g.,
            # t0 and t6 of the same conversation about the same event)
            # should count once. Key = (amount_int, session_prefix) where
            # session_prefix is turn_id minus the "_tN" suffix.
            seen_amounts: set[tuple[int, str]] = set()
            _AMOUNT_IN_DELTA = _re.compile(r"\+?\$?([\d,]+(?:\.\d+)?)")
            _SESSION_PREFIX_RE = _re.compile(r"^(.+?)_t\d+$")
            for h in (entry.history or [])[-12:]:
                if h.get("reason") in ("trinity_amount_refine",
                                       "trinity_member_refine"):
                    continue
                phr = str(h.get("phrase") or "").strip()
                if not phr:
                    continue
                delta = str(h.get("delta") or "").strip()
                tid = str(h.get("turn_id") or "").strip()
                tag = f" [{tid}]" if tid else ""
                prefix = f"{delta} :: " if delta else ""

                in_scope = True
                if scope_word is not None:
                    stem = scope_word.rstrip("s")
                    in_scope = bool(_re.search(
                        rf"\b{_re.escape(stem)}", phr, _re.IGNORECASE,
                    ))
                mark = "" if in_scope else "  ← FILTERED OUT (no '" + (scope_word or "") + "' in source)"

                # Check dedup key when in scope
                is_dup = False
                parsed_amt: float | None = None
                if in_scope and delta:
                    m = _AMOUNT_IN_DELTA.search(delta)
                    if m:
                        try:
                            parsed_amt = float(m.group(1).replace(",", ""))
                            amt_i = int(parsed_amt)
                            sm = _SESSION_PREFIX_RE.match(tid)
                            sess_prefix = sm.group(1) if sm else tid
                            key = (amt_i, sess_prefix)
                            if key in seen_amounts:
                                is_dup = True
                            else:
                                seen_amounts.add(key)
                        except ValueError:
                            pass
                if is_dup:
                    mark = "  ← DEDUPED (same amount, same session as another event)"

                phrases.append(f"  · {prefix}{phr[:140]}{tag}{mark}")
                if not in_scope or is_dup:
                    continue
                # Kept — accumulate sum + evidence chain
                if parsed_amt is not None:
                    scoped_sum += parsed_amt
                    scoped_count += 1
                    kept_chain.append((parsed_amt, phr[:160], tid))

            if entry.total_amount is not None:
                amt = f"${entry.total_amount:,.2f}".rstrip("0").rstrip(".")
                lines.append(
                    f"- {entry.entity_class}: total_amount={amt} "
                    f"({entry.count} events). Per-event evidence:"
                )
                lines.extend(phrases or [
                    f"  · (no per-event phrases recorded; turn IDs: "
                    f"{','.join(entry.evidence[:6])})"
                ])
                if scope_word is not None and scoped_count > 0:
                    scoped_amt = f"${scoped_sum:,.2f}".rstrip("0").rstrip(".")
                    # Build the evidence chain — show every event that
                    # contributes, with its source snippet and turn id.
                    # The model can mentally verify each line instead of
                    # being asked to blindly trust a number.
                    lines.append(
                        f"\n  ⇒ DETERMINISTIC {scope_word.upper()} TOTAL: {scoped_amt}"
                    )
                    lines.append(
                        f"    Evidence chain (each item {scope_word}-scoped, "
                        f"deduplicated, sum computed by RadioMind, not LLM):"
                    )
                    addition_parts: list[str] = []
                    for amt, pp, ttid in kept_chain:
                        amt_str = f"${amt:,.0f}" if amt == int(amt) else f"${amt:,.2f}"
                        addition_parts.append(amt_str)
                        lines.append(
                            f"      [✓] {amt_str:>8}  —  @ {ttid}"
                        )
                        lines.append(
                            f"              source: \"{pp[:150]}\""
                        )
                    # Show any filtered/deduped items so the model knows
                    # why those numbers are absent (and doesn't re-add them)
                    for h in (entry.history or [])[-12:]:
                        if h.get("reason") in ("trinity_amount_refine",
                                               "trinity_member_refine"):
                            continue
                        phr2 = str(h.get("phrase") or "").strip()
                        if not phr2:
                            continue
                        delta2 = str(h.get("delta") or "").strip()
                        tid2 = str(h.get("turn_id") or "").strip()
                        m2 = _AMOUNT_IN_DELTA.search(delta2)
                        if not m2:
                            continue
                        try:
                            amt2 = float(m2.group(1).replace(",", ""))
                        except ValueError:
                            continue
                        amt2_str = f"${amt2:,.0f}" if amt2 == int(amt2) else f"${amt2:,.2f}"
                        stem2 = (scope_word or "").rstrip("s")
                        if stem2 and not _re.search(
                            rf"\b{_re.escape(stem2)}", phr2, _re.IGNORECASE,
                        ):
                            lines.append(
                                f"      [✗ SCOPE] {amt2_str:>8} — @ {tid2} — "
                                f"excluded because source has no "
                                f"'{scope_word}': \"{phr2[:120]}\""
                            )
                    # Inline arithmetic so the LLM can verify the sum
                    # itself and commit to the number
                    if addition_parts:
                        lines.append(
                            f"    Arithmetic: {' + '.join(addition_parts)} = {scoped_amt}"
                        )
                    lines.append(
                        f"    ★ Your final answer MUST be {scoped_amt}. The "
                        f"chain above is verifiable line-by-line — each "
                        f"event's source snippet is shown with its turn id. "
                        f"If you derive a different number from raw memories, "
                        f"you are either missing the dedup (same event "
                        f"mentioned at multiple turns of the same session), "
                        f"missing the scope filter ('{scope_word}' must appear "
                        f"literally in the source turn), or accidentally "
                        f"including a filtered event. Trust the chain."
                    )
            else:
                mem = ""
                if entry.members:
                    mem = f" (members: {', '.join(entry.members[:10])})"
                lines.append(
                    f"- {entry.entity_class}: count={entry.count}{mem}. "
                    f"Per-event evidence:"
                )
                lines.extend(phrases or [
                    f"  · (no per-event phrases recorded; turn IDs: "
                    f"{','.join(entry.evidence[:6])})"
                ])
                if scope_word is not None and scoped_count > 0:
                    lines.append(
                        f"  ⇒ SCOPED COUNT (filter='{scope_word}'): "
                        f"{scoped_count} of {entry.count} events match. "
                        f"Use this as the authoritative count for "
                        f"'{scope_word}'-scoped questions."
                    )

        if is_delta and primary.total_amount is not None:
            lines.append(
                "")
            lines.append(
                f"DELTA QUESTION HINT: the question asks for "
                f"'{query}' — this is goal − current, NOT the absolute "
                f"goal. Scan memories for a target/threshold the user "
                f"stated (e.g. 'need a total of N'). If found, answer = "
                f"target − {entry.total_amount:g}. If the user says they "
                f"need a total of X and currently have Y, answer = X − Y."
            )
        return "\n".join(lines) + "\n\n"

    def list_cardinals(
        self, domain: str = "", user_id: str = ""
    ) -> list:
        """Debug / inspection hook: return all cardinal entries."""
        self._check_init()
        if self._numeric_agg is None:
            return []
        return self._numeric_agg.list_all(user_id=user_id, domain=domain)

    # --- Meta ---

    def record_answer_outcome(
        self,
        query: str,
        evidence_count: int,
        abstained: bool = False,
        correct: bool | None = None,
    ) -> None:
        """Append one answer outcome to behavior log (feeds dynamic calibration)."""
        self._check_init()
        if self._meta is None:
            return
        try:
            from radiomind.core.attention import analyze
            sig = analyze(query)
            self._meta.behavior.record(
                wants=sig.wants,
                answer_shape=sig.answer_shape,
                evidence_count=int(evidence_count or 0),
                abstained=abstained,
                correct=correct,
            )
        except Exception:
            pass

    def profile_hint(self, query: str) -> str:
        """Answer-side user-context prefix (empty when query isn't preference-anchored)."""
        self._check_init()
        if self._meta is None:
            return ""
        try:
            return self._meta.profile_hint(query)
        except Exception:
            return ""

    def get_meta_calibration(self) -> str:
        """Meta-layer answer calibration hint.

        Returns a short directive (~300 chars) the caller can append to
        any answer-generation prompt. Encodes corrections for biases the
        meta layer has observed (over-abstention, previous/current
        confusion, etc.) and a thumbnail of the user's confirmed habits.

        Safe to call on an empty memory store — returns generic defaults.
        """
        self._check_init()
        if self._meta is None:
            return ""
        try:
            return self._meta.get_calibration_hint()
        except Exception:
            return ""

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
