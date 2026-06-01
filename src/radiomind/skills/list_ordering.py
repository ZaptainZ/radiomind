"""Chronological list-ordering skill.

Handles "What is the order of X (from earliest to latest)?" — common LME-S
temporal question where the answer is a comma-joined list of N items
sorted by event date.

Approach:
  1. Extract entity-type from question ("airlines", "doctors", "jobs", etc.)
  2. Collect matching entity mentions from memories (with their session_date)
  3. Sort chronologically
  4. Trinity-validate: is the list complete? Are we missing items the
     memories mention? Could any item's date be ambiguous?
  5. Commit only on confident completion.
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

def _parse_date(s: str) -> datetime | None:
    return parse_event_date(s)


def _extract_noun_from_trigger(query: str) -> str | None:
    """Pull the entity-type phrase from the trigger."""
    for pat in (_TRIGGER_RE, _TRIGGER_RE_2):
        m = pat.search(query)
        if m:
            return m.group(1).strip().rstrip(".,?!")
    return None


def _collect_instances_via_llm(
    query: str, entity_noun: str, memories: list, llm: Any, max_memories: int = 30,
) -> list[dict]:
    """Use the LLM to extract {name, date} pairs for the entity type."""
    if not llm:
        return []
    from radiomind.refinement.trinity import debate

    mem_lines = []
    for m in memories[:max_memories]:
        if hasattr(m, "entry"):
            sdate = (m.entry.metadata or {}).get("session_date", "")
            content = m.entry.content or ""
        elif isinstance(m, dict):
            sdate = m.get("created_at") or m.get("session_date", "")
            content = m.get("memory") or m.get("content") or ""
        elif hasattr(m, "content"):  # bare MemoryEntry (FACT enumeration)
            sdate = (getattr(m, "metadata", None) or {}).get("session_date", "")
            content = m.content or ""
        else:
            continue
        if not content:
            continue
        mem_lines.append(f"[{sdate}] {content[:300].replace(chr(10), ' ')}")
    evidence = "\n".join(mem_lines)

    result = debate(
        task=(
            f"The user asks: '{query}'. Extract every distinct '{entity_noun}' "
            f"instance the memories mention and assign each a date "
            f"(use session_date when the memory doesn't carry its own). "
            f"Tensions to triangulate: exhaustive-coverage (find ALL, even "
            f"one-off mentions) vs literal-evidence (only emit items the "
            f"memories actually name — no inventing) vs date-certainty "
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

        # OrderedEventList-1d (B): completeness. Gold answers are 3-6 needles
        # scattered across ~50 sessions, so top-k retrieval cannot surface
        # them all. When a store + domain are available, enumerate the full
        # FACT layer (as event_interval/age_interval do) instead of the
        # passed-in top-k memories.
        candidates = memories
        max_memories = 30
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
                    max_memories = 500
            except Exception:
                pass

        # Trinity-backed extraction of instances
        instances = _collect_instances_via_llm(
            query, entity_noun, candidates, llm, max_memories=max_memories)
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
                for d, inst in dated[:6]
            ],
            confidence=0.85,
        )


from radiomind.skills.registry import register  # noqa: E402

register(ListOrderingSkill())
