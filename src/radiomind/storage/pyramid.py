"""L2 Pyramid Search — attention-style multi-level retrieval.

Like 3D NAND: scan top layer first (principles), drill down to patterns, then facts.
Efficiency gain: ~7x vs flat search.
"""

from __future__ import annotations

from radiomind.core.llm import LLMRouter
from radiomind.core.types import MemoryEntry, MemoryLevel, PrivacyLevel, SearchResult
from radiomind.storage.database import MemoryStore

AGGREGATE_THRESHOLD = 10  # facts needed before triggering pattern extraction
AGGREGATE_PROMPT = """You are a memory analyst. Given these facts about a user in the "{domain}" domain, identify one concise pattern or habit.

Facts:
{facts}

Respond with ONLY the pattern in one sentence. No explanation."""

PRINCIPLE_PROMPT = """You are a memory analyst. Given these patterns about a user, extract one high-level principle.

Patterns:
{patterns}

Respond with ONLY the principle in one sentence. No explanation."""


RRF_K = 60  # standard RRF constant (TREC best practice)


# --- Temporal query handling ---
# Questions asking "when" (including 何时/什么时候/几月/哪天/date patterns)
# benefit from up-weighting memories that contain explicit dates or times.
# This is the hook P3 audit flagged: LoCoMo10 cat3 (temporal reasoning)
# scored 0.000 because vector + FTS + LIKE are all lexical — none of them
# know that a memory mentioning \"May 7, 2023\" is a better candidate for
# \"when did X go to Y\" than one that doesn't.
import re as _re

_TEMPORAL_QUERY_MARKERS = (
    "when ", "what day", "what date", "what year", "what month",
    "which day", "which date", "which year", "which month",
    "how long ago", "how many days", "how many weeks", "how many months",
    "什么时候", "何时", "哪天", "哪一天", "几月", "几号", "何年何月",
    "多久以前", "多长时间",
)

# Matches explicit dates in memory content. Compiled once; cheap to reuse.
_DATE_PATTERNS = _re.compile(
    r"\b(?:"
    r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?"                 # 2023-05-07, 2023年5月7日
    r"|\d{1,2}[-/月]\d{1,2}日?(?:[, ]+\d{4})?"           # 5/7/2023, 5月7日
    r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.? \d{1,2}(?:[,\s]+\d{4})?"
    r"|\d{1,2}:\d{2}(?:\s*[ap]m)?"                         # 3:45pm
    r")",
    _re.IGNORECASE,
)


def _is_temporal_query(q: str) -> bool:
    ql = q.lower()
    return any(m in ql for m in _TEMPORAL_QUERY_MARKERS)


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _cjk_ngrams(text: str, n: int = 2) -> list[str]:
    """Extract CJK character n-grams from a query.

    Example: "我叫什么名字" (n=2) → ["我叫", "叫什", "什么", "么名", "名字"]
    Non-CJK characters are treated as segment boundaries.
    """
    segments: list[str] = []
    buf: list[str] = []
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff":
            buf.append(ch)
        else:
            if buf:
                segments.append("".join(buf))
                buf = []
    if buf:
        segments.append("".join(buf))

    ngrams: list[str] = []
    seen: set[str] = set()
    for seg in segments:
        if len(seg) < n:
            if seg and seg not in seen:
                seen.add(seg)
                ngrams.append(seg)
            continue
        for i in range(len(seg) - n + 1):
            g = seg[i : i + n]
            if g not in seen:
                seen.add(g)
                ngrams.append(g)
    return ngrams


