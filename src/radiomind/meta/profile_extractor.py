"""LLM-based user profile extraction — language-agnostic.

Replaces the Chinese-only regex in meta/profiles.py. One batch LLM call
per ~30 user turns outputs who/how/what fragments that merge into the
persisted UserProfile.
"""
from __future__ import annotations

import json
import re
from typing import Any


PROFILE_EXTRACT_PROMPT = """Extract PERSONAL PROFILE fragments about the USER from these turns.

Turns are prefixed with [turn_id]. Output three categories:

WHO (stable identity):
  - name, age (integer — the user's CURRENT age; extract whenever the user
    says "I'm N", "I'm N years old", or introduces themselves as "an N-year-old
    X" (e.g. "As a 32-year-old Digital Marketing Specialist..." → age=32).
    DO NOT set age from event-specific mentions like "at the age of 25 I
    graduated" — that's a past-event age, not current.
  - birth_year (YYYY — only when explicitly stated).
  - location, occupation, marital_status, family, pets, relationships.
HOW (style / preferences): things the user likes, dislikes, prefers,
    avoids, habits, communication style, decision tendencies. Each as
    a short phrase.
WHAT (current focus): active projects, near-term goals, recurring
    interests, ongoing learning, upcoming plans.

Only extract what the USER explicitly reveals about THEMSELVES. Ignore
statements about other people unless they affect the user's context
("my wife is pregnant" → who.family = pregnant wife). Use the user's
own language — if they said "I love hiking", output "loves hiking".

Turns:
{turns}

Output STRICT JSON only. Include every "who" field you have evidence for
(age and birth_year are especially important — extract them whenever stated):
{{
  "who": {{"name": "...", "age": 32, "birth_year": 1991, "location": "...", "occupation": "...", "marital_status": "...", "family": "...", "pets": "..."}},
  "how": {{"preferences": ["...", "..."], "aversions": ["..."], "habits": ["..."], "style": ["..."]}},
  "what": {{"goals": ["..."], "interests": ["..."], "current_focus": ["..."]}}
}}

Missing fields: omit the key (don't output empty string). Be concise —
5-20 word fragments. Dedup across turns."""


def _parse_json(raw: str) -> dict | None:
    if not raw:
        return None
    cleaned = re.sub(r"^```(?:json|JSON)?\s*\n?", "", raw.strip())
    cleaned = re.sub(r"\n?```\s*$", "", cleaned).strip()
    try:
        obj = json.loads(cleaned)
        if isinstance(obj, dict):
            return obj
    except Exception:
        return None
    return None


def _format_turn(mid: int, content: str, meta: dict) -> str:
    tid = meta.get("turn_id") or f"mem{mid}"
    snippet = (content or "")[:500].replace("\n", " ")
    if snippet.startswith("[user] ") or snippet.startswith("[USER] "):
        snippet = snippet[7:]
    return f"[{tid}] {snippet}"


def extract_batch(
    user_turns: list[tuple[int, str, dict]],
    llm: Any,
    batch_size: int = 30,
) -> dict[str, dict]:
    """Run LLM profile extraction per batch; merge results.

    Returns {"who": {...}, "how": {...}, "what": {...}}. Later batches
    overwrite earlier values for scalar fields (who); list fields (how/what)
    accumulate deduplicated.
    """
    if not llm or not user_turns:
        return {"who": {}, "how": {}, "what": {}}
    try:
        avail = llm.is_available() if hasattr(llm, "is_available") else True
    except Exception:
        avail = False
    if not avail:
        return {"who": {}, "how": {}, "what": {}}

    merged = {"who": {}, "how": {}, "what": {}}
    for start in range(0, len(user_turns), batch_size):
        chunk = user_turns[start : start + batch_size]
        lines = [_format_turn(mid, content, meta) for mid, content, meta in chunk]
        prompt = PROFILE_EXTRACT_PROMPT.format(turns="\n".join(lines))
        try:
            if hasattr(llm, "generate"):
                resp = llm.generate(prompt, system="Output only strict JSON.")
                raw = getattr(resp, "text", "") or ""
            else:
                raw = llm(prompt, "Output only strict JSON.")
        except Exception:
            continue
        obj = _parse_json(raw)
        if not obj:
            continue

        # Merge who (scalar fields — last non-empty wins). Accept both
        # strings and numeric types: age/birth_year are often emitted as
        # JSON integers and silently dropped if we filter to str only.
        for k, v in (obj.get("who") or {}).items():
            if isinstance(v, str):
                if v.strip():
                    merged["who"][k] = v.strip()
            elif isinstance(v, (int, float)):
                merged["who"][k] = v

        # Merge how/what (list fields — accumulate unique)
        for category in ("how", "what"):
            cat_obj = obj.get(category) or {}
            if not isinstance(cat_obj, dict):
                continue
            for field, values in cat_obj.items():
                if isinstance(values, str):
                    values = [values]
                if not isinstance(values, list):
                    continue
                existing = merged[category].setdefault(field, [])
                for v in values:
                    vs = str(v).strip()
                    if vs and vs not in existing:
                        existing.append(vs)
    return merged
