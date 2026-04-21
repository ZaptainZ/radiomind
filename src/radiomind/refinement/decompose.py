"""Query-time atomic decomposition.

When the attention classifier flags a query as "aggregation" (counting,
listing, comparison across sessions), the base retrieval returns a handful
of raw narrative turns — but the LLM answer model then has to parse each
turn, identify all mentions of the target entity, deduplicate, and count.
Qwen/GPT do this unreliably, which is why RadioMind loses on
multi-session questions vs Mem0's extractive architecture.

This module restores the atomic-fact view **at query time, not ingest
time** — preserving the narrative in storage while giving the answer
layer an enumeration view when the query demands it. A single focused
LLM call extracts, deduplicates, and scores per-fact confidence.

Output atoms are also candidates for *promotion*: if the same atom
surfaces across multiple queries, gets KG-crossverified, and is not
redundant with existing L2 PATTERN memories, it earns promotion from
query-scope transient to persistent L2 fact. Memory consolidates
through use — the attention-driven pipeline is also the learning
pipeline.

Design stays consistent with RadioMind's ground-truth-preserving
philosophy: no raw turn is ever rewritten or discarded. Atomic facts
live alongside, not in place of, the source turns.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

from radiomind.core.llm import LLMRouter
from radiomind.core.types import MemoryEntry, MemoryLevel, SearchResult
from radiomind.storage.database import MemoryStore


DECOMPOSE_PROMPT = """You are extracting atomic facts from retrieved conversation turns so that an aggregation question can be answered precisely.

Question: {question}
Focus entity (if obvious): {focus}

Retrieved turns (ranked by relevance, each prefixed with its turn_id):

{memories}

Task: Extract every factual claim from these turns that bears on the question.

Rules:
1. **Atomic**: one subject, one predicate, one object per fact. Split compound sentences.
2. **Literal entity names**: use the exact names from the turns ("Dr. Smith", not "my doctor").
3. **Dedupe with counts**: if the same entity/fact appears multiple times across turns, emit ONE fact with count equal to the number of distinct mentions.
4. **Relevance filter**: skip facts unrelated to the question's focus.
5. **Cite evidence**: each fact lists the turn_id(s) it was derived from.
6. **Confidence 0-1**: 1.0 for explicit user statement, 0.7 for implied, 0.5 for assistant-suggested.
7. **No hallucination**: if a turn says "I might visit Dr. X next week", do NOT emit "user visited Dr. X" — emit "user planned to visit Dr. X (not confirmed)" instead.

Output STRICT JSON only — no prose, no markdown fencing:
{{
  "atoms": [
    {{"fact": "user visited Dr. Smith (primary care physician)", "count": 2, "evidence": ["s3_t5", "s7_t2"], "confidence": 0.95}},
    {{"fact": "user visited Dr. Lee (dermatologist) for biopsy", "count": 1, "evidence": ["s4_t1"], "confidence": 0.90}}
  ]
}}