class PyramidSearch:
    """Attention-style hierarchical memory retrieval.

    Retrieval strategy (priority order):
      1. Vector search (semantic, via embedding)
      2. FTS5 (lexical, BM25-ranked)
      3. LIKE fallback (substring, low-signal)

    Results fused with Reciprocal Rank Fusion:
        score = sum(1 / (k + rank_in_each_list))
    """

    def __init__(self, store: MemoryStore, embedder=None, reranker=None, query_rewriter=None, kg=None):
        self._store = store
        self._embedder = embedder  # optional EmbeddingEncoder
        self._reranker = reranker  # optional CrossEncoderReranker
        self._query_rewriter = query_rewriter  # optional QueryRewriter
        self._kg = kg  # optional KnowledgeGraph — used for temporal/entity queries

    def set_embedder(self, embedder) -> None:
        self._embedder = embedder

    def set_reranker(self, reranker) -> None:
        self._reranker = reranker

    def set_query_rewriter(self, rewriter) -> None:
        self._query_rewriter = rewriter

    def set_kg(self, kg) -> None:
        self._kg = kg

    def search(
        self,
        query: str,
        start_level: int = 2,
        max_results: int = 10,
        domain: str | None = None,
    ) -> list[SearchResult]:
        """Hybrid retrieval with RRF fusion + privacy/domain filtering."""
        candidates: list[list[SearchResult]] = []

        # Query rewriting: if a rewriter is configured, generate paraphrased
        # variants and retrieve for EACH. RRF naturally gives rank-weighted
        # votes — a doc that shows up high across multiple paraphrasings wins.
        queries = [query]
        if self._query_rewriter is not None:
            try:
                queries = self._query_rewriter.rewrite(query) or [query]
            except Exception:
                queries = [query]

        # 1. Vector search per query variant
        if self._embedder is not None and getattr(self._embedder, "is_available", False):
            for q in queries:
                q_emb = self._embedder.encode(q)
                if q_emb:
                    vec_results = self._store.search_vector(q_emb, limit=max_results * 2)
                    if vec_results:
                        candidates.append(vec_results)

        # 2. FTS5 per query variant
        for q in queries:
            fts_results = self._store.search_fts(q, limit=max_results * 2)
            if fts_results:
                candidates.append(fts_results)

        # 3. LIKE — always run for CJK (unicode61 FTS tokenizes CJK by
        #    punctuation, missing mid-string matches). For ASCII-only
        #    queries LIKE acts as fallback when FTS+vector are empty.
        if _has_cjk(query) or not candidates:
            # Also expand with CJK bigrams if the single LIKE finds nothing
            like_results = self._store.search_like(query, limit=max_results * 2)
            if not like_results and _has_cjk(query):
                for ngram in _cjk_ngrams(query, n=2):
                    like_results.extend(
                        self._store.search_like(ngram, limit=max_results)
                    )
                # Dedup by id, preserve order
                seen = set()
                unique = []
                for r in like_results:
                    if r.entry.id not in seen:
                        seen.add(r.entry.id)
                        unique.append(r)
                like_results = unique[: max_results * 2]
            if like_results:
                candidates.append(like_results)

        # 3b. Knowledge Graph candidates — for temporal/entity queries,
        #     the KG has structured facts (subject, relation, object, valid_from,
        #     valid_until). We extract mentioned entities from the query, pull
        #     relevant triples, then back-resolve them to memory entries via
        #     source_id. This is the fix for temporal-reasoning (0.15) and a
        #     lift for multi-session (entity cross-reference).
        if self._kg is not None:
            kg_candidates = self._kg_candidates(query, queries, max_results=max_results)
            if kg_candidates:
                candidates.append(kg_candidates)

        # 4. Temporal boost: for "when/什么时候/..." questions, a small set
        #    of date-bearing memories is a very strong prior. We fuse this
        #    into RRF rather than replacing lexical results so it helps
        #    temporal queries without hurting the common case.
        if _is_temporal_query(query) and candidates:
            # Pick the top lexical matches that actually mention a date.
            dated: list[SearchResult] = []
            seen_ids: set[int] = set()
            for result_list in candidates:
                for r in result_list:
                    if r.entry.id in seen_ids:
                        continue
                    if _DATE_PATTERNS.search(r.entry.content):
                        seen_ids.add(r.entry.id)
                        dated.append(SearchResult(
                            entry=r.entry, score=1.0, method="temporal"
                        ))
                if len(dated) >= max_results * 2:
                    break
            if dated:
                candidates.append(dated[: max_results * 2])

        # RRF fusion. Pull a wider top-N when a reranker is available so
        # it has enough candidates to actually improve ordering.
        rrf_limit = max(max_results, 20) if self._reranker is not None else max_results
        fused = self._rrf_fuse(candidates, rrf_limit)

        # 5. Cross-encoder rerank (optional, high quality path).
        # Takes RRF's top-20 and re-scores with a pairwise
        # (query, candidate) cross-encoder. This is where most published
        # retrieval systems get their last +10-20% R@5.
        if self._reranker is not None and len(fused) > max_results:
            try:
                pairs = [(query, r.entry.content) for r in fused[: rrf_limit]]
                scores = self._reranker.predict(pairs)
                for r, s in zip(fused[: rrf_limit], scores):
                    r.score = float(s)
                    r.method = "rerank"
                fused = sorted(fused[: rrf_limit], key=lambda r: r.score, reverse=True)
            except Exception:
                pass  # fall through to RRF ordering on any reranker error

        # Filter + privacy + record hits
        filtered: list[SearchResult] = []
        for r in fused:
            if domain is not None and r.entry.domain != domain:
                continue
            if not self._privacy_allows(r.entry, domain):
                continue
            filtered.append(r)

        filtered.sort(key=lambda r: (-r.entry.level, -r.score))

        # 6. Contextualized retrieval ("nucleus expansion").
        # MemMachine's key finding: retrieving a single turn often loses
        # the Q/A structure needed to answer. For each top result, if its
        # metadata carries session/turn info, we look up adjacent turns
        # in the same session and include them as "context" results with
        # a reduced score. This is domain-agnostic — only kicks in when
        # the metadata has session_id + turn_idx.
        filtered = self._expand_with_context(filtered, max_results)

        for r in filtered[:max_results]:
            if r.entry.id is not None:
                self._store.record_hit(r.entry.id)

        return filtered[:max_results]

    def _kg_candidates(self, query: str, queries: list[str], max_results: int = 10) -> list[SearchResult]:
        """Pull memories backed by KG triples matching query entities/relations.

        Strategy:
          1. Extract entity mentions from query using the KG's own triple
             extraction patterns (they already know 'user', 'likes', etc.)
          2. For each entity, pull triples (current + as_of if temporal)
          3. Look up the source_id of each triple → find corresponding
             memory entry
          4. Return as SearchResult list

        This is cheap: KG queries are sub-millisecond SQL lookups.
        """
        if self._kg is None:
            return []

        try:
            # Collect candidate subjects from all query variants
            subjects: set[str] = set()
            for q in queries:
                triples = self._kg.extract_triples_from_text(q)
                for subj, _, _ in triples:
                    subjects.add(subj)
                # Heuristic: if query mentions an entity we know about, include it.
                # Extract likely proper nouns (capitalized tokens, CJK name patterns)
                for tok in _re.findall(r"[A-Z][a-zA-Z]+|[\u4e00-\u9fff]{2,4}", q):
                    resolved = self._kg.resolve(tok) if hasattr(self._kg, "resolve") else tok.lower()
                    if resolved:
                        subjects.add(resolved)

            if not subjects:
                return []

            # For temporal queries, query as_of snapshots (use valid_from time of
            # any triple as a timestamp signal). For non-temporal, use current.
            is_temporal = _is_temporal_query(query)

            triple_entries: list[tuple] = []  # (source_id, triple)
            for subj in list(subjects)[:5]:  # cap entity count
                if is_temporal:
                    triples = self._kg.timeline(subj)
                else:
                    triples = self._kg.query_entity(subj)
                for t in triples:
                    if t.source_id is not None:
                        triple_entries.append((t.source_id, t))

            if not triple_entries:
                return []

            # Back-resolve source_id → memory entry
            results: list[SearchResult] = []
            seen_ids: set[int] = set()
            for src_id, triple in triple_entries[: max_results * 2]:
                if src_id in seen_ids:
                    continue
                seen_ids.add(src_id)
                entry = self._store.get(src_id)
                if entry is None:
                    continue
                # Score by triple confidence
                results.append(SearchResult(entry=entry, score=float(triple.confidence), method="kg"))

            return results[: max_results * 2]
        except Exception:
            # KG integration is additive — never fail the whole search on KG errors
            return []

    def _expand_with_context(
        self, results: list[SearchResult], max_results: int, window: int = 1,
    ) -> list[SearchResult]:
        """For each top-K result with session metadata, pull adjacent turns.

        A turn like "Yes, I did." is worthless alone — the question giving
        it meaning lives in the previous turn. MemMachine v0.2 attributes
        ~+5 pt on LongMemEval to this single change.

        CRITICAL: nuclei are ALWAYS returned first (so that callers slicing
        [:max_results] still get max_results nuclei, not mixed with context).
        Context turns are appended afterward at indices
        [max_results, 2 * max_results).
        """
        if not results:
            return results

        seen_ids: set[int] = {r.entry.id for r in results if r.entry.id is not None}
        nuclei = list(results[:max_results])  # preserved in original order
        context_adds: list[SearchResult] = []
        expansion_score_discount = 0.3

        for r in nuclei:
            meta = r.entry.metadata or {}
            session_key, turn_idx = self._parse_turn_pos(meta)
            if session_key is None:
                continue
            domain = r.entry.domain
            neighbors = self._fetch_neighbors(domain, session_key, turn_idx, window)
            for nb in neighbors:
                if nb.id is None or nb.id in seen_ids:
                    continue
                seen_ids.add(nb.id)
                context_adds.append(SearchResult(
                    entry=nb,
                    score=r.score * (1 - expansion_score_discount),
                    method="context",
                ))

        # nuclei first, contexts after — callers slicing [:K] keep K nuclei
        return nuclei + context_adds

    @staticmethod
    def _parse_turn_pos(meta: dict) -> tuple[str | None, int | None]:
        """Extract (session_id, turn_idx) from metadata."""
        # Explicit keys
        if "session" in meta and "turn_idx" in meta:
            return (str(meta["session"]), int(meta["turn_idx"]))
        # LoCoMo-style "turn_id": "D1:3" means session D1, turn 3
        tid = meta.get("turn_id", "") or meta.get("evidence_id", "")
        if tid and ":" in tid:
            sess, _, turn = tid.partition(":")
            # strip any trailing suffix like "_t3"
            if turn.startswith("t") and turn[1:].isdigit():
                turn = turn[1:]
            elif "_t" in turn:
                turn = turn.split("_t")[-1]
            if turn.isdigit():
                return (sess, int(turn))
        # LongMemEval-style "answer_{id}_2_t5"
        if "_t" in tid:
            base, _, turn_str = tid.rpartition("_t")
            if turn_str.isdigit():
                return (base, int(turn_str))
        return (None, None)

    def _fetch_neighbors(
        self, domain: str, session_key: str, turn_idx: int, window: int,
    ) -> list:
        """Pull ±window adjacent turns from the same session."""
        if window <= 0:
            return []
        # Scan domain's FACT entries for matching session with nearby turn_idx.
        # For our benchmark scale this is cheap; for production scale, add a
        # (domain, session, turn_idx) index if it becomes hot.
        entries = self._store.list_by_domain(domain, limit=500)
        neighbors = []
        target_range = set(range(turn_idx - window, turn_idx + window + 1)) - {turn_idx}
        for e in entries:
            sess, tidx = self._parse_turn_pos(e.metadata or {})
            if sess == session_key and tidx in target_range:
                neighbors.append(e)
        neighbors.sort(key=lambda e: self._parse_turn_pos(e.metadata or {})[1] or 0)
        return neighbors

    @staticmethod
    def _rrf_fuse(
        lists: list[list[SearchResult]], limit: int
    ) -> list[SearchResult]:
        """Reciprocal Rank Fusion: combine multiple ranked lists."""
        if not lists:
            return []
        if len(lists) == 1:
            return lists[0][:limit]

        scored: dict[int, tuple[float, SearchResult]] = {}
        for result_list in lists:
            for rank, r in enumerate(result_list):
                if r.entry.id is None:
                    continue
                contribution = 1.0 / (RRF_K + rank + 1)
                if r.entry.id in scored:
                    prev_score, prev_result = scored[r.entry.id]
                    prev_result.score = prev_score + contribution
                    scored[r.entry.id] = (prev_score + contribution, prev_result)
                else:
                    # Clone result so we don't mutate input
                    fused_result = SearchResult(
                        entry=r.entry,
                        score=contribution,
                        method="rrf",
                    )
                    scored[r.entry.id] = (contribution, fused_result)

        merged = sorted(scored.values(), key=lambda x: x[0], reverse=True)
        return [result for _, result in merged[:limit]]

    def drill_down(self, entry_id: int) -> list[MemoryEntry]:
        """Expand a higher-level entry to its children (drill down the pyramid)."""
        return self._store.get_children(entry_id)

    @staticmethod
    def _privacy_allows(entry: MemoryEntry, search_domain: str | None) -> bool:
        """Check if privacy level allows this entry in search results.

        domain=None means "search all" (user's own query), not "cross-domain".
        Privacy filtering only kicks in when searching FROM a specific different domain.
        """
        if search_domain is None:
            # User-initiated search across all domains: sealed hidden, everything else visible
            return entry.privacy != PrivacyLevel.SEALED
        if entry.domain == search_domain:
            # Searching within same domain: always visible
            return True
        # Cross-domain: check privacy
        if entry.privacy == PrivacyLevel.SEALED:
            return False
        if entry.privacy == PrivacyLevel.GUARDED:
            return entry.level >= MemoryLevel.PATTERN
        return True

    def search_pyramid(
        self,
        query: str,
        domain: str | None = None,
        max_results: int = 10,
    ) -> list[SearchResult]:
        """Full pyramid search: top-down with expansion.

        1. Search at principle level
        2. If hits, expand to children
        3. If no principle hits, search patterns directly
        4. If no pattern hits, search facts
        """
        results: list[SearchResult] = []
        seen_ids: set[int] = set()

        # Level 2: Principles
        principles = self._search_level(query, MemoryLevel.PRINCIPLE, domain, limit=3)
        for r in principles:
            if r.entry.id not in seen_ids:
                seen_ids.add(r.entry.id)
                results.append(r)
                # Expand to children
                children = self.drill_down(r.entry.id)
                for child in children:
                    if child.id not in seen_ids:
                        seen_ids.add(child.id)
                        results.append(SearchResult(entry=child, score=r.score * 0.8, method="drill"))

        # Level 1: Patterns (supplement if few principle hits)
        if len(results) < max_results:
            patterns = self._search_level(query, MemoryLevel.PATTERN, domain, limit=5)
            for r in patterns:
                if r.entry.id not in seen_ids:
                    seen_ids.add(r.entry.id)
                    results.append(r)

        # Level 0: Facts (supplement if still few)
        if len(results) < max_results:
            facts = self._search_level(query, MemoryLevel.FACT, domain, limit=10)
            for r in facts:
                if r.entry.id not in seen_ids:
                    seen_ids.add(r.entry.id)
                    results.append(r)

        # Record hits
        for r in results[:max_results]:
            if r.entry.id is not None:
                self._store.record_hit(r.entry.id)

        return results[:max_results]

    def _search_level(
        self,
        query: str,
        level: MemoryLevel,
        domain: str | None,
        limit: int,
    ) -> list[SearchResult]:
        """Search within a specific pyramid level."""
        fts = self._store.search_fts(query, limit=limit * 2)
        like = self._store.search_like(query, limit=limit)

        results = []
        seen = set()
        for r in fts + like:
            if r.entry.id not in seen and r.entry.level == level:
                if domain is None or r.entry.domain == domain:
                    seen.add(r.entry.id)
                    results.append(r)
        return results[:limit]


