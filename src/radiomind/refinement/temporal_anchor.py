"""Temporal-anchor extractor.

Dates are sparse and high-value: in a 500-turn haystack ~5-15 turns
actually name a dated event. Embedding retrieval doesn't prioritize
these; they get buried under narrative chatter.

This module extracts them at ingest time into a dedicated L2 PATTERN
bucket (`kind=temporal_anchor`, `event_date=YYYY-MM-DD`) so the temporal
skill at query time scans O(10) anchor entries instead of O(500) raw
turns. One LLM batch call per ~20 user turns.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


ANCHOR_EXTRACT_PROMPT = """Extract dated events from the user turns below.

A "dated event" is an action, decision, purchase, meeting, appointment,
travel, illness, milestone, or any other event that happened on a
specific date the user mentioned. The date may appear as a number
(2023-03-15, March 15 2023, 3/15), or as a relative phrase that the
turn's session_date disambiguates.

Exclude: hypothetical/future plans ("might go next week"), preferences
("I like hiking"), generic state ("I'm a student"). Only events that
actually happened on an identifiable date.

Each turn is labeled `[turn_id session_date]`. Use session_date as the
event date when no explicit in-text date exists.

Turns:
{turns}

Output STRICT JSON only:
{{
  "anchors": [
    {{"event": "cancelled FarmFresh subscription", "date": "2023-01-10", "turn_id": "s3_t2"}},
    {{"event": "participated in 5K charity run at Central Park", "date": "2023-03-05", "turn_id": "s7_t0"}}
  ]
}}

Be exhaustive. Missing an anchor means downstream temporal queries will
fail. Duplicate events across turns emit once (pick earliest turn)."""


@dataclass
class TemporalAnchor:
    event: str
    date: str  # YYYY-MM-DD
    turn_id: str


def _format_turn(mid: int, content: str, meta: dict) -> str:
    tid = meta.get("turn_id") or f"mem{mid}"
    sdate = meta.get("session_date", "")
    prefix = f"[{tid} {sdate}]" if sdate else f"[{tid}]"
    snippet = (content or "")[:500].replace("\n", " ")
    if snippet.startswith("[user] ") or snippet.startswith("[USER] "):
        snippet = snippet[7:]
    return f"{prefix} {snippet}"


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


def extract(
    user_turns: list[tuple[int, str, dict]],
    llm: Any,
    batch_size: int = 20,
    max_chars_per_turn: int = 500,
) -> list[TemporalAnchor]:
    """Batch-extract temporal anchors. Returns dedup'd list."""
    if not llm or not user_turns:
        return []
    try:
        available = llm.is_available() if hasattr(llm, "is_available") else True
    except Exception:
        available = False
    if not available:
        return []

    anchors: dict[tuple[str, str], TemporalAnchor] = {}
    for start in range(0, len(user_turns), batch_size):
        chunk = user_turns[start : start + batch_size]
        lines = [_format_turn(mid, content[:max_chars_per_turn], meta)
                 for mid, content, meta in chunk]
        prompt = ANCHOR_EXTRACT_PROMPT.format(turns="\n".join(lines))
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
        for item in obj.get("anchors", []) or []:
            if not isinstance(item, dict):
                continue
            event = str(item.get("event") or "").strip()
            date = str(item.get("date") or "").strip()[:10]
            turn_id = str(item.get("turn_id") or "").strip()
            if not event or not date:
                continue
            # Normalize date to YYYY-MM-DD best effort
            m = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", date)
            if m:
                date = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
            key = (event.lower()[:80], date)
            if key not in anchors:
                anchors[key] = TemporalAnchor(event=event, date=date, turn_id=turn_id)
    return list(anchors.values())