If no relevant facts exist, output: {{"atoms": []}}"""


_JSON_OBJECT_RE = re.compile(r"\{[\s\S]*\}")


@dataclass
class Atom:
    """A query-scope atomic fact extracted from retrieved turns."""
    fact: str
    count: int = 1
    evidence: list[str] = field(default_factory=list)
    confidence: float = 0.8
    # Populated by downstream consumers (promotion logic)
    kg_verified: bool = False
    hit_count: int = 1  # times this atom has appeared across past queries
    promoted: bool = False  # has this been stored as L2 PATTERN


class QueryDecomposer:
    """Extract atomic facts from retrieved turns for aggregation-type queries.

    Stateful across calls via `_atom_cache` (keyed by domain) — so atoms
    that surface in query 1 and again in query 5 accumulate hit_count and
    become candidates for promotion.

    Single LLM call per decompose() — cheaper than the full three-body
    ingest-time debate, and only fires on aggregation queries. Three-body
    upgrade can replace _decompose_once later if quality isn't sufficient.
    """

    def __init__(self, store: MemoryStore, llm: LLMRouter, kg=None, embedder=None):
        self._store = store
        self._llm = llm
        self._kg = kg
        self._embedder = embedder
        # {domain: [Atom, Atom, ...]} — persistent across the Mind lifetime
        self._atom_cache: dict[str, list[Atom]] = {}

    def is_available(self) -> bool:
        return self._llm is not None and self._llm.is_available()

    def decompose(
        self,
        question: str,
        retrieved: list[SearchResult],
        domain: str,
        focus: str | None = None,
        max_turns_in: int = 30,
        max_atoms_out: int = 20,
    ) -> list[Atom]:
        """Run atomic decomposition on top-k retrieved turns.

        Returns Atoms sorted by confidence descending. On LLM error or
        empty retrieval, returns []. Side effect: updates _atom_cache for
        the domain, which powers hit_count tracking.
        """
        if not self.is_available() or not retrieved:
            return []

        # Evidence guard: if the focus entity (or any strong noun from the
        # question) doesn't appear in any top-k content, there's nothing
        # to decompose — emitting atoms here would invite the LLM to
        # fabricate. Abstention-type questions ("how many pages left in
        # Sapiens" when haystack has no Sapiens mention) must fall
        # through to the answer model's "insufficient" verdict.
        if not self._has_relevant_evidence(
            question, focus, retrieved[:max_turns_in]
        ):
            return []

        # Build turn-id-prefixed memory block
        turns_text = self._format_turns(retrieved[:max_turns_in])
        focus_label = focus or "(inferred from question)"
        prompt = DECOMPOSE_PROMPT.format(
            question=question, focus=focus_label, memories=turns_text,
        )

        try:
            resp = self._llm.generate(
                prompt, system="You are an atomic fact extractor. Output valid JSON only."
            )
            raw = resp.text or ""
        except Exception:
            return []

        atoms = self._parse_atoms(raw)[:max_atoms_out]
        if not atoms:
            return []

        # Enrich with KG cross-check (boosts confidence on verified facts)
        if self._kg is not None:
            for atom in atoms:
                if self._kg_verifies(atom):
                    atom.kg_verified = True
                    atom.confidence = min(1.0, atom.confidence + 0.1)

        # Update cache (hit-count tracking)
        self._merge_into_cache(domain, atoms)

        atoms.sort(key=lambda a: -a.confidence)
        return atoms

    def promote_if_valuable(
        self,
        atoms: list[Atom],
        domain: str,
        min_confidence: float = 0.7,
        min_hits: int = 2,
    ) -> list[MemoryEntry]:
        """Promote qualifying atoms to L2 PATTERN memory entries.

        Criteria (default):
          - confidence >= min_confidence (0.7)
          - hit_count >= min_hits (2, i.e. atom surfaced in >=2 queries)
          - not substantially redundant with existing L2 PATTERN in this domain

        Returns the MemoryEntry objects created (may be empty list).

        Note on philosophy: we never DELETE the source turn — promoted
        atoms live alongside, giving the pyramid both a narrative layer
        and a factoid layer. Mem0 collapses everything into facts; we
        keep both.
        """
        if not atoms:
            return []
        created: list[MemoryEntry] = []
        existing_patterns = self._store.list_by_domain(
            domain, level=MemoryLevel.PATTERN, limit=50
        ) if self._store else []
        existing_texts = [p.content.lower() for p in existing_patterns]

        for atom in atoms:
            if atom.promoted:
                continue
            if atom.confidence < min_confidence:
                continue
            if atom.hit_count < min_hits:
                continue
            # Redundancy check: substring match with any existing PATTERN
            atom_lower = atom.fact.lower()
            if any(atom_lower in e or e in atom_lower for e in existing_texts):
                continue

            content = atom.fact if atom.count <= 1 else f"{atom.fact} (count={atom.count})"
            entry = MemoryEntry(
                content=content,
                domain=domain,
                level=MemoryLevel.PATTERN,
                metadata={
                    "source": "query_decompose",
                    "confidence": atom.confidence,
                    "hit_count": atom.hit_count,
                    "evidence": ",".join(atom.evidence[:5]),
                    "kg_verified": atom.kg_verified,
                },
            )
            if self._embedder is not None:
                try:
                    entry.embedding = self._embedder.encode(entry.content)
                except Exception:
                    pass
            mid = self._store.add(entry, dedup=False)
            if mid > 0:
                atom.promoted = True
                created.append(entry)
                existing_texts.append(atom_lower)  # update in-loop to dedupe subsequent
        return created

    # ---------- internals ----------

    _STOP = {
        "what", "which", "how", "when", "where", "who", "why", "do", "did",
        "does", "have", "had", "has", "is", "are", "was", "were", "am", "my",
        "your", "our", "their", "his", "her", "the", "a", "an", "of", "to",
        "in", "on", "at", "for", "by", "with", "from", "as", "that", "this",
        "many", "much", "long", "some", "any", "all",
    }

    @classmethod
    def _question_noun_tokens(cls, question: str, focus: str | None) -> set[str]:
        import re as _re
        tokens = set()
        if focus:
            for t in _re.findall(r"[a-z0-9]+", focus.lower()):
                if len(t) > 2 and t not in cls._STOP:
                    tokens.add(t)
        for t in _re.findall(r"[a-z0-9]+", (question or "").lower()):
            if len(t) > 2 and t not in cls._STOP and not t.isdigit():
                tokens.add(t)
        return tokens

    @classmethod
    def _has_relevant_evidence(
        cls, question: str, focus: str | None, retrieved: list[SearchResult],
    ) -> bool:
        """Refuse to decompose when top-k carries no content relevant to the question.

        Requires at least one question noun-token to appear in some retrieved
        turn's content. Tokens are filtered to content words (length > 2,
        non-stop, non-digit); if the question yields zero such tokens
        (degenerate), we keep the old permissive behavior.
        """
        needles = cls._question_noun_tokens(question, focus)
        if not needles:
            return True
        for r in retrieved:
            content = (r.entry.content or "").lower()
            if any(n in content for n in needles):
                return True
        return False

    @staticmethod
    def _format_turns(retrieved: list[SearchResult]) -> str:
        lines = []
        for r in retrieved:
            meta = r.entry.metadata or {}
            tid = meta.get("turn_id") or meta.get("evidence_id") or f"mem{r.entry.id or 0}"
            sdate = meta.get("session_date", "")
            prefix = f"[{tid}]"
            if sdate:
                prefix += f" ({sdate})"
            lines.append(f"{prefix} {r.entry.content}")
        return "\n".join(lines)

    @staticmethod
    def _parse_atoms(raw: str) -> list[Atom]:
        """Lenient JSON parser for the decomposer output."""
        if not raw:
            return []
        text = raw.strip()
        # Strip common markdown fences qwen/gpt like to wrap JSON in
        # even when the prompt says "no markdown".
        if text.startswith("```"):
            text = re.sub(r"^```(?:json|JSON)?\s*\n?", "", text)
            text = re.sub(r"\n?```\s*$", "", text)
            text = text.strip()
        m = _JSON_OBJECT_RE.search(text)
        extracted = m.group(0) if m else ""
        for candidate in (text, extracted):
            if not candidate:
                continue
            try:
                obj = json.loads(candidate)
                items = obj.get("atoms") if isinstance(obj, dict) else obj
                if not isinstance(items, list):
                    continue
                out: list[Atom] = []
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    fact = str(it.get("fact", "")).strip()
                    if not fact:
                        continue
                    evidence = it.get("evidence") or []
                    if not isinstance(evidence, list):
                        evidence = [str(evidence)]
                    try:
                        count = int(it.get("count", 1))
                    except (ValueError, TypeError):
                        count = 1
                    try:
                        conf = float(it.get("confidence", 0.8))
                        conf = max(0.0, min(1.0, conf))
                    except (ValueError, TypeError):
                        conf = 0.8
                    out.append(Atom(
                        fact=fact,
                        count=max(1, count),
                        evidence=[str(e) for e in evidence[:10]],
                        confidence=conf,
                    ))
                return out
            except json.JSONDecodeError:
                continue
        return []

    def _kg_verifies(self, atom: Atom) -> bool:
        """Light check: does the atom's text overlap with any existing KG triple?"""
        if self._kg is None:
            return False
        try:
            text_low = atom.fact.lower()
            triples = getattr(self._kg, "all_triples", None)
            if triples:
                for t in triples(limit=200):
                    subj = getattr(t, "subject", "").lower()
                    obj = getattr(t, "object", "").lower()
                    if subj and subj in text_low and obj and obj in text_low:
                        return True
        except Exception:
            pass
        return False

    def _merge_into_cache(self, domain: str, atoms: list[Atom]) -> None:
        """Update hit_count on atoms that re-appear across queries."""
        bucket = self._atom_cache.setdefault(domain, [])
        for new_atom in atoms:
            match = self._find_similar(bucket, new_atom)
            if match is not None:
                match.hit_count += 1
                match.confidence = max(match.confidence, new_atom.confidence)
                # Take the new atom's hit_count forward so caller sees
                # accumulated evidence, not the bucket's private counter.
                new_atom.hit_count = match.hit_count
                # Merge evidence list (dedup, cap)
                combined = list({*match.evidence, *new_atom.evidence})[:10]
                match.evidence = combined
                new_atom.evidence = combined
            else:
                bucket.append(new_atom)
        # Cap bucket growth — drop lowest-confidence tail
        if len(bucket) > 200:
            bucket.sort(key=lambda a: (-a.hit_count, -a.confidence))
            del bucket[200:]

    @staticmethod
    def _find_similar(bucket: list[Atom], candidate: Atom) -> Atom | None:
        """Very loose fuzzy match — exact substring or high overlap."""
        cand_low = candidate.fact.lower()
        cand_tokens = set(re.findall(r"\w+", cand_low))
        if not cand_tokens:
            return None
        for existing in bucket:
            ex_low = existing.fact.lower()
            if cand_low == ex_low or cand_low in ex_low or ex_low in cand_low:
                return existing
            ex_tokens = set(re.findall(r"\w+", ex_low))
            if not ex_tokens:
                continue
            jaccard = len(cand_tokens & ex_tokens) / len(cand_tokens | ex_tokens)
            if jaccard >= 0.8:
                return existing
        return None