class PyramidAggregator:
    """Aggregates facts → patterns → principles (bottom-up pyramid building)."""

    def __init__(self, store: MemoryStore, llm: LLMRouter):
        self._store = store
        self._llm = llm

    def check_and_aggregate(self, domain: str) -> list[MemoryEntry]:
        """Check if a domain has enough facts to aggregate into patterns."""
        created: list[MemoryEntry] = []

        fact_count = self._store.count_by_domain_level(domain, MemoryLevel.FACT)
        pattern_count = self._store.count_by_domain_level(domain, MemoryLevel.PATTERN)

        # Aggregate facts → pattern when threshold reached
        if fact_count >= AGGREGATE_THRESHOLD and fact_count > pattern_count * AGGREGATE_THRESHOLD:
            facts = self._store.list_by_domain(domain, level=MemoryLevel.FACT, limit=20)
            pattern = self._aggregate_to_pattern(domain, facts)
            if pattern:
                created.append(pattern)

        # Aggregate patterns → principle when enough patterns
        if pattern_count >= 3:
            principle_count = self._store.count_by_domain_level(domain, MemoryLevel.PRINCIPLE)
            if principle_count == 0 or pattern_count > principle_count * 3:
                patterns = self._store.list_by_domain(domain, level=MemoryLevel.PATTERN, limit=10)
                principle = self._aggregate_to_principle(domain, patterns)
                if principle:
                    created.append(principle)

        return created

    def _aggregate_to_pattern(self, domain: str, facts: list[MemoryEntry]) -> MemoryEntry | None:
        facts_text = "\n".join(f"- {f.content}" for f in facts)
        prompt = AGGREGATE_PROMPT.format(domain=domain, facts=facts_text)

        try:
            resp = self._llm.generate(prompt, system="You are a concise memory analyst.")
            pattern_text = resp.text.strip()
            if not pattern_text:
                return None

            pattern = MemoryEntry(
                content=pattern_text,
                domain=domain,
                level=MemoryLevel.PATTERN,
                metadata={"source": "aggregation", "fact_count": len(facts)},
            )
            pattern_id = self._store.add(pattern)
            if pattern_id <= 0:
                return None

            # Link facts to pattern
            for f in facts:
                if f.id is not None and f.parent_id is None:
                    f.parent_id = pattern_id
                    self._store.update(f)

            return pattern
        except Exception:
            return None

    def _aggregate_to_principle(
        self, domain: str, patterns: list[MemoryEntry]
    ) -> MemoryEntry | None:
        patterns_text = "\n".join(f"- {p.content}" for p in patterns)
        prompt = PRINCIPLE_PROMPT.format(patterns=patterns_text)

        try:
            resp = self._llm.generate(prompt, system="You are a concise memory analyst.")
            principle_text = resp.text.strip()
            if not principle_text:
                return None

            principle = MemoryEntry(
                content=principle_text,
                domain=domain,
                level=MemoryLevel.PRINCIPLE,
                metadata={"source": "aggregation", "pattern_count": len(patterns)},
            )
            principle_id = self._store.add(principle)
            if principle_id <= 0:
                return None

            for p in patterns:
                if p.id is not None and p.parent_id is None:
                    p.parent_id = principle_id
                    self._store.update(p)

            return principle
        except Exception:
            return None
