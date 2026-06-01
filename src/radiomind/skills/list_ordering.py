"""Chronological list-ordering skill.

Handles "What is the order of X (from earliest to latest)?" — common LME-S
temporal question where the answer is a comma-joined list of N items
sorted by event date.

Pipeline (OrderedEventList-1d/1f):
  1. Extract the entity-type from the question ("airlines", "museums", …).
  2. FACT enumeration: pull the whole domain's FACT layer (recall — gold
     answers are 3-6 needles across ~50 sessions, top-k can't surface all).
  3. Deterministic relevance filter: keep facts whose text shares an entity
     token (singular+plural) — feeding ALL facts to one extractor collapses
     it (1e: 467 facts → 0 instances).
  4. Chunked extraction: extract {name, date} per small chunk (a single
     extractor over a large set under-recovers — 1e: 42 facts → 3/6).
  5. Merge + dedup (collapse repeated mentions), sort by date, render.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from radiomind.skills.base import Skill, SkillResult
from radiomind.skills.date_utils import parse_event_date


_TRIGGER_RE = re.compile(
    r"(?:order|sequence|list)\s+of\s+(.+?)\s+(?:from|in)\s+"
    r"(?:earliest|oldest|chronological|order)",
    re.IGNORECASE,
)
_TRIGGER_RE_2 = re.compile(
    r"what\s+(?:was|is|were)\s+the\s+order\s+of\s+(.+?)(?:[\?\.]|$)",
    re.IGNORECASE,
)

# Stop-words dropped when deriving relevance tokens from the entity noun.
_NOUN_STOP = {
    "the", "a", "an", "my", "our", "his", "her", "their", "of", "in", "on",
    "to", "from", "and", "or", "i", "we", "six", "five", "four", "three",
    "two", "all", "some", "few", "several", "many", "that", "these", "those",
    "did", "do", "have", "had", "been", "was", "were", "is", "are",
}

_CHUNK_SIZE = 10
_CONTENT_CHARS = 400


def _parse_date(s: str) -> datetime | None:
    return parse_event_date(s)


def _extract_noun_from_trigger(query: str) -> str | None:
    """Pull the entity-type phrase from the trigger."""
    for pat in (_TRIGGER_RE, _TRIGGER_RE_2):
        m = pat.search(query)
        if m:
            return m.group(1).strip().rstrip(".,?!")
    return None


def _mem_fields(m: Any) -> tuple[str, str]:
    """Return (session_date, content) for a SearchResult / dict / bare
    MemoryEntry — the three shapes the candidate list can hold."""
    if hasattr(m, "entry"):                       # SearchResult
        meta = m.entry.metadata or {}
        return meta.get("session_date", ""), (m.entry.content or "")
    if isinstance(m, dict):
        return (m.get("created_at") or m.get("session_date", "")), \
               (m.get("memory") or m.get("content") or "")
    if hasattr(m, "content"):                     # bare MemoryEntry (FACT enum)
        meta = getattr(m, "metadata", None) or {}
        return meta.get("session_date", ""), (m.content or "")
    return "", ""


def _relevance_tokens(entity_noun: str) -> set[str]:
    """Content tokens (singular+plural) used to filter candidate facts."""
    toks: set[str] = set()
    for t in re.findall(r"[a-z]+", (entity_noun or "").lower()):
        if len(t) <= 2 or t in _NOUN_STOP:
            continue
        toks.add(t)
        toks.add(t[:-1] if t.endswith("s") else t + "s")  # singular/plural
    return toks


def _relevant_facts(candidates: list, entity_noun: str) -> list:
    """Deterministic relevance filter. Feeding ALL enumerated facts to the
    extractor collapses it (1e); keep only facts whose text contains an
    entity token. Returns candidates unchanged when no usable token."""
    toks = _relevance_tokens(entity_noun)
    if not toks:
        return list(candidates)
    out = []
    for m in candidates:
        _, content = _mem_fields(m)
        low = content.lower()
        if any(t in low for t in toks):
            out.append(m)
    return out


def _chunks(seq: list, size: int = _CHUNK_SIZE) -> list[list]:
    return [seq[i:i + size] for i in range(0, len(seq), size)]


def _extract_chunk(
    query: str, entity_noun: str, chunk: list, llm: Any,
) -> list[dict]:
    """Trinity-extract {name, date} pairs from ONE small chunk of facts."""
    if not llm:
        return []
    from radiomind.refinement.trinity import debate

    mem_lines = []
    for m in chunk:
        sdate, content = _mem_fields(m)
        if not content:
            continue
        mem_lines.append(
            f"[{sdate}] {content[:_CONTENT_CHARS].replace(chr(10), ' ')}")
    if not mem_lines:
        return []
    evidence = "\n".join(mem_lines)

    result = debate(
        task=(
            f"The user asks: '{query}'. From the memories below, extract every "
            f"distinct '{entity_noun}' instance and assign each a date "
            f"(use the bracketed session date when the memory doesn't carry "
            f"its own). Tensions to triangulate: exhaustive-coverage (find "
            f"ALL, even one-off mentions) vs literal-evidence (only emit items "
            f"the memories actually name — no inventing) vs date-certainty "
            f"(prefer items with clear dates; flag ambiguous ones)."
        ),
        evidence=evidence,
        llm=llm,
        extra_schema=(
            '  "instances": [{"name": str, "date": str (YYYY-MM-DD), '
            '"confidence": float}]'
        ),
    )
    if not result:
        return []
    inst = result.get("instances") or []
    if not isinstance(inst, list):
        return []
    out = []
    for item in inst:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        date = str(item.get("date") or "").strip()
        if name and date:
            out.append({
                "name": name, "date": date,
                "confidence": float(item.get("confidence") or 0.7),
            })
    return out


def _collect_instances_via_llm(
    query: str, entity_noun: str, memories: list, llm: Any,
    max_memories: int = 200,
) -> list[dict]:
    """Chunked extraction over the (already relevance-filtered) candidates.
    A single extractor over a large set under-recovers (1e), so extract per
    small chunk and concatenate; merge/dedup happens in resolve."""
    if not llm:
        return []
    out: list[dict] = []
    for chunk in _chunks(memories[:max_memories], _CHUNK_SIZE):
        out.extend(_extract_chunk(query, entity_noun, chunk, llm))
    return out


def _norm_name(name: str) -> str:
    """Normalize an item name for dedup: lowercase, drop leading article,
    collapse whitespace."""
    s = re.sub(r"\s+", " ", (name or "").strip().lower())
    s = re.sub(r"^(the|a|an)\s+", "", s)
    return s


def _merge_dedup(instances: list[dict]) -> list[dict]:
    """Collapse repeated mentions of the same item (D folds in here). Keep
    one per normalized name, preferring the earliest parseable date."""
    by_name: dict[str, dict] = {}
    for it in instances:
        key = _norm_name(it.get("name", ""))
        if not key:
            continue
        cur = by_name.get(key)
        if cur is None:
            by_name[key] = it
            continue
        d_new, d_cur = _parse_date(it.get("date", "")), _parse_date(cur.get("date", ""))
        if d_new is not None and (d_cur is None or d_new < d_cur):
            by_name[key] = it
    return list(by_name.values())


class ListOrderingSkill(Skill):
    name = "list_ordering"
    priority = 12

    def match(self, signature: Any) -> bool:
        return True  # gate by pattern inside resolve

    def resolve(self, query: str, memories: list, context: dict) -> SkillResult | None:
        entity_noun = _extract_noun_from_trigger(query)
        if not entity_noun:
            return None
        mind = context.get("mind")
        llm = mind._llm if mind else None
        if llm is None:
            return None

        # (B) completeness: enumerate the full FACT layer when available.
        candidates = memories
        domain = context.get("domain")
        store = getattr(mind, "_store", None)
        if store is not None and domain:
            try:
                from radiomind.core.types import MemoryLevel
                facts = store.list_by_domain(
                    domain, level=MemoryLevel.FACT, limit=500,
                )
                if facts:
                    candidates = facts
            except Exception:
                pass

        # (1f) deterministic relevance filter — feeding ALL facts to the
        # extractor collapses it (1e: 467 -> 0). Keep only entity-relevant.
        candidates = _relevant_facts(candidates, entity_noun)
        if not candidates:
            return None

        # (1f) chunked extraction + merge/dedup (a single extractor over the
        # whole set under-recovers).
        raw = _collect_instances_via_llm(query, entity_noun, candidates, llm)
        instances = _merge_dedup(raw)
        if len(instances) < 2:
            return None

        # Parse dates + sort
        dated: list[tuple[datetime, dict]] = []
        for inst in instances:
            d = _parse_date(inst["date"])
            if d is not None:
                dated.append((d, inst))
        if len(dated) < 2:
            return None
        dated.sort(key=lambda x: x[0])

        names = [inst["name"] for _, inst in dated]
        answer = ", ".join(names)

        return SkillResult(
            skill_name=self.name,
            answer=answer,
            anchors=[
                (inst["name"], d.strftime("%Y-%m-%d"))
                for d, inst in dated[:10]
            ],
            confidence=0.85,
        )


from radiomind.skills.registry import register  # noqa: E402

register(ListOrderingSkill())
